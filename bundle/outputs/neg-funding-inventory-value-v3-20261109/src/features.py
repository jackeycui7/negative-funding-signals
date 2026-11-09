from common import *
SOURCE=ROOT.parent/'neg-funding-aligned-research-20261109'

def qty_features(core,fraction):
 q=np.asarray(fraction);notional=core[:,0]*q;capacity=np.minimum.reduce([notional,core[:,1],core[:,2],core[:,3]])
 out=np.column_stack([np.log1p(np.maximum(notional,0)),np.log1p(np.maximum(capacity,0)),np.divide(capacity,core[:,4]+1),np.divide(capacity,core[:,5]+1),np.divide(capacity,core[:,6]+1),np.divide(capacity,core[:,7]+1),np.full(len(core),q) if q.ndim==0 else q,capacity*core[:,8]/1e4,capacity*core[:,9]/1e4])
 names=['log_received_notional','log_effective_capacity','capacity_OI_ratio','capacity_paired_ADV_ratio','entry_hours_prior_volume_proxy','exit_hours_prior_volume_proxy','conditional_quantity_fraction','capacity_EMA72_score_usdt','capacity_raw_cash_EMA720_score_usdt']
 return out.astype(np.float32),names

def rolling(x,h,op='mean',minimum=None):return getattr(pd.DataFrame(x).rolling(h,min_periods=h if minimum is None else minimum),op)().to_numpy()

def build(B,capq,persist=True):
 d=loadnp(SOURCE/'data/daily_samples.npz');h=d['hours'];ids=d['symbol_id'];q=h-1;T=B.T;N=B.N
 ev=B.D.arr[6];rate=B.D.arr[7];sc=B.D.arr[1];fc=B.D.arr[4];iv=B.D._iv;clock=np.arange(T)[:,None];last=np.maximum.accumulate(np.where(iv>0,clock,-100000),axis=0);fresh=(clock-last<=8)&np.isfinite(rate)&(fc>0);payments=np.where(iv>0,np.nan_to_num(ev),0.);units=np.rint(payments/1e-8).astype(np.int64);cs=np.vstack([np.zeros((1,N),np.int64),np.cumsum(units,axis=0)]);raw24=np.zeros((T,N));raw24[23:]=(cs[24:]-cs[:-24])*1e-8
 cashknown=rolling(fresh.astype(float),24,'sum')==24
 X=[];names=[]
 def add(n,x):X.append(x[q,ids]);names.append(n)
 # Every completed nonpositive raw24 cycle is counted at its first positive balance.
 age=np.zeros(N);longest=np.zeros(N);cnt=np.zeros(N);sums=np.zeros(N);hits=np.zeros(N);completed_duration=np.zeros((T,N));completed=np.zeros((T,N));live_age=np.zeros((T,N));longhit=np.zeros((T,N));lastlen=np.full((T,N),np.nan)
 previous=np.zeros(N)
 for t in range(T):
  known=cashknown[t];fail=known&(raw24[t]>0)&(age>0);completed[t,fail]=1;completed_duration[t,fail]=age[fail];longhit[t,fail]=(age[fail]>=168);previous[fail]=age[fail];lastlen[t]=previous;age=np.where(known&(raw24[t]<=0),age+1,0);live_age[t]=age
 add('cash_nonpositive_age_uncapped_h',live_age)
 add('last_completed_cash_cycle_h',lastlen)
 for w in [720,2160]:
  count=rolling(completed,w,'sum',minimum=w//2);dur=rolling(completed_duration,w,'sum',minimum=w//2);long=rolling(longhit,w,'sum',minimum=w//2)
  add(f'completed_cash_cycles_{w}h',count);add(f'completed_cycle_mean_h_{w}h',np.divide(dur,count,out=np.full_like(count,np.nan),where=count>0));add(f'completed_long_cycle_share_{w}h',np.divide(long,count,out=np.full_like(count,np.nan),where=count>0))
  add(f'cash_nonpositive_fraction_{w}h',rolling(np.where(fresh,(raw24<=0).astype(float),np.nan),w,minimum=w//2))
 for w in [72,720]:
  ema=pd.DataFrame(payments).ewm(span=w,adjust=False,min_periods=w//2).mean().to_numpy();add(f'raw_payment_EMA_{w}h_bp_per_h',ema*1e4)
 add('funding_prints_30d',rolling((iv>0).astype(float),720,'sum',minimum=360))
 add('ema_r8_720h_bp',pd.DataFrame(np.where(fresh,rate*1e4,np.nan)).ewm(halflife=720,adjust=False,min_periods=720).mean().to_numpy())
 # Quote depth remains an estimator; no historical book or actual own impact is fabricated.
 vspot=rolling(np.maximum(np.nan_to_num(B.D.arr[2]),0),24,'sum');vperp=rolling(np.maximum(np.nan_to_num(B.D.arr[5]),0),24,'sum');vpair=np.minimum(vspot,vperp);oi=B.D.oih
 add('frozen_roundtrip_fee_spread_bp',np.broadcast_to((2*(.0006+.00032)+2*(B.D.hs_s+B.D.hs_f))[None,:],(T,N))*1e4)
 add('causal_sigma_bp',B.D._sg*1e4)
 # Official cached Bybit settlements; only settled events, no inferred future schedule.
 cross=PHASE2/'signal_strengthening_20261107';mapping=json.loads((cross/'CROSS_VENUE_MAPPING.json').read_text())['mappings'];be=np.full((T,N),np.nan);bi=np.full((T,N),np.nan);lookup={s:n for n,s in enumerate(B.D.fut)};count=0;files=[]
 for rec in mapping:
  n=lookup.get(rec['binance']);p=cross/'raw/bybit_funding'/rec['bybit']/'series.json'
  if n is None or not p.exists():continue
  au=json.loads((p.parent/'audit.json').read_text());assert sha(p)==au['series_sha256'];files.append({'file':str(p),'sha256':sha(p)})
  prior=None
  for v in json.loads(p.read_text()):
   ms=int(v['fundingRateTimestamp']);delta=(ms-prior)/3600000 if prior is not None else np.nan;t=int(np.ceil((ms-ORIGIN.value//10**6-60000)/3600000))
   if 0<=t<T:
    assert not np.isfinite(be[t,n]);be[t,n]=float(v['fundingRate']);bi[t,n]=round(delta) if any(abs(delta-z)<1e-5 for z in [1,2,4,8]) else np.nan;count+=1
   prior=ms
 event=np.isfinite(be);lastb=np.maximum.accumulate(np.where(event,clock,-100000),axis=0);ageb=clock-lastb;known=(ageb<=8)&(lastb>=0);rawb=pd.DataFrame(be).ffill().to_numpy();intb=bi[np.maximum(lastb,0),np.arange(N)[None,:]]
 add('cross_funding_available',known.astype(float));add('bybit_observation_age_h',np.where(known,ageb,np.nan));add('bybit_last_interval_inferred_h',np.where(known,intb,np.nan));add('bybit_r8_bp_inferred',np.where(known,rawb*8/intb*1e4,np.nan))
 for w in [24,72,168]:
  cov=rolling(known.astype(float),w)>=.95;bc=rolling(np.nan_to_num(be),w,'sum');nc=rolling(payments,w,'sum');add(f'bybit_cash_sum_{w}h_bp',np.where(cov,bc*1e4,np.nan));add(f'binance_minus_bybit_cash_sum_{w}h_bp',np.where(cov& (rolling(fresh.astype(float),w)>=.95),(nc-bc)*1e4,np.nan))
 columns=np.r_[d['columns'],names];XX=np.column_stack([d['X'],*X]).astype(np.float32);XX[~np.isfinite(XX)]=np.nan
 capstatic=B.HB.cap_vec(B.D,1e7);half=B.D.hs_s+B.D.hs_f;priorvol=np.minimum(B.D.arr[2][q,ids],B.D.arr[5][q,ids]);adv=vpair[q,ids];ois=oi[q,ids]
 # Core holds scenario-independent physical values; qty_features applies conditional delivery fractions.
 core=np.column_stack([capq[ids]*sc[q,ids],np.minimum(capstatic[ids],1e6),.025*ois,.05*adv,ois,adv,.03*np.maximum(priorvol,0),.03*np.maximum(priorvol,0),-d['X'][:,d['columns'].tolist().index('ema_r8_72h_bp')],-XX[:,columns.tolist().index('raw_payment_EMA_720h_bp_per_h')]*24])
 base=np.isfinite(d['X'][:,0])&np.isfinite(d['X'][:,d['columns'].tolist().index('basis_bp')])&(capq[ids]>0)&(h<B.D.dl_exit[ids]);core[~np.isfinite(core)]=np.nan
 if persist:
  np.savez_compressed(ROOT/'data/features.npz',X=XX,columns=columns,core=core,hours=h,symbol_id=ids,symbols=d['symbols'],eligible=base)
  save(OUT/'FEATURE_AUDIT.json',{'created_at':now(),'base_features':90,'additional_features':len(names),'quantity_features':qty_features(core[:1],1.)[1],'cutoff':'decision-1','cross_settlements':count,'cross_source_files':len(files),'cross_source_hashes':files,'feature_file_sha256':sha(ROOT/'data/features.npz'),'daily_rows':len(h),'eligible_rows':int(base.sum()),'cross_available_eligible_fraction':float(XX[base,columns.tolist().index('cross_funding_available')].mean()),'bybit_timing':'Source fundingTime rounded to containing historical hourly observation; available next completed-hour decision. Actual received_at unavailable, not a tick-level availability audit. Native mapping snapshot; no chain holder/control labels.'})
 return d,XX,columns,core,base,raw24,fresh
