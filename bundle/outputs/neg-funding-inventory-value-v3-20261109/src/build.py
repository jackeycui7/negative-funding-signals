from common import *
from features import build,qty_features
import inspect,time
SOURCE=ROOT.parent/'neg-funding-aligned-research-20261109'
sys.path.append(str(SOURCE/'src'))
from build_economic_labels import one_coin

def main():
 import runtime_boot as B
 start=time.monotonic();gate,capq=B.setup();d,X,columns,core,eligible,raw24,fresh=build(B,capq);h=d['hours'];ids=d['symbol_id'];take=np.flatnonzero(eligible&((h-hour('2025-10-28'))%168==0)&(h+1008<=B.T));ix={s:i for i,s in enumerate(inspect.signature(B.XE.sim.py_func).parameters)}
 params=dict(B.RR.BASEX);params.update({k:float(v) for k,v in B.RESEARCH['parameters'].items()});params.update(derisk_force=2.,sqrt_y=1.,cutb_sqrt=1.,use_xa=1.,tail_hours=0.)
 Y=np.full((len(take),2),np.nan);why=np.full((len(take),2),'UNPROCESSED',dtype='U40');comp=np.zeros((len(take),2,9));checks=[];done=0
 for n in np.unique(ids[take]):
  coin=one_coin(B.D,int(n));local=np.flatnonzero(ids[take]==n);first=int(h[take[local[0]]])+72;capture={}
  def cap(*a):capture['args']=list(a);return np.zeros((2,8)),0.,0.
  B.HB.E=type('CaptureEngine',(),{'PN':B.XE.PN,'sim':staticmethod(cap)})
  B.HB.run(coin,1e7,ok_t=gate[:,n:n+1],extra=dict(params,trade_end=float(first+720+24)),hw=(first,first+936),same_hour=False,capq=np.array([capq[n]]),dl_stop=True,advmode=1.,imp=30.,xa=np.ascontiguousarray(B.RR.XA['cal'][0][:,:,n:n+1]),s24=np.ascontiguousarray(raw24[:,n:n+1]));B.HB.E=B.XE;args=capture['args'];args[ix['ep_buf']]=np.zeros((1000,11))
  for j in local:
   t=int(h[take[j]])+72;end=t+720;stop=t+936;args[0]=t;args[1]=stop;args[ix['P']][B.XE.PN.index('trade_end')]=float(end+24)
   alive=np.arange(t,end)<B.D.dl_fin[n];data_missing=bool((alive&(~fresh[t:end,n]|~(coin.arr[1][t:end,0]>0)|~(coin.arr[4][t:end,0]>0))).any())
   for k,fraction in enumerate([.5,1.]):
    args[ix['cap_q']]=np.array([capq[n]*fraction])
    for key in ['out_used','out_cum','ep_buf','out_comp','diag','pos_rec','xd','account_rec']:
     if args[ix[key]] is not None:args[ix[key]].fill(0)
    res,blocked,lost=B.XE.sim(*args);cu=args[ix['out_cum']];co=args[ix['out_comp']];pos=args[ix['pos_rec']];ac=args[ix['account_rec']];ep=args[ix['ep_buf']];ne=int(res[:,6].sum());ep=ep[:ne];net=float(cu[-1]);err=float(abs(ac[:,0]-ac[:,4]+ac[:,1]+ac[:,2]-1e7-cu).max());assert err<.002
    heldgap=bool(((pos>1e-9)&~((coin.arr[1][t:stop]>0)&(coin.arr[4][t:stop]>0))).any());remain=float(pos[-1].sum());closed=float((ep[:,3]-ep[:,6]).sum())
    reason='ENTRY_WINDOW_DATA_CENSORED' if data_missing else 'HELD_QUOTE_GAP_CENSORED' if heldgap else 'RESIDUAL_CENSORED' if remain>1e-6 else 'COMPLETED_REFERENCE'
    if reason=='COMPLETED_REFERENCE':Y[j,k]=net;assert abs(closed-net)<.002
    why[j,k]=reason;comp[j,k]=[co[-1,0],co[-1,1],co[-1,2],remain,closed,ne,float((ep[:,2]-ep[:,1]).max()) if ne else 0.,float(ep[:,10].sum()) if ne else 0.,err]
    if len(checks)<3 or (abs(net)>1 and len(checks)<9):
     rr=B.HB.run(coin,1e7,ok_t=gate[:,n:n+1],extra=dict(params,trade_end=float(end+24)),hw=(t,stop),same_hour=False,capq=np.array([capq[n]*fraction]),dl_stop=True,advmode=1.,imp=30.,xa=np.ascontiguousarray(B.RR.XA['cal'][0][:,:,n:n+1]),s24=np.ascontiguousarray(raw24[:,n:n+1]));error=abs(net-float(rr['cum'][-1]));assert error<1e-8;checks.append({'symbol':B.D.fut[n],'decision':stamp(t-72),'quantity_fraction':fraction,'net':net,'difference':error})
    done+=1
   if done%2000==0:print(json.dumps({'probes':done,'total':len(take)*2,'seconds':time.monotonic()-start}),flush=True)
  del coin,args
 rows=np.repeat(take,2);fr=np.tile([.5,1.],len(take));qx,qn=qty_features(core[rows],fr);np.savez_compressed(ROOT/'data/labels.npz',X=np.column_stack([X[rows],qx]),columns=np.r_[columns,qn],source_row=rows,quantity_fraction=fr,hours=h[rows],symbol_id=ids[rows],symbols=d['symbols'],label_end=h[rows]+1007,net_usdt=Y.reshape(-1),reason=why.reshape(-1),components=comp.reshape(-1,9))
 audit={'created_at':now(),'rows':len(rows),'features':X.shape[1]+len(qn),'observed':int(np.isfinite(Y).sum()),'positive':int((Y>1).sum()),'negative':int((Y< -1).sum()),'inactive_abs_le1':int((abs(Y)<=1).sum()),'reasons':pd.Series(why.reshape(-1)).value_counts().to_dict(),'parity_checks':checks,'max_cash_identity_error_usdt':float(comp[:,:,8].max()),'elapsed_seconds':time.monotonic()-start,'horizon':'72h delivery+720h entry+216h constrained unwind; full1008h purged','sha256':sha(ROOT/'data/labels.npz')};save(OUT/'LABEL_AUDIT.json',audit);print(json.dumps(clean(audit)),flush=True)
if __name__=='__main__':main()
