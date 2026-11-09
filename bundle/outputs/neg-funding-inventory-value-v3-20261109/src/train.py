from common import *
from features import qty_features,SOURCE
from model import *
import joblib,warnings,time
from sklearn.metrics import average_precision_score
from scipy.stats import spearmanr

def evaluate(y,p,h):
 good=np.isfinite(y)&np.isfinite(p);f=pd.DataFrame({'y':y,'p':p,'h':h});top=f.sort_values(['h','p'],ascending=[True,False],kind='stable').groupby('h',sort=False).head(20);obs=top[np.isfinite(top.y)];known=f[good]
 return dict(rows=len(y),known=int(good.sum()),selected=len(top),selected_known=len(obs),dates=int(len(np.unique(h))),all_mean_usdt=float(known.y.mean()),top20_mean_usdt=float(obs.y.mean()),top20_positive_fraction=float((obs.y>1).mean()),top20_loss_fraction=float((obs.y< -1).mean()),MAE_usdt=float(abs(y[good]-p[good]).mean()),profitable_AP=float(average_precision_score(y[good]>1,p[good])) if (y[good]>1).any() else None,rank_correlation=float(spearmanr(y[good],p[good]).statistic) if np.std(p[good]) else None)

def main():
 start=time.monotonic();d=loadnp(ROOT/'data/labels.npz');f=loadnp(ROOT/'data/features.npz');X=d['X'];y=d['net_usdt'];h=d['hours'];end=d['label_end'];ids=d['symbol_id'];syms=d['symbols'];cols=d['columns'].tolist();valid=np.isfinite(y);held=np.array([int(hashlib.sha256(str(s).encode()).hexdigest(),16)%5==0 for s in syms])[ids];no_cross=np.array([i for i,n in enumerate(cols) if not(n.startswith(('cross_','bybit_','binance_minus_bybit_')))]);families=['hurdle_full','hurdle_base90','hurdle_no_cross','direct_HGB','ridge','MLP64_32','hurdle_coin_holdout'];bundle={'version':'nfb.inventory-value.v3.20261109','feature_names':cols,'models':{},'research_only':True,'submission_allowed':False,'primary':'hurdle_full','target':'conditional independent-coin completed30d-entry net_usdt; not a probability or additive portfolio prediction','horizon_h':1008};results=[];records=[];pred_daily={m:np.full((len(f['hours']),2),np.nan) for m in families};raw_daily={m:np.full((len(f['hours']),2),np.nan) for m in ['hurdle_full']};fits=0;warn=[]
 for month in range(3,12):
  at=pd.Timestamp(f'2026-{month:02}-01',tz='UTC');cut=hour(at);nextcut=hour(at+pd.offsets.MonthBegin(1));tr=valid&(end<cut);te=(h>=cut)&(h<nextcut);daily=(f['hours']>=cut)&(f['hours']<nextcut)&f['eligible'];meta={'fit_asof_utc':at.isoformat(),'train_rows':int(tr.sum()),'train_dates':int(len(np.unique(h[tr]))),'train_active':int((abs(y[tr])>1).sum()),'training_max_label_end_utc':stamp(end[tr].max()),'test_rows':int(te.sum()),'label_censored_rows':int((te&~valid).sum())};assert end[tr].max()<cut;bundle['models'][str(month)]={'metadata':meta,'estimators':{}}
  for family in families:
   use=tr&~held if family=='hurdle_coin_holdout' else tr
   estimator=Hurdle(np.arange(X.shape[1]) if family in ['hurdle_full','hurdle_coin_holdout'] else np.arange(90) if family=='hurdle_base90' else no_cross) if family.startswith('hurdle') else HistGradientBoostingRegressor(**CFG) if family=='direct_HGB' else linear() if family=='ridge' else neural()
   with warnings.catch_warnings(record=True) as ww:
    warnings.simplefilter('always');estimator.fit(X[use],y[use]);warn.extend([{'month':month,'family':family,'message':str(z.message),'category':z.category.__name__} for z in ww])
   fits+=2 if family.startswith('hurdle') else 1;bundle['models'][str(month)]['estimators'][family]=estimator
   if te.any():
    pp=estimator.predict(X[te]);pick=held[te] if family=='hurdle_coin_holdout' else np.ones(te.sum(),bool)
    for fraction in [.5,1.]:
     mask=(d['quantity_fraction'][te]==fraction)&pick
     if mask.any():results.append(dict(month=month,family=family,quantity_fraction=fraction,**meta,**evaluate(y[te][mask],pp[mask],h[te][mask])))
    records.append(pd.DataFrame({'month':month,'family':family,'hour':h[te],'symbol':syms[ids[te]],'quantity_fraction':d['quantity_fraction'][te],'net_label_usdt':y[te],'prediction_usdt':pp,'coin_holdout':held[te],'observed':valid[te]}))
   if daily.any():
    for k,fraction in enumerate([.5,1.]):
     qx,qn=qty_features(f['core'][daily],fraction);xx=np.column_stack([f['X'][daily],qx]);pred_daily[family][daily,k]=estimator.predict(xx)
     if family=='hurdle_full':raw_daily[family][daily,k]=estimator.predict_activity(xx)
   print(json.dumps({'month':month,'family':family,'fits':fits,'train':int(use.sum()),'seconds':time.monotonic()-start}),flush=True)
  joblib.dump(bundle,ROOT/'data/models.partial.joblib',compress=3);save(OUT/'TRAINING_PROGRESS.json',{'month':month,'component_fits':fits,'elapsed_seconds':time.monotonic()-start,'warnings':warn})
 # Simple controls are always past-only and quantity-aware where named.
 columns=f['columns'].tolist();r8=f['X'][:,0];capa=np.minimum.reduce([f['core'][:,0],f['core'][:,1],f['core'][:,2],f['core'][:,3]])
 for method in ['latest_negative','EMA72','EMA720','capacity_EMA72','raw_cash_EMA720','old_short_net']:pred_daily[method]=np.full((len(f['hours']),2),np.nan)
 old=joblib.load(SOURCE/'data/economic_models.joblib')
 for k,fraction in enumerate([.5,1.]):
  qx,_=qty_features(f['core'],fraction);scores={'latest_negative':-r8,'EMA72':-f['X'][:,columns.index('ema_r8_72h_bp')],'EMA720':-f['X'][:,columns.index('ema_r8_720h_bp')],'capacity_EMA72':qx[:,-2],'raw_cash_EMA720':qx[:,-1]}
  for key,v in scores.items():pred_daily[key][:,k]=np.where(f['eligible'],v,np.nan)
  for fold,lo,hi in [('earlier',hour('2026-03-01'),hour('2026-07-01')),('primary',hour('2026-07-01'),hour('2026-12-01'))]:
   mask=f['eligible']&(f['hours']>=lo)&(f['hours']<hi);pred_daily['old_short_net'][mask,k]=old['models'][fold][old['selected'][fold]].predict(f['X'][mask,:90])
 for method in ['latest_negative','EMA72','EMA720','capacity_EMA72','raw_cash_EMA720','old_short_net']:
  pp=pred_daily[method][d['source_row'],(d['quantity_fraction']==1.).astype(int)];te=(h>=hour('2026-03-01'))&(h<hour('2026-11-01'))
  records.append(pd.DataFrame({'month':pd.to_datetime(ORIGIN+pd.to_timedelta(h[te],unit='h')).month,'family':method,'hour':h[te],'symbol':syms[ids[te]],'quantity_fraction':d['quantity_fraction'][te],'net_label_usdt':y[te],'prediction_usdt':pp[te],'coin_holdout':held[te],'observed':valid[te]}))
  for month in range(3,11):
   for fraction in [.5,1.]:
    mask=te&(h>=hour(f'2026-{month:02}-01'))&(h<hour(pd.Timestamp(f'2026-{month:02}-01')+pd.offsets.MonthBegin(1)))&(d['quantity_fraction']==fraction)
    if mask.any():results.append(dict(month=month,family=method,quantity_fraction=fraction,**evaluate(y[mask],pp[mask],h[mask])))
 joblib.dump(bundle,ROOT/'data/models.joblib',compress=3);np.savez_compressed(ROOT/'data/scores.npz',hours=f['hours'],symbol_id=f['symbol_id'],symbols=f['symbols'],quantity_fractions=[.5,1.],activity_score_uncalibrated=raw_daily['hurdle_full'],**pred_daily);pd.DataFrame(results).to_csv(OUT/'monthly_prediction_metrics.csv',index=False);allp=pd.concat(records);allp.to_csv(OUT/'oos_predictions.csv',index=False);aggregate=[]
 for (family,fraction),g in allp.groupby(['family','quantity_fraction']):
  if family=='hurdle_coin_holdout':g=g[g.coin_holdout]
  aggregate.append(dict(family=family,quantity_fraction=fraction,**evaluate(g.net_label_usdt.to_numpy(),g.prediction_usdt.to_numpy(),g.hour.to_numpy())))
 pd.DataFrame(aggregate).to_csv(OUT/'prediction_summary.csv',index=False);save(OUT/'TRAINING_AUDIT.json',{'created_at':now(),'component_fits':fits,'models_per_month':len(families),'month_fits':9,'warnings':warn,'models_sha256':sha(ROOT/'data/models.joblib'),'elapsed_seconds':time.monotonic()-start,'every_train_label_end_before_fit':True,'no_test_based_family_selection':True,'hurdle_probability_calibrated':False});print('TRAINING_COMPLETED',flush=True)
if __name__=='__main__':main()
