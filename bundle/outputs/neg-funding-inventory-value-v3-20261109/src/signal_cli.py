"""Offline research scoring only. No exchange, account, order or network API."""
from common import *
from model import EventHead,Hurdle
import joblib

class InputError(ValueError):pass

def parse_time(value):
 try:
  p=pd.Timestamp(value)
  if p.tzinfo is None:raise ValueError()
  return p.tz_convert('UTC')
 except Exception:raise InputError('Timestamp must include a timezone')

def score(request, economic=None,events=None,reference_now=None):
 if request.get('schema_version')!='nfb.signal-input.v3':raise InputError('Unsupported schema_version')
 for key in ['request_id','symbol','asof_utc','feature_hour_start_utc','conditional_arrival_fraction','inventory_status','raw24_known','information_mode','features']:
  if key not in request:raise InputError('Missing field: '+key)
 allowed={'schema_version','request_id','symbol','asof_utc','feature_hour_start_utc','conditional_arrival_fraction','inventory_status','raw24_known','information_mode','features'}
 if set(request)!=allowed:raise InputError('Unexpected top-level input fields')
 asof=parse_time(request['asof_utc']);featuretime=parse_time(request['feature_hour_start_utc'])
 if asof.hour or asof.minute or asof.second or asof.microsecond:raise InputError('V3 research heads require daily00UTC decision grid')
 if featuretime!=asof-pd.Timedelta(hours=1):raise InputError('Feature cutoff must equal preceding completed-hour start')
 fraction=request['conditional_arrival_fraction']
 if isinstance(fraction,bool) or not isinstance(fraction,(int,float)) or not .5<=fraction<=1:raise InputError('Conditional fraction must be within trained0.5..1.0 support')
 if request['inventory_status'] not in ['NOT_REQUESTED','PENDING_72H','AVAILABLE']:raise InputError('Unsupported inventory_status')
 if not isinstance(request['raw24_known'],bool):raise InputError('raw24_known must be boolean')
 economic=joblib.load(ROOT/'data/models.joblib') if economic is None else economic;events=joblib.load(ROOT/'data/event_models.joblib') if events is None else events;names=economic['feature_names'];features=request['features']
 if not isinstance(features,dict) or set(features)!=set(names):raise InputError('Feature names must match the frozen125-feature schema exactly')
 values=[]
 for name in names:
  v=features[name]
  if v is None:values.append(np.nan)
  elif isinstance(v,bool) or not isinstance(v,(int,float)) or not np.isfinite(v):raise InputError('Feature must be finite number or null: '+name)
  else:values.append(v)
 X=np.array([values],float)
 if abs(X[0,names.index('conditional_quantity_fraction')]-fraction)>1e-7:raise InputError('Quantity scenario and feature disagree')
 latest=X[0,0];raw24=X[0,names.index('raw_net_sum_24h_bp')]/1e4
 if not np.isfinite(latest):raise InputError('Latest settled funding is required')
 # Pick only an already-fitted month; do not silently use a future model.
 months=[m for m,x in economic['models'].items() if parse_time(x['metadata']['fit_asof_utc'])<=asof]
 if not months:raise InputError('No model with training cutoff before requested asof')
 month=max(months,key=lambda m:parse_time(economic['models'][m]['metadata']['fit_asof_utc']));em=economic['models'][month];fitted=parse_time(em['metadata']['fit_asof_utc']);model_stale=asof>=fitted+pd.offsets.MonthBegin(1);evaluated=parse_time(reference_now) if reference_now else pd.Timestamp.now(tz='UTC');expiry=asof+pd.Timedelta(days=1);snapshot_stale=evaluated>=expiry;missing_fraction=float(np.isnan(X).mean());extra=[]
 if snapshot_stale:extra.append('STALE_HISTORICAL_SNAPSHOT')
 if model_stale:extra.append('MODEL_MONTH_STALE')
 if missing_fraction>.25:extra.append('FEATURE_MISSING_OVER_25_PERCENT')
 if request['information_mode'] not in ['historical_hourly_proxy','observed_asof_snapshot']:raise InputError('Unsupported information_mode')
 if request['information_mode']=='historical_hourly_proxy':extra.append('RECEIVED_AT_NOT_HISTORICALLY_PROVEN')
 if not request['raw24_known']:extra.append('RAW24_UNKNOWN')
 forecasts={};fit_metadata={}
 for task,outkey in [('new_negative_72h','p_new_negative_within72h'),('survival_168h','p_no_raw24_exit_next168h'),('arrival_entry_7d','p_qualified_entry_after72h_within7d')]:
  definition=events['heads'][task][month];head=definition['estimators']['fixed_HGB_full'];meta=definition['metadata'];assert parse_time(meta['max_cal_label_end'])<asof
  current_ok=(latest>=0) if task=='new_negative_72h' else (latest<0 and request['raw24_known'] and np.isfinite(raw24) and raw24<=0) if task=='survival_168h' else True
  forecasts[outkey]=float(head.predict(X[:,:len(events['feature_names'])])[0]) if current_ok else None;fit_metadata[task]=meta
 if request['inventory_status']=='AVAILABLE':value=None;extra.append('VALUE_HEAD_ASSUMES_NEW72H_DELIVERY_NOT_EXISTING_STOCK')
 else:value=float(em['estimators']['hurdle_full'].predict(X)[0])
 forecasts['conditional_30d_reference_net_usdt']=value
 return {'schema_version':'nfb.signal-output.v3','request_id':str(request['request_id']),'symbol':str(request['symbol']),'asof_utc':asof.isoformat(),'feature_hour_start_utc':featuretime.isoformat(),'valid_until_utc':expiry.isoformat(),'model_version':economic['version'],'fit_month':month,'research_only':True,'submission_allowed':False,'status':'DATA_OR_TIMING_LIMITED' if extra else 'WATCH_ONLY','inventory_status':request['inventory_status'],'conditional_arrival_fraction':fraction,'forecasts':forecasts,'forecast_definitions':{'p_new_negative_within72h':'Any first negative settled print from current nonnegative state; can be shallow/brief. Not probability of crossing−0.1%8h.','p_no_raw24_exit_next168h':'No strictlypositive raw24 or delivery; does not imply every settlement remainsnegative.','p_qualified_entry_after72h_within7d':'At least one frozen strategy flat-entry opportunity in[t+72,t+240); not realized profit.','conditional_30d_reference_net_usdt':'Independent-coin full-exit reference value after72h arrival,30d entry window,9d unwind, frozen assumed costs+k4; not actual expected profit or additive joint portfolio value.'},'data_quality':{'missing_fraction':missing_fraction,'snapshot_stale':bool(snapshot_stale),'model_stale':bool(model_stale),'flags':extra,'information_mode':request['information_mode']},'economic_training':em['metadata'],'event_training':fit_metadata,'execution_actions':[]}

def main():
 try:
  request=json.loads(Path(sys.argv[1]).read_text()) if len(sys.argv)>1 else json.load(sys.stdin);out=score(request);print(json.dumps(clean(out),ensure_ascii=False,allow_nan=False))
 except (InputError,KeyError,json.JSONDecodeError) as e:print(json.dumps({'schema_version':'nfb.signal-output.v3','status':'INVALID_INPUT','submission_allowed':False,'error':str(e)},ensure_ascii=False));sys.exit(2)
if __name__=='__main__':main()
