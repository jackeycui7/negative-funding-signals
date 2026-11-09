from common import *
from model import CFG
from features import SOURCE
import joblib,warnings,time
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import average_precision_score,brier_score_loss,precision_score,recall_score

def linear():return make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),StandardScaler(),LogisticRegression(C=1.,max_iter=2000))
from model import EventHead

def event_labels(f):
 with np.load(MARKET/'ds/dataset.npz') as z:rate=z['r8'];iv=z['ivh'];ev=z['ev'];fc=z['fc']
 T,N=rate.shape;clock=np.arange(T)[:,None];last=np.maximum.accumulate(np.where(iv>0,clock,-100000),axis=0);fresh=(clock-last<=8)&np.isfinite(rate)&(fc>0)&((iv<=0)|np.isfinite(ev));h=f['hours'];ids=f['symbol_id'];latest=f['X'][:,0];eligible=f['eligible']&(latest>=0);y=np.full(len(h),np.nan);reason=np.full(len(h),'CURRENT_INELIGIBLE',dtype='U32');registry=json.loads((FROZEN/'research/lifecycle_events.json').read_text());death=np.full(N,T+1000);lookup={s:n for n,s in enumerate(f['symbols'])}
 for r in registry['events']:
  for s in r['symbols']:
   if s in lookup:death[lookup[s]]=hour(r['futures_delivery_utc'])
 for j in np.flatnonzero(eligible):
  t,n=int(h[j]),int(ids[j]);stop=min(t+72,T);missing=np.flatnonzero(~fresh[t:stop,n]);censor=t+int(missing[0]) if len(missing) else stop;neg=np.flatnonzero((iv[t:censor,n]>0)&(ev[t:censor,n]<0));success=t+int(neg[0]) if len(neg) else T+1000;fail=death[n]
  if success<min(t+72,fail) and success<censor:y[j]=1;reason[j]='NEGATIVE_PRINT'
  elif fail<t+72 and fail<=censor:y[j]=0;reason[j]='DELIVERY_BEFORE_TURN'
  elif censor>=t+72:y[j]=0;reason[j]='NO_TURN'
  else:reason[j]='DATA_CENSORED' if stop<T else 'END_CENSORED'
 old=loadnp(SOURCE/'data/daily_samples.npz');assert np.array_equal(h,old['hours']);np.savez_compressed(ROOT/'data/event_labels.npz',hours=h,symbol_id=ids,y_new_negative_72h=y,end_new_negative_72h=h+71,new_negative_reason=reason,y_survival_168h=old['y_survival'],end_survival_168h=old['end_survival'],survival_reason=old['survival_reason'])
 return y,old['y_survival'],reason

def metrics(g):
 o=g[g.observed];rank=g.sort_values(['hour','prediction'],ascending=[True,False],kind='stable').groupby('hour',sort=False).head(10);v=rank[rank.observed];last={};warn=[]
 for _,row in g.sort_values(['hour','prediction'],ascending=[True,False],kind='stable').iterrows():
  t=int(row.hour);s=row.symbol
  if t-last.get(s,-100000)<72:continue
  if sum(x['hour']==t for x in warn[-10:])>=10:continue
  last[s]=t;warn.append({'hour':t,'symbol':s,'y':row.y,'observed':row.observed})
 w=pd.DataFrame(warn);wo=w[w.observed] if len(w) else w
 bins=[]
 for low,high in zip(np.arange(0,1,.2),np.arange(.2,1.2,.2)):
  b=o[(o.prediction>=low)&(o.prediction<high if high<1 else o.prediction<=1)];bins.append({'lo':float(low),'hi':float(high),'n':len(b),'mean_prediction':float(b.prediction.mean()),'observed_fraction':float(b.y.mean())})
 if not len(o):return dict(rows=len(g),observed=0,AP=None,Brier=None,top10_rows=len(rank),top10_observed=0,top10_precision=None,cooldown_alerts=len(w),cooldown_observed=0,cooldown_hits=0,cooldown_precision=None,calibration_bins=bins)
 return dict(rows=len(g),observed=len(o),positives=int(o.y.sum()),base_rate=float(o.y.mean()),AP=float(average_precision_score(o.y,o.prediction)),Brier=float(brier_score_loss(o.y,o.prediction)),threshold_05_alerts=int((o.prediction>=.5).sum()),threshold_05_precision=float(precision_score(o.y,o.prediction>=.5,zero_division=0)),threshold_05_recall=float(recall_score(o.y,o.prediction>=.5,zero_division=0)),top10_rows=len(rank),top10_observed=len(v),top10_precision=float(v.y.mean()),cooldown_alerts=len(w),cooldown_observed=len(wo),cooldown_hits=int(wo.y.sum()),cooldown_precision=float(wo.y.mean()),calibration_bins=bins)

def main():
 start=time.monotonic();f=loadnp(ROOT/'data/features.npz');yturn,ysurv,reason=event_labels(f);X=f['X'];cols=f['columns'].tolist();h=f['hours'];ids=f['symbol_id'];syms=f['symbols'];bundle={'version':'nfb.signal-event.v3.20261109','feature_names':cols,'heads':{},'research_only':True,'submission_allowed':False};records=[];fits=0;warn=[];old_labels=loadnp(SOURCE/'data/daily_samples.npz');rescore='--rescore' in sys.argv;extend='--add-arrival' in sys.argv
 if rescore or extend:
  bundle=joblib.load(ROOT/'data/event_models.joblib');prior_audit=json.loads((OUT/'EVENT_RESULTS.json').read_text());fits=prior_audit['component_fits'];warn=prior_audit['warnings']
 methods=['fixed_HGB_full','fixed_HGB_base90','logistic_C1_full','EMA72_calibrated','latest_or_age_calibrated'];fitmeta=[]
 tasks=[('new_negative_72h',yturn,71),('survival_168h',ysurv,167)]
 if extend:tasks=[('arrival_entry_7d',old_labels['y_arrival'],239)]
 for task,y,offset in tasks:
  e=h+offset;valid=np.isfinite(y)
  if not rescore:bundle['heads'][task]={}
  for month in range(3,12):
   at=pd.Timestamp(f'2026-{month:02}-01',tz='UTC');cut=hour(at);calstart=cut-60*24;nextcut=hour(at+pd.offsets.MonthBegin(1));tr=valid&(e<calstart);ca=valid&(h>=calstart)&(e<cut);current_eligible=(f['eligible']&(X[:,0]>=0)) if task=='new_negative_72h' else f['eligible'] if task=='arrival_entry_7d' else (f['eligible']&old_labels['current_eligible']);te=current_eligible&(h>=cut)&(h<nextcut);audit={'task':task,'month':month,'fit_asof':at.isoformat(),'train_rows':int(tr.sum()),'calibration_rows':int(ca.sum()),'max_train_label_end':stamp(e[tr].max()),'max_cal_label_end':stamp(e[ca].max()),'test_rows':int(te.sum())};assert e[tr].max()<calstart and e[ca].max()<cut;
   if not rescore:bundle['heads'][task][str(month)]={'metadata':audit,'estimators':{}}
   fitmeta.append(audit)
   for method in methods:
    if rescore:head=bundle['heads'][task][str(month)]['estimators'][method]
    else:
     index=np.arange(90) if method=='fixed_HGB_base90' else np.arange(X.shape[1]);head=EventHead(method,index)
     if method.startswith('EMA72'):
      head.indices=[cols.index('ema_r8_72h_bp')];head.sign=-1
     elif method.startswith('latest_or_age'):
      head.indices=[cols.index('settled_r8_bp') if task in ['new_negative_72h','arrival_entry_7d'] else cols.index('known_negative_age_hours')];head.sign=-1 if task in ['new_negative_72h','arrival_entry_7d'] else 1
     else:
      head.estimator=linear() if method.startswith('logistic') else HistGradientBoostingClassifier(**CFG)
      with warnings.catch_warnings(record=True) as ww:
       warnings.simplefilter('always');head.estimator.fit(X[tr][:,index],y[tr]);warn.extend([{'task':task,'month':month,'method':method,'warning':str(z.message)} for z in ww])
      fits+=1
     cal_score=head.score(X[ca]);known=np.isfinite(cal_score);head.calibrator=make_pipeline(SimpleImputer(strategy='median'),StandardScaler(),LogisticRegression(C=1.,max_iter=2000)).fit(cal_score[known,None],y[ca][known]);fits+=1
    bundle['heads'][task][str(month)]['estimators'][method]=head
    if te.any():
     pp=head.predict(X[te]);records.append(pd.DataFrame({'task':task,'month':month,'method':method,'hour':h[te],'symbol':syms[ids[te]],'y':y[te],'prediction':pp,'observed':np.isfinite(y[te])}))
   print(json.dumps({'task':task,'month':month,'fits':fits,'seconds':time.monotonic()-start}),flush=True)
  joblib.dump(bundle,ROOT/'data/event_models.partial.joblib',compress=3)
 allp=pd.concat(([pd.read_csv(OUT/'event_predictions.csv')] if extend else [])+records);allp.to_csv(OUT/'event_predictions.csv',index=False);summary=[];monthly=[]
 for (task,method),g in allp.groupby(['task','method']):
  summary.append({'task':task,'method':method,'period':'2026-03 through2026-10',**metrics(g[g.month<=10])})
  for month,gg in g.groupby('month'):monthly.append({'task':task,'method':method,'month':int(month),**metrics(gg)})
 joblib.dump(bundle,ROOT/'data/event_models.joblib',compress=3);save(OUT/'EVENT_RESULTS.json',{'created_at':now(),'summary':summary,'monthly':monthly,'fit_metadata':(prior_audit['fit_metadata'] if extend else [])+fitmeta,'component_fits':fits,'warnings':warn,'elapsed_seconds':time.monotonic()-start,'turn_label_reasons':pd.Series(reason).value_counts().to_dict(),'retrospective':True,'calibration_no_test_labels':True,'select_before_observing_labels':True,'rescore_without_refit':rescore,'unobserved_predictions_retained':int((~allp.observed).sum()),'selection_censor_fix':'Current-eligible rows retained even when future label unknown; historical event heads rescored without retraining to fix preselection censor removal. Arrival task added separately under registered protocol.'});print('EVENT_HEADS_COMPLETED',flush=True)
if __name__=='__main__':main()
