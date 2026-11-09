from common import *
from features import qty_features
from model import EventHead,Hurdle
from signal_cli import score,InputError
import joblib,copy,subprocess,importlib.metadata

def main():
 f=loadnp(ROOT/'data/features.npz');names=np.r_[f['columns'],qty_features(f['core'][:1],1.)[1]].tolist();econ=joblib.load(ROOT/'data/models.joblib');events=joblib.load(ROOT/'data/event_models.joblib');scores=loadnp(ROOT/'data/scores.npz');eligible=f['eligible']&(f['hours']==f['hours'].max());assert len(names)==125;examples=[];checks=[]
 for sign,label in [(True,'nonnegative'),(False,'negative')]:
  choose=eligible&((f['X'][:,0]>=0) if sign else (f['X'][:,0]<0));ix=np.flatnonzero(choose);j=ix[np.argmax(scores['hurdle_full'][ix,1])];qx,_=qty_features(f['core'][j:j+1],1.);x=np.r_[f['X'][j],qx[0]];asof=stamp(f['hours'][j]);request={'schema_version':'nfb.signal-input.v3','request_id':'historical-demo-'+label,'symbol':str(f['symbols'][f['symbol_id'][j]]),'asof_utc':asof,'feature_hour_start_utc':stamp(f['hours'][j]-1),'conditional_arrival_fraction':1.,'inventory_status':'NOT_REQUESTED','raw24_known':True,'information_mode':'historical_hourly_proxy','features':{n:float(v) if np.isfinite(v) else None for n,v in zip(names,x)}};out=score(request,econ,events);save(ROOT/'interface'/('historical-'+label+'-input.json'),request);save(ROOT/'interface'/('historical-'+label+'-output.json'),out);examples.append(request)
  assert abs(out['forecasts']['conditional_30d_reference_net_usdt']-scores['hurdle_full'][j,1])<1e-8;assert not out['submission_allowed'] and out['execution_actions']==[];assert out['data_quality']['snapshot_stale'];assert (out['forecasts']['p_new_negative_within72h'] is not None)==sign
  if sign:assert out['forecasts']['p_no_raw24_exit_next168h'] is None
  raw=f['X'][j,f['columns'].tolist().index('raw_net_sum_24h_bp')];assert (out['forecasts']['p_no_raw24_exit_next168h'] is not None)==(not sign and raw<=0)
  checks.append(label+'_scores_cohort_and_expiry')
 base=examples[0]
 def reject(change,description):
  q=copy.deepcopy(base);change(q)
  try:score(q,econ,events);raise AssertionError('Expected reject '+description)
  except InputError:checks.append(description)
 reject(lambda q:q.update(feature_hour_start_utc=q['asof_utc']),'future_feature_rejected');reject(lambda q:q.update(asof_utc='2026-11-05T01:00:00+00:00'),'intraday_grid_rejected');reject(lambda q:q.update(conditional_arrival_fraction=.25),'out_of_quantity_support_rejected');reject(lambda q:q['features'].update(conditional_quantity_fraction=.5),'quantity_mismatch_rejected');reject(lambda q:q['features'].update(extra_future_profit=1),'unexpected_feature_rejected');reject(lambda q:q.update(asof_utc='2026-01-01T00:00:00+00:00',feature_hour_start_utc='2025-12-31T23:00:00+00:00'),'future_model_rejected');reject(lambda q:q['features'].update(settled_r8_bp=float('inf')),'nonfinite_feature_rejected')
 req=copy.deepcopy(base);req['inventory_status']='AVAILABLE';out=score(req,econ,events);assert out['forecasts']['conditional_30d_reference_net_usdt'] is None;checks.append('existing_inventory_not_misvalued_as_new72h_delivery');req=copy.deepcopy(examples[1]);req['raw24_known']=False;assert score(req,econ,events)['forecasts']['p_no_raw24_exit_next168h'] is None;checks.append('unknown_raw24_suspends_survival')
 # Real caller path through JSON stdin and CLI stdout.
 raw=subprocess.run([sys.executable,str(ROOT/'src/signal_cli.py')],input=json.dumps(base),capture_output=True,text=True,check=True);result=json.loads(raw.stdout);expected=score(base,econ,events);assert result['forecasts']==expected['forecasts'];checks.append('stdin_json_cli_roundtrip')
 request_schema={'$schema':'https://json-schema.org/draft/2020-12/schema','type':'object','additionalProperties':False,'required':list(base),'properties':{k:({'const':'nfb.signal-input.v3'} if k=='schema_version' else {'type':'object','additionalProperties':False,'required':names,'properties':{n:{'type':['number','null']} for n in names}} if k=='features' else {'type':'boolean'} if k=='raw24_known' else {'type':'number','minimum':.5,'maximum':1.} if k=='conditional_arrival_fraction' else {'enum':['NOT_REQUESTED','PENDING_72H','AVAILABLE']} if k=='inventory_status' else {'enum':['historical_hourly_proxy','observed_asof_snapshot']} if k=='information_mode' else {'type':'string'}) for k in base}};save(ROOT/'interface/INPUT_SCHEMA.json',request_schema);import jsonschema
 for request in examples:jsonschema.validate(request,request_schema)
 checks.append('example_json_schema_validation');save(ROOT/'interface/FEATURES.json',{'names':names,'features':125,'event_features':116,'cutoff':'asof-1 completed hour','economic_model_sha256':sha(ROOT/'data/models.joblib'),'event_model_sha256':sha(ROOT/'data/event_models.joblib')})
 # Compare already-established controls, all155 formal manifest files and fixed inputs.
 manifest=json.loads((ONLINE/'SOURCE_FILE_HASHES.json').read_text());mismatches=[p for p,v in manifest.items() if sha(ONLINE/p)!=v];assert not mismatches
 inputs=json.loads((ROOT/'PROTOCOL.json').read_text())['input_hashes'];assert all(sha(p)==v for p,v in inputs.items());checks.append('all_frozen_and_prior_inputs_unchanged')
 prior=pd.DataFrame(json.loads((ROOT.parent/'neg-funding-cross-period-validation-20261109/results/RESULTS.json').read_text())['cases']);current=pd.DataFrame(json.loads((OUT/'RESULTS.json').read_text())['cases']);parity=[]
 for p in ['earlier','later']:
  for method,days,slots in [('all_ready',0,0),('request_all_72h',0,0),('EMA72',15,20),('net_selected',15,20)]:
   old=prior[(prior.period==p)&(prior.scope=='long_period')&(prior.method==method)&(prior.refresh_days==days)&(prior.new_slots==slots)&(prior.k_scenario==4)].iloc[0];name='old_short_net' if method=='net_selected' else method;new=current[(current.period==p)&(current.scope=='long_period')&(current.method==name)&(current.refresh_days==days)&(current.new_slots==slots)].iloc[0];err=abs(old.closed_net_usdt-new.closed_net_usdt);assert err<1e-8;parity.append({'period':p,'control':method,'closed_net_difference_usdt':float(err)})
 checks.append('eight_prior_engine_controls_exactly_reproduced')
 libs={n:importlib.metadata.version(n) for n in ['numpy','pandas','scikit-learn','scipy','joblib','jsonschema','numba']};(ROOT/'requirements-research.txt').write_text('\n'.join(n+'=='+v for n,v in libs.items())+'\n');save(OUT/'VALIDATION.json',{'created_at':now(),'passed':True,'checks':checks,'checks_count':len(checks),'frozen_files_verified':len(manifest),'input_hashes_verified':len(inputs),'prior_control_parity':parity,'dependencies':libs,'backtests':len(current),'max_cash_identity_error_usdt':float(current.cash_identity_max_error_usdt.max()),'max_one_x_gap_hours_close_proxy':int(current.one_x_gap_hours_close_proxy.max()),'all_inventory_checks_passed':bool(current.inventory_and_arrival_checks_passed.all()),'no_live_execution_or_deploy':True});print(json.dumps({'passed':True,'checks':len(checks),'formal_files':len(manifest),'replays':len(current)}))
if __name__=='__main__':main()
