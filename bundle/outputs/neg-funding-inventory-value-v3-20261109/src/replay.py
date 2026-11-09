from common import *
import joblib,time
SOURCE=ROOT.parent/'neg-funding-aligned-research-20261109'

def predict_probability(head,X):
 p=np.clip(head['estimator'].predict_proba(X)[:,1],1e-6,1-1e-6)
 return head['calibrator'].predict_proba(np.log(p/(1-p)).reshape(-1,1))[:,1]

def schedule_inventory(h,ids,score,symbols,capq,notices,T,lo,end,days,slots,method):
 request=np.full(len(symbols),T+1000,dtype=np.int64);rows=[]
 for t in range(lo,end,24*days):
  ix=np.flatnonzero(h==t);n=ids[ix];p=score[ix];ok=np.isfinite(p)&(capq[n]>0)&(t<notices[n])&(request[n]>T);n=n[ok];p=p[ok]
  if method.startswith('random_'):
   seed=method.split('_')[1];p=np.array([int(hashlib.sha256(f'{seed}:{t}:{symbols[j]}'.encode()).hexdigest()[:13],16)/16**13 for j in n])
  order=np.argsort(-p,kind='stable')[:slots]
  for q in order:
   j=n[q];request[j]=t;rows.append({'request_hour':int(t),'available_hour':int(t+72),'symbol':str(symbols[j]),'score':float(p[q])})
 return np.arange(T)[:,None]>=request[None,:]+72,request,rows

def main():
 protocol=json.loads((ROOT/'PROTOCOL.json').read_text());log('v3_portfolio_replays_started')
 import runtime_boot as B
 gate,capq=B.setup();T=B.T;N=B.N;d=loadnp(ROOT/'data/features.npz');h=d['hours'];ids=d['symbol_id'];symbols=d['symbols'];assert symbols.tolist()==B.D.fut
 data=loadnp(ROOT/'data/scores.npz');scores={m:data[m] for m in ['hurdle_full','hurdle_base90','hurdle_no_cross','direct_HGB','ridge','MLP64_32','old_short_net','latest_negative','EMA72','EMA720','capacity_EMA72','raw_cash_EMA720']}
 for seed in range(20261109,20261119):scores['random_'+str(seed)]=np.where(d['eligible'][:,None],np.zeros((len(h),2)),np.nan)
 raw=B.D.arr[6];units=np.rint(np.nan_to_num(raw)/1e-8).astype(np.int64);cs=np.vstack([np.zeros((1,N),np.int64),np.cumsum(units,axis=0)]);exact=np.zeros_like(raw);exact[23:]=(cs[24:]-cs[:-24])*1e-8;B.RR.sum24=exact
 original=B.RR.run;current={'mask':None,'fraction':1.}
 def restricted(*a,**kw):kw['ok_t']=kw['ok_t']&current['mask'];kw['capq']=capq.copy()*current['fraction'];return original(*a,**kw)
 B.RR.run=restricted;close=pd.DataFrame(B.D.arr[1]).where(lambda x:x>0).ffill().to_numpy();qualified=loadnp(SOURCE/'data/replay_inputs.npz')['qualified']
 results=[];requests=[];curves={};cache={};masks={};start=time.monotonic();actual_runs=0
 definitions=[]
 methods=[m for m in scores if not m.startswith('random')]
 for period,limits in protocol['portfolio']['periods'].items():
  lo,end,hi=map(hour,limits)
  for method in ['all_ready','request_all_72h']:definitions.append((period,lo,end,hi,method,0,0,4.,1.,'long_period'))
  for days,slots in [(15,20),(30,20),(30,40)]:
   for method in methods:definitions.append((period,lo,end,hi,method,days,slots,4.,1.,'long_period'))
  for method in [m for m in scores if m.startswith('random')]:definitions.append((period,lo,end,hi,method,15,20,4.,1.,'random_control'))
  for method in ['hurdle_full','EMA72','EMA720','capacity_EMA72','raw_cash_EMA720']:
   definitions.append((period,lo,end,hi,method,15,20,4.,.5,'half_inventory'))
   definitions.append((period,lo,end,hi,method,15,20,0.,1.,'exogenous_control'))
 for month in range(3,11):
  first=pd.Timestamp(f'2026-{month:02}-01',tz='UTC');until=pd.Timestamp('2026-10-30',tz='UTC') if month==10 else first+pd.offsets.MonthBegin(1);lo=hour(first);end=hour(until);hi=end+216;period='earlier' if month<7 else 'later'
  for method in ['hurdle_full','old_short_net','EMA72','EMA720','capacity_EMA72','raw_cash_EMA720']:definitions.append((period,lo,end,hi,method,15,20,4.,1.,'monthly_cold_start'))
 for i,(period,lo,end,hi,method,days,slots,k,fraction,scope) in enumerate(definitions):
  assert hi<=T and hi-end==216
  canonical=method
  key=(lo,end,hi,canonical,days,slots,k,fraction)
  name=f'{scope}_{stamp(lo)[:10]}_{method}_{days}d_{slots}_k{k:g}_q{fraction:g}'
  alias=key in cache
  if alias:
   prior=cache[key];row=dict(prior,case=name,method=method,scope=scope,alias_of=prior['case']);curves[name]=curves[prior['case']]
  else:
   maskkey=(lo,end,canonical,days,slots,fraction)
   if maskkey not in masks:
    if method=='all_ready':mask=np.ones((T,N),bool);request=np.full(N,lo-72);rec=[]
    elif method=='request_all_72h':
     listed=np.zeros((T,N),bool);listed[1:]=(B.D.arr[1][:-1]>0)&(B.D.arr[4][:-1]>0);listed&=(np.arange(T)[:,None]<B.D.dl_exit[None,:])&(capq>0)[None,:];listed[:lo]=False;seen=listed.any(axis=0);request=np.where(seen,listed.argmax(axis=0),T+1000);mask=np.arange(T)[:,None]>=request[None,:]+72;rec=[]
    else:mask,request,rec=schedule_inventory(h,ids,scores[method][:,int(fraction==1.)],symbols,capq,B.D.dl_exit,T,lo,end,days,slots,method)
    masks[maskkey]=(mask,request)
    for x in rec:requests.append(dict(x,period=period,scope=scope,signal_start=stamp(lo),method=method,days=days,slots=slots))
   mask,request=masks[maskkey];current['mask']=mask;current['fraction']=fraction;parameters={z:float(v) for z,v in B.RESEARCH['parameters'].items()};parameters.update(tail_hours=0,trade_end=float(end+24),k_imp=k);B.RR.WINS['cross_period']=(lo,hi);r=B.V.run_fix('cons_c0','cross_period',extra=parameters,oi_frac=.025,m=2.)
   acc=r['accounts'];cash_identity=acc[:,0]-acc[:,4]+acc[:,1]+acc[:,2]-1e7;err=float(abs(cash_identity-r['cum']).max());assert err<.002
   qty=np.divide(r['pos'],close[lo:hi],out=np.zeros_like(r['pos']),where=close[lo:hi]>0);assert np.all(qty<=fraction*capq[None,:]+1e-7*np.maximum(1,capq)[None,:]);assert not ((qty>1e-9)&~mask[lo:hi]).any()
   ep=r['ep'];closed_net=float((ep[:,3]-ep[:,6]).sum());net=float(r['cum'][-1]);remaining=int((qty[-1]>1e-9).sum());comp=r['comp'][-1];assert abs(net-(comp[0]+comp[1]-comp[2]+comp[5]))<.001
   if remaining==0:assert abs(net-closed_net)<.002
   margin=np.maximum(0.,acc[:,3]-acc[:,1]-acc[:,2]);curve=np.diff(np.r_[0.,r['cum']]);curves[name]=curve;dd=np.maximum.accumulate(np.r_[0.,r['cum']])-np.r_[0.,r['cum']]
   q=qualified[lo:end];row={'case':name,'period':period,'scope':scope,'quantity_fraction':fraction,'method':method,'refresh_days':days,'new_slots':slots,'k_scenario':k,'k_is_causally_identified':False,'signal_start':stamp(lo),'signal_end_exclusive':stamp(end),'accounting_end_exclusive':stamp(hi),'closed_net_usdt':closed_net,'marked_net_usdt':net,'remaining_sold_coin_liability_mark_usdt':float(r['pos'][-1].sum()),'remaining_symbols':remaining,'closed_episodes':len(ep),'funding_net_usdt':float(comp[0]),'pair_price_after_cost_usdt':float(comp[1]+comp[5]),'fee_usdt':float(comp[2]),'mean_position_usdt':float(r['pos'].sum(axis=1).mean()),'peak_cost_basis_usdt':float(r['diag'][12]),'capital_binding_candidate_hours':float(r['xd'][4]),'max_drawdown_usdt':float(dd.max()),'requested_coins':int((request<T).sum()),'arrived_before_signal_end':int((request+72<end).sum()),'qualified_coin_hour_coverage':float((q&mask[lo:end]).sum()/q.sum()) if q.any() else None,'cash_identity_max_error_usdt':err,'one_x_gap_hours_close_proxy':int((margin>1e-6).sum()),'inventory_and_arrival_checks_passed':True,'parameters':r['resolved_engine_parameters'],'alias_of':None}
   cache[key]=row;actual_runs+=1
   if not method.startswith('random'):
    trades=pd.DataFrame(ep,columns=['coin_id','start_hour','end_hour','pair_plus_funding','peak_notional','side','fee','fills','funding','spread_impact_in_price','own_funding_deduction']);trades['symbol']=[B.D.fut[int(n)] for n in trades.coin_id];trades['net_usdt']=trades.pair_plus_funding-trades.fee;coin=trades.groupby('symbol').agg(net_usdt=('net_usdt','sum'),funding_net_usdt=('funding','sum'),fee_usdt=('fee','sum'));coin.to_csv(OUT/(name+'_coin_pnl.csv'))
   del r,qty
  results.append(row)
  if i%12==0 or method=='hurdle_full':
   save(OUT/'PROGRESS.json',{'completed_rows':len(results),'planned_rows':len(definitions),'actual_engine_runs':actual_runs,'elapsed_seconds':time.monotonic()-start});print(json.dumps(clean({z:row[z] for z in ['period','scope','method','refresh_days','new_slots','closed_net_usdt','remaining_symbols','alias_of']})),flush=True)
  save(OUT/'RESULTS.partial.json',{'cases':results,'planned_rows':len(definitions)})
 pd.DataFrame(requests).to_csv(OUT/'borrow_requests.csv',index=False);pd.DataFrame([{z:v for z,v in x.items() if z!='parameters'} for x in results]).to_csv(OUT/'summary.csv',index=False);np.savez_compressed(OUT/'hourly_curves.npz',**curves)
 save(OUT/'RESULTS.json',{'created_at':now(),'cases':results,'rows':len(results),'actual_engine_runs':actual_runs,'component_fits':json.loads((OUT/'TRAINING_AUDIT.json').read_text())['component_fits'],'elapsed_seconds':time.monotonic()-start,'protocol_sha256':sha(ROOT/'PROTOCOL.json'),'separate_cold_starts_not_one_continuous_portfolio':True,'monthly_windows_overlap_not_independent_trials':True,'formal_strategy_changed':False});log('v3_portfolio_replays_completed',actual_engine_runs=actual_runs,rows=len(results))
 print(json.dumps({'rows':len(results),'actual_engine_runs':actual_runs,'elapsed_seconds':time.monotonic()-start}),flush=True)
if __name__=='__main__':main()
