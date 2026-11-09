from common import *
from features import SOURCE
from train import evaluate
import joblib,time

def main():
 r=json.loads((OUT/'RESULTS.json').read_text());f=pd.DataFrame(r['cases']);long=f[f.scope=='long_period'];table=long[['period','method','refresh_days','new_slots','closed_net_usdt','marked_net_usdt','remaining_symbols','funding_net_usdt','pair_price_after_cost_usdt','fee_usdt','max_drawdown_usdt','mean_position_usdt','peak_cost_basis_usdt','capital_binding_candidate_hours','arrived_before_signal_end','qualified_coin_hour_coverage']];table.to_csv(OUT/'portfolio_comparison.csv',index=False)
 contributions=[];comparisons=[]
 for period in ['earlier','later']:
  a=long[(long.period==period)&(long.method=='hurdle_full')&(long.refresh_days==15)].iloc[0];aa=pd.read_csv(OUT/(a['case']+'_coin_pnl.csv')).set_index('symbol')
  for baseline in ['old_short_net','EMA72','EMA720','capacity_EMA72','raw_cash_EMA720','hurdle_base90','hurdle_no_cross']:
   b=long[(long.period==period)&(long.method==baseline)&(long.refresh_days==15)].iloc[0];bb=pd.read_csv(OUT/(b['case']+'_coin_pnl.csv')).set_index('symbol');j=aa[['net_usdt','funding_net_usdt','fee_usdt']].join(bb[['net_usdt','funding_net_usdt','fee_usdt']],how='outer',lsuffix='_v3',rsuffix='_baseline').fillna(0);j['delta_net_usdt']=j.net_usdt_v3-j.net_usdt_baseline;j=j.sort_values('delta_net_usdt',ascending=False);delta=float(j.delta_net_usdt.sum());largest=j.iloc[0];comparisons.append({'period':period,'baseline':baseline,'delta_net_usdt':delta,'biggest_positive_contributor':str(j.index[0]),'biggest_positive_delta_usdt':float(largest.delta_net_usdt),'other_coins_delta_usdt':delta-float(largest.delta_net_usdt),'coin_subtraction_not_exclusion_rerun':True});j.to_csv(OUT/(period+'_v3_vs_'+baseline+'_coin_delta.csv'));contributions.extend([dict(period=period,baseline=baseline,symbol=s,**row.to_dict()) for s,row in j.iterrows()])
 pd.DataFrame(comparisons).to_csv(OUT/'incremental_concentration.csv',index=False)
 monthly=f[f.scope=='monthly_cold_start'].pivot(index='signal_start',columns='method',values='closed_net_usdt');monthly.to_csv(OUT/'monthly_cold_start_comparison.csv')
 # Overlapping30day labels: date-level diagnostics only, no iid confidence interval.
 pp=pd.read_csv(OUT/'oos_predictions.csv');pp=pp[(pp.quantity_fraction==1)&(pp.family!='hurdle_coin_holdout')];pivot=pp.pivot(index=['hour','symbol'],columns='family',values='prediction_usdt');ys=pp.drop_duplicates(['hour','symbol']).set_index(['hour','symbol']).net_label_usdt;common=pivot.notna().all(axis=1);common_records=[]
 for method in pivot:
  ix=pivot.index[common];common_records.append(dict(method=method,common_rows=int(common.sum()),**evaluate(ys.loc[ix].to_numpy(),pivot.loc[ix,method].to_numpy(),ix.get_level_values('hour').to_numpy())))
 pd.DataFrame(common_records).to_csv(OUT/'same_rows_prediction_summary.csv',index=False)
 held=pd.read_csv(OUT/'oos_predictions.csv');held=held[(held.quantity_fraction==1)&held.coin_holdout];holdmetrics=[]
 for family,g in held[held.family.isin(['hurdle_full','hurdle_coin_holdout','EMA72','capacity_EMA72'])].groupby('family'):holdmetrics.append(dict(family=family,**evaluate(g.net_label_usdt.to_numpy(),g.prediction_usdt.to_numpy(),g.hour.to_numpy())))
 pd.DataFrame(holdmetrics).to_csv(OUT/'coin_generalization_same_rows.csv',index=False)
 # Group permutation diagnostics use held-out predictions, same timestamp and quantity strata.
 d=loadnp(ROOT/'data/labels.npz');X=d['X'];cols=d['columns'].tolist();y=d['net_usdt'];h=d['hours'];models=joblib.load(ROOT/'data/models.joblib');groups={'past_cycle':[i for i,n in enumerate(cols) if n.startswith(('cash_nonpositive_age','last_completed_cash','completed_cash','completed_cycle','completed_long','cash_nonpositive_fraction'))],'cross_venue':[i for i,n in enumerate(cols) if n.startswith(('cross_','bybit_','binance_minus_bybit_'))],'quantity_capacity':list(range(X.shape[1]-9,X.shape[1])),'raw_cash_EMA':[i for i,n in enumerate(cols) if n.startswith('raw_payment_EMA')],'premium':[i for i,n in enumerate(cols) if n.startswith('premium_')],'OI_volume_price':[i for i,n in enumerate(cols) if any(s in n for s in ['return_','OI_','volume_','basis_','volatility_'])],'positioning':[i for i,n in enumerate(cols) if n.startswith(('global_accounts','top_accounts','top_positions','taker_flow'))]};perm=[]
 for month in range(3,10):
  cut=hour(f'2026-{month:02}-01');until=hour(pd.Timestamp(f'2026-{month:02}-01')+pd.offsets.MonthBegin(1));use=(h>=cut)&(h<until)&(d['quantity_fraction']==1);xx=X[use];yy=y[use];hh=h[use];m=models['models'][str(month)]['estimators']['hurdle_full'];p=m.predict(xx);reference=evaluate(yy,p,hh)['top20_mean_usdt'];rng=np.random.default_rng(20261109+month)
  for group,indices in groups.items():
   for rep in range(3):
    z=xx.copy()
    for date in np.unique(hh):
     loc=np.flatnonzero(hh==date);shuffle=rng.permutation(loc);z[np.ix_(loc,indices)]=xx[np.ix_(shuffle,indices)]
    value=evaluate(yy,m.predict(z),hh)['top20_mean_usdt'];perm.append(dict(month=month,group=group,repetition=rep,top20_reference_usdt=reference,permuted_top20_usdt=value,drop_usdt=reference-value))
 pd.DataFrame(perm).to_csv(OUT/'group_permutation_diagnostic.csv',index=False)
 primary=long[(long.method=='hurdle_full')&(long.refresh_days==15)];criteria={}
 for b in ['EMA72','EMA720','capacity_EMA72']:
  criteria['beats_'+b+'_both_periods']=all(primary.set_index('period').closed_net_usdt>long[(long.method==b)&(long.refresh_days==15)].set_index('period').closed_net_usdt)
 criteria['positive_increment_without_largest_coin_both_periods']=all(x['other_coins_delta_usdt']>0 for x in comparisons if x['baseline']=='EMA72')
 passed=all(criteria.values());decision={'created_at':now(),'economic_primary':'hurdle_full_fixed_before_training','economic_gate_passed':passed,'criteria':criteria,'production_change':False,'status':'WATCH_ONLY' if not passed else 'RESEARCH_PASSED_NOT_PROSPECTIVE','no_test_based_family_switch':True,'capital_competition_in_observed_allready_runs':{'peak_cost_usdt':float(long[long.method=='all_ready'].peak_cost_basis_usdt.max()),'binding_candidate_hours':float(long[long.method=='all_ready'].capital_binding_candidate_hours.sum())},'independent_coin_label_is_reference_not_marginal_joint_value':True,'cross_venue_effect_not_consistent':True,'regressor_value_not_profit_probability':True,'all_tested_model_families_reported':True,'own_impact_k4_unidentified':True,'prior_and_formal_runs_unchanged_pending_final_hash_check':True};save(ROOT/'ADOPTION_DECISION.json',decision);print(json.dumps(clean(decision)),flush=True)
 # Independent source decomposition, not model inputs.
 tr=pd.read_csv(SOURCE/'results/all_ready_closed_trades.csv');tr['duration_h']=tr.end_hour-tr.start_hour;tr['duration_group']=pd.cut(tr.duration_h,[-1,24,72,168,336,100000],labels=['<=1d','1-3d','3-7d','7-14d','>14d']);tr.groupby('duration_group',observed=False).agg(episodes=('net_usdt','size'),net_usdt=('net_usdt','sum'),funding_usdt=('funding','sum'),fees_usdt=('fee','sum')).to_csv(OUT/'source_pnl_by_completed_holding_duration.csv')
if __name__=='__main__':main()
