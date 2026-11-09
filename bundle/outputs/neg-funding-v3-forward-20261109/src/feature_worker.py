"""Reuse frozen pure feature/scoring implementations; never fit or mutate models."""
import common as live
import sys,sqlite3,importlib.util,types,warnings,time
sys.modules.pop('common');sys.path.insert(0,str(live.V3/'src'))
import common as frozen
from common import np,pd
import features as vf
import signal_cli
import joblib
warnings.filterwarnings('ignore',category=RuntimeWarning)

def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
cf=module('pure_causal',live.PHASE2/'signal_strengthening_20261107/causal_features.py')
ec=module('pure_cash',live.PHASE2/'exit_aware_research_20261107/exit_core.py')
em=module('pure_ema',live.PHASE2/'model_comparison_v2/comparison_core.py')
sigma=module('pure_sigma',live.OUTPUTS/'neg-funding-strategy-online-20261108/frozen_reference/research/causal_inputs.py')

def loadhistory(T,parity=False):
 seed=live.OUTPUTS/('neg-funding-strategy-phase1-20261106' if parity else 'neg-funding-empirical-calibration-20261109')/'data/ds/dataset.npz'
 with np.load(seed) as z:
  arr={k:np.pad(z[k][:T],((0,max(0,T-len(z[k]))),(0,0)),constant_values=0 if k in ['ev','ivh'] else np.nan) for k in ['sc','fc','sq','fq','r8','oih','ev','ivh']}
  seedlen=min(T,len(z['sc']))
 with np.load(live.PHASE2/'model_v1/extra_features.npz') as z:
  premium=np.pad(z['premium'][:T],((0,max(0,T-len(z['premium']))),(0,0)),constant_values=np.nan)
  positioning=np.pad(z['positioning'][:T],((0,max(0,T-len(z['positioning']))),(0,0),(0,0)),constant_values=np.nan)
 meta=pd.read_csv(live.OUTPUTS/'neg-funding-empirical-calibration-20261109/data/ds/dataset_meta.csv');syms=meta.fut.tolist()
 return arr,premium,positioning,meta,syms,seedlen

def observed(arr,premium,positioning,meta,syms,seedlen,asof,received_before):
 c=sqlite3.connect(live.ROOT/'data/market.sqlite');lookup={s:n for n,s in enumerate(syms)};T=len(arr['sc']);proof={};last={};coverage={};funds={};cross={};issues=[]
 # Stream one final known5m observation per hour and the latest visible source revision.
 # This preserves the frozen last-record semantics without retaining months of5m rows in RAM.
 query="""WITH ranked AS (SELECT kind,symbol,event_ms,received_ms,payload,request_id,
 ROW_NUMBER() OVER(PARTITION BY kind,symbol,CASE WHEN kind IN ('oi','global_accounts','top_accounts','top_positions','taker_flow') THEN (event_ms-?)/3600000 ELSE event_ms END
 ORDER BY event_ms DESC,received_ms DESC,request_id DESC) AS rn
 FROM records WHERE received_ms<=? AND event_ms<? AND kind NOT IN ('probe','futures_metadata','funding_metadata'))
 SELECT kind,symbol,event_ms,received_ms,payload,request_id FROM ranked WHERE rn=1 ORDER BY event_ms,received_ms,request_id"""
 rows=c.execute(query,(live.ORIGIN,received_before,asof))
 for kind,s,stamp,received,payload,rid in rows:
  if s not in lookup:continue
  n=lookup[s];x=frozen.json.loads(payload);h=(stamp-live.ORIGIN)//live.H
  if kind in ['spot','perp','premium']:
   if not (0<=h<T) or int(x[6])>=asof:continue
   if kind=='premium':premium[h,n]=float(x[4])
   else:
    price='sc' if kind=='spot' else 'fc';vol='sq' if kind=='spot' else 'fq';arr[price][h,n]=float(x[4])/(meta.mult.iloc[n] if kind=='perp' else 1);arr[vol][h,n]=float(x[7])
  elif kind in ['oi','global_accounts','top_accounts','top_positions','taker_flow']:
   if stamp>=asof:continue
   # Archived OI was prelagged1h; positioning remained in its timestamp hour.
   if kind=='oi':h+=1
   if not 0<=h<(asof-live.ORIGIN)//live.H:continue
   if kind=='oi':arr['oih'][h,n]=float(x['sumOpenInterestValue'])
   else:positioning[h,n,['global_accounts','top_accounts','top_positions','taker_flow'].index(kind)]=float(x['buySellRatio'] if kind=='taker_flow' else x['longShortRatio'])
  elif kind=='funding':
   if stamp>=asof:continue
   funds.setdefault(n,{})[stamp]=x
  elif kind=='bybit_funding':
   if stamp>=asof:continue
   cross.setdefault(s,{})[stamp]=x
  else:continue
  key=(kind,s);coverage.setdefault(key,set()).add(h);last[key]=max(last.get(key,0),stamp);proof[str(rid)]=received
 for n,events in funds.items():
  prioridx=np.flatnonzero(arr['ivh'][:seedlen,n]>0);lasttime=live.ORIGIN+int(prioridx[-1])*live.H if len(prioridx) else None;interval=float(arr['ivh'][prioridx[-1],n]) if len(prioridx) else np.nan
  for stamp,x in sorted(events.items()):
   h=int(np.ceil((stamp-live.ORIGIN-60000)/live.H))
   if not 0<=h<T:continue
   if h<seedlen:continue # Frozen cached history is immutable and provenance-bound.
   delta=(stamp-lasttime)/live.H if lasttime is not None else np.nan
   if not (0<delta<=8.05):
    delta=interval;issues.append({'symbol':syms[n],'event_ms':stamp,'flag':'INTERVAL_FALLBACK_MATCHES_FROZEN_SOURCE'})
   delta=round(delta,6);arr['ev'][h,n]=float(x['fundingRate']);arr['ivh'][h,n]=delta if np.isfinite(delta) else 0;arr['r8'][h,n]=float(x['fundingRate'])*8/delta if np.isfinite(delta) and delta>0 else np.nan;lasttime=stamp;interval=delta
 # Never ffill market bars,OI,positions or missing payments. Only latest-settled funding is a state variable.
 arr['r8']=pd.DataFrame(arr['r8']).ffill().to_numpy()
 reqids=[int(k) for k in proof];hashes={}
 for offset in range(0,len(reqids),900):
  part=reqids[offset:offset+900]
  hashes.update({str(live.ROOT/'data/raw'/(r[0]+'.json')):r[0] for r in c.execute('SELECT DISTINCT hash FROM requests WHERE id IN ('+','.join('?' for _ in part)+')',part)})
 c.close();return {'received_at_utc':live.iso(max(proof.values())) if proof else None,'source_file_hashes':hashes,'kind_symbol_latest':{k+'|'+s:live.iso(t) for (k,s),t in last.items()},'interval_issues':issues},cross

def build(asof,received_before,folder,parity=False):
 decision=(asof-live.ORIGIN)//live.H;T=decision+1;arr,premium,positioning,meta,syms,seedlen=loadhistory(T,parity);ids=np.arange(len(syms));hours=np.full(len(syms),decision,dtype=int);proof={};cross={}
 if not parity:proof,cross=observed(arr,premium,positioning,meta,syms,seedlen,asof,received_before)
 btc=syms.index('BTCUSDT');base,cols,_=cf.build_features(arr,premium,positioning,hours,btc,ids);fresh=em.fresh_funding(arr['r8'],arr['ivh'],arr['fc']);ema,names=em.ema_features(arr['r8'],fresh,hours,ids);state=ec.cash_state(arr['ev'],arr['ivh'],fresh);raw,rnames=ec.raw_features(state,fresh,hours,ids);reg,gnames=ec.regime_features(arr['r8'],fresh,hours,ids)
 X=np.column_stack([base,ema,raw,reg]);columns=cols+names+rnames+gnames;d={'X':X,'columns':np.array(columns),'hours':hours,'symbol_id':ids,'symbols':np.array(syms)}
 if parity:
  # v3additional26andcapacity were built on the later empirical market seed.
  with np.load(live.OUTPUTS/'neg-funding-empirical-calibration-20261109/data/ds/dataset.npz') as z:arr={k:z[k][:T] for k in arr}
 else:
  shadow=folder/'cross/signal_strengthening_20261107';shadow.mkdir(parents=True,exist_ok=True);original=live.PHASE2/'signal_strengthening_20261107';mapping=frozen.json.loads((original/'CROSS_VENUE_MAPPING.json').read_text());(shadow/'CROSS_VENUE_MAPPING.json').write_text(frozen.json.dumps(mapping))
  for rec in mapping['mappings']:
   source=original/'raw/bybit_funding'/rec['bybit']/'series.json';dest=shadow/'raw/bybit_funding'/rec['bybit'];dest.mkdir(parents=True,exist_ok=True);series={}
   if source.exists():
    audit=frozen.json.loads((source.parent/'audit.json').read_text());assert live.sha(source)==audit['series_sha256'];series={int(v['fundingRateTimestamp']):v for v in frozen.json.loads(source.read_text()) if int(v['fundingRateTimestamp'])<asof}
   series.update(cross.get(rec['binance'],{}));path=dest/'series.json';path.write_text(frozen.json.dumps([v for _,v in sorted(series.items())]));(dest/'audit.json').write_text(frozen.json.dumps({'series_sha256':live.sha(path)}))
  vf.PHASE2=folder/'cross'
 cap=pd.read_csv(live.OUTPUTS.parent/'neg-funding-strategy-v1/private/inventory_caps.csv').set_index('fut_symbol');capq=np.array([float(cap.loc[s,'cap_qty_token']) if s in cap.index else 0 for s in syms]);capusd=np.array([min(float(cap.loc[s,'cap_usdt']),1e7) if s in cap.index else 0 for s in syms])
 D=types.SimpleNamespace(arr=[None,arr['sc'],arr['sq'],None,arr['fc'],arr['fq'],arr['ev'],arr['r8']],_iv=arr['ivh'],oih=arr['oih'],hs_s=meta.hs_s.to_numpy(),hs_f=meta.hs_f.to_numpy(),_sg=sigma.causal_sigma(arr['sc']),fut=syms,dl_exit=meta.dl_exit.to_numpy())
 B=types.SimpleNamespace(D=D,T=T,N=len(syms),HB=types.SimpleNamespace(cap_vec=lambda *_:capusd));vf.loadnp=lambda _:d
 _,xx,nn,core,eligible,raw24,ff=vf.build(B,capq,persist=False);xx[~np.isfinite(xx)]=np.nan
 vectors=[]
 for fraction in [1.,.5]:
  q,qnames=vf.qty_features(core,fraction);vectors.append(np.column_stack([xx,q]));names=list(nn)+qnames
 np.savez_compressed(folder/'features.npz',X=vectors[0],X_half=vectors[1],columns=np.array(names),symbols=np.array(syms),eligible=eligible,raw24_known=state['known'][decision-1],fresh=fresh[decision-1],raw24=raw24[decision-1],asof_ms=asof)
 live.atomic(folder/'evidence.json',dict(proof,feature_file_sha256=live.sha(folder/'features.npz'),source_cutoff_exclusive_utc=live.iso(asof),snapshot_received_cutoff_utc=live.iso(received_before),parity_test=parity))
 return vectors,names,syms,eligible,state['known'][decision-1]

def parity(folder):
 z=np.load(live.V3/'data/features.npz');hour=int(z['hours'].max());asof=live.ORIGIN+hour*live.H;v,names,syms,eligible,known=build(asof,live.ms(),folder,True);selected=z['hours']==hour;expected=z['X'][selected];got=v[0][:,:116][z['symbol_id'][selected]]
 q,qn=vf.qty_features(z['core'][selected],1.);expected=np.column_stack([expected,q]);got=v[0][z['symbol_id'][selected]]
 mismatch=~np.isclose(expected,got,rtol=1e-6,atol=2e-6,equal_nan=True);details=[{'feature':names[j],'mismatches':int(mismatch[:,j].sum()),'max_abs_difference':float(np.nanmax(np.abs(expected[:,j]-got[:,j])))} for j in range(125) if mismatch[:,j].any()]
 out={'landmark_utc':live.iso(asof),'rows':len(expected),'features':125,'cells':int(expected.size),'mismatch_cells':int(mismatch.sum()),'details':details,'passed':not mismatch.any(),'frozen_files_written':False};live.atomic(folder/'parity.json',out);return out

def scoring(folder,asof):
 z=np.load(folder/'features.npz');economic=joblib.load(live.V3/'data/models.joblib');events=joblib.load(live.V3/'data/event_models.joblib');out=[];names=z['columns'].tolist();assert names==economic['feature_names']
 for i,s in enumerate(z['symbols']):
  if not z['eligible'][i]:continue
  for fraction,key in [(1.,'X'),(.5,'X_half')]:
   request={'schema_version':'nfb.signal-input.v3','request_id':f'v3-{asof}-{s}-q{fraction:g}','symbol':str(s),'asof_utc':live.iso(asof),'feature_hour_start_utc':live.iso(asof-live.H),'conditional_arrival_fraction':fraction,'inventory_status':'NOT_REQUESTED','raw24_known':bool(z['raw24_known'][i]),'information_mode':'historical_hourly_proxy' if (folder/'parity.json').exists() else 'observed_asof_snapshot','features':{k:float(x) if np.isfinite(x) else None for k,x in zip(names,z[key][i])}}
   prediction=signal_cli.score(request,economic,events);baselines={}
   if fraction==1.:
    x=np.array([[np.nan if request['features'][k] is None else request['features'][k] for k in names[:116]]])
    for task,key in [('new_negative_72h','p_new_negative_within72h'),('survival_168h','p_no_raw24_exit_next168h'),('arrival_entry_7d','p_qualified_entry_after72h_within7d')]:
     if prediction['forecasts'][key] is None:continue
     heads=events['heads'][task][prediction['fit_month']]['estimators'];baselines[key]={method:float(heads[method].predict(x)[0]) for method in ['EMA72_calibrated','latest_or_age_calibrated']}
   out.append({'request':request,'prediction':prediction,'frozen_baseline_probabilities':baselines,'computed_at_utc':live.iso(live.ms())})
 live.atomic(folder/'scores.json',out);return {'outputs':len(out),'scoring_only':True,'model_fitted':False}

if __name__=='__main__':
 import argparse
 ap=argparse.ArgumentParser();ap.add_argument('--parity',action='store_true');ap.add_argument('--asof-ms',type=int);ap.add_argument('--folder',required=True);ap.add_argument('--score',action='store_true');args=ap.parse_args();folder=live.Path(args.folder).resolve();folder.mkdir(parents=True,exist_ok=True)
 if args.parity:result=parity(folder)
 elif args.score:result=scoring(folder,args.asof_ms)
 else:
  v,nn,syms,eligible,known=build(args.asof_ms,live.ms(),folder);result={'rows':len(syms),'features':len(nn),'eligible':int(eligible.sum()),'raw24_known':int(known.sum()),'median_missing_fraction':float(np.isnan(v[0]).mean(axis=1).mean()),'predictions_made':0}
 print(frozen.json.dumps(result,ensure_ascii=False))
