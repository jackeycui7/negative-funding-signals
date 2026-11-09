from common import *
from event_diagnostics import selected
from features import SOURCE

def main():
 f=loadnp(ROOT/'data/features.npz');d=loadnp(SOURCE/'data/daily_samples.npz');lookup={(int(t),str(f['symbols'][int(n)])):i for i,(t,n) in enumerate(zip(f['hours'],f['symbol_id']))};p=pd.read_csv(OUT/'event_predictions.csv');out=[];records=[]
 for method,g in p[(p.task=='arrival_entry_7d')&(p.month<=10)].groupby('method'):
  ii=np.array([lookup[(int(t),s)] for t,s in zip(g.hour,g.symbol)]);gn=g.loc[f['X'][ii,0]>=0];alert=selected(gn);jj=np.array([lookup[(int(t),s)] for t,s in zip(alert.hour,alert.symbol)]);alert['latest_r8_bp']=f['X'][jj,0];alert['interval_h']=f['X'][jj,f['columns'].tolist().index('latest_settled_interval_hours')];alert['method']=method;alert['y']=d['y_arrival'][jj];alert['observed']=np.isfinite(alert.y);known=alert[alert.observed];out.append({'method':method,'pool':'currently_nonnegative_only','alerts':len(alert),'observed':len(known),'hits':int(known.y.sum()),'known_precision':float(known.y.mean()),'unknown_outcomes':len(alert)-len(known),'conservative_lower_precision':float(known.y.sum()/len(alert)),'upper_precision_all_unknown_hit':float((known.y.sum()+len(alert)-len(known))/len(alert))});records.append(alert)
 pd.concat(records).to_csv(OUT/'pre_turn_arrival_alerts.csv',index=False);save(OUT/'PRE_TURN_ARRIVAL_RESULTS.json',{'created_at':now(),'subgroup_analysis_not_new_training':True,'summary':out,'scope':'Rank arrival probability only amongcurrentlynonnegativecoins; top10/day72hcoin cooldown, same alert budget asordinaryturn experiment. Targetisqualifiedopportunity after72hdelivery, not actual profits.'});print(json.dumps(clean(out)),flush=True)
if __name__=='__main__':main()
