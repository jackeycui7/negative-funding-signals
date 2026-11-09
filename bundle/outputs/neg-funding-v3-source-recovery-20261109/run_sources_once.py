"""Run authorized independent data sources, then the byte-frozen v3 forward routine."""
from pathlib import Path
import sys,json,fcntl,subprocess,sqlite3,hashlib,shutil,traceback,datetime
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
from independent_sources import Datahub,FORWARD,ms,iso,H,atomic
PYTHON=ROOT.parent/'neg-funding-strategy-phase2-20261107/forward_validation_v2_20261107/.venv/bin/python'

def verify():
 binding=json.loads((ROOT/'SOURCE_BINDING.json').read_text())
 for file,expected in binding.items():
  if hashlib.sha256(Path(file).read_bytes()).hexdigest()!=expected:raise ValueError('SOURCE_ADAPTER_HASH_MISMATCH:'+file)
 protocol=json.loads((FORWARD/'PROTOCOL.json').read_text());v3=ROOT.parent/'neg-funding-inventory-value-v3-20261109'
 for name,h in protocol['model_bindings'].items():
  if hashlib.sha256((v3/name).read_bytes()).hexdigest()!=h:raise ValueError('MODEL_HASH_MISMATCH:'+name)
 for file,h in json.loads((FORWARD/'RUNTIME_BINDING.json').read_text()).items():
  if hashlib.sha256(Path(file).read_bytes()).hexdigest()!=h:raise ValueError('ORIGINAL_PIPELINE_HASH_MISMATCH:'+file)

def publish_health(run):
 c=sqlite3.connect(FORWARD/'data/market.sqlite');now=ms();closed=now//H*H
 # Match the frozen reader's final-known observation, so retained superseded mistakes and explicit NaN do not count as coverage.
 rows=c.execute("""WITH ranked AS (SELECT kind,symbol,event_ms,received_ms,payload,
 ROW_NUMBER() OVER(PARTITION BY kind,symbol,CASE WHEN kind IN ('oi','global_accounts','top_accounts','top_positions','taker_flow') THEN event_ms/3600000 ELSE event_ms END ORDER BY event_ms DESC,received_ms DESC,request_id DESC) rn
 FROM records WHERE kind IN ('spot','perp','premium','funding','oi','global_accounts','top_accounts','top_positions','taker_flow','bybit_funding'))
 SELECT kind,symbol,MAX(event_ms),MAX(received_ms) FROM ranked WHERE rn=1
 AND CASE WHEN kind='oi' THEN COALESCE(json_extract(payload,'$.sumOpenInterestValue'),'nan') NOT IN ('','nan','NaN')
 WHEN kind IN ('global_accounts','top_accounts','top_positions') THEN COALESCE(json_extract(payload,'$.longShortRatio'),'nan') NOT IN ('','nan','NaN')
 WHEN kind='taker_flow' THEN COALESCE(json_extract(payload,'$.buySellRatio'),'nan') NOT IN ('','nan','NaN') ELSE 1 END
 GROUP BY kind,symbol""").fetchall();families={}
 for kind in sorted({x[0] for x in rows}):
  group=[x for x in rows if x[0]==kind];target=closed-H if kind in ['spot','perp','premium'] else closed-H-300000 if kind=='oi' else closed-8*H if kind in ['funding','bybit_funding'] else closed-300000
  families[kind]={'symbols_with_records':len(group),'symbols_at_required_source_time':sum(t>=target for _,_,t,_ in group),'required_source_time_utc':iso(target),'latest_source_time_utc':iso(max(x[2] for x in group)),'latest_actual_receive_utc':iso(max(x[3] for x in group))}
 last=c.execute("SELECT MAX(received) FROM requests WHERE venue='aurabit_datahub' AND status=200").fetchone()[0];cool=[{'source':v,'until_utc':iso(t),'reason':reason,'active':t>now} for v,t,reason in c.execute('SELECT * FROM cooldown')];m=json.loads((FORWARD/'data/metrics-latest.json').read_text()) if (FORWARD/'data/metrics-latest.json').exists() else {}
 h={'at_utc':iso(now),'transport_version':'nfb.sources.20261109.r1','state':'AUTHORIZED_PROVIDER_RESPONDING_WITH_REMAINING_GAPS' if last and now-last<30*60000 else 'NO_RECENT_AUTHORIZED_PROVIDER_RESPONSE','last_datahub_success_utc':iso(last) if last else None,'source_coverage':families,'underlying_rest_cooldowns_preserved':cool,'predictions_real':m.get('primary_fraction1_prediction_rows',0),'verified_mature':sum(x['verified'] for x in m.get('heads',{}).values()),'known_gaps':['No current-day four positioning series via Datahub; official daily archive is next-day data','Bybit is not supplied by this Datahub schema; missing original cross-venue fields remain missing','Raw24/maturity correctness follows original frozen code;240/1008h labels still pending independent frozen replay'],'no_model_or_threshold_change':True,'last_run':run};c.close();atomic(ROOT/'RECOVERY_HEALTH.json',h);return h

def run(seconds=240,diagnostic=False):
 started=ms();lock=(ROOT/'run.lock').open('a+')
 try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:return {'status':'ALREADY_RUNNING','started_at_utc':iso(started)}
 report={'started_at_utc':iso(started),'sources':[],'status':'STARTED'};code=0
 try:
  verify()
  report['source_binding_sha256']=hashlib.sha256((ROOT/'SOURCE_BINDING.json').read_bytes()).hexdigest()
  report['source_contract_sha256']=hashlib.sha256((ROOT/'SOURCE_CONTRACT.json').read_bytes()).hexdigest()
  if shutil.disk_usage(ROOT).free<2*1024**3:raise ValueError('LESS_THAN2GIB_FREE_STOP_ACQUISITION_NO_AUTOMATIC_DELETION')
  day=started//86400000*86400000;on_grid=started-day<300000
  source=Datahub()
  try:
   report['datahub']=source.collect(75 if on_grid else seconds,latest_only=on_grid)
   if not on_grid:report['archive']=source.archive_cycle(min(40,max(0,seconds)))
   report['archive_missing_value_normalization']=source.repair_blank_archive_fields()
   report['oi_timestamp_normalization']=source.repair_oi_period_end_mapping()
  finally:source.s.close()
  # Preserve the original model,grid,deadline,cohort,ledger and diagnostic gates.
  args=[str(PYTHON),'-B',str(FORWARD/'run_once.py'),'--collect-seconds','1','--max-requests','0']
  if diagnostic:args.append('--diagnostic')
  process=subprocess.run(args,capture_output=True,text=True,timeout=330 if on_grid else 150);report['frozen_run_exit_code']=process.returncode
  report['frozen_run']=json.loads(process.stdout.strip().splitlines()[-1]) if process.stdout.strip() else None
  if process.returncode:raise ValueError('FROZEN_RUN_FAILED:'+process.stderr[-2500:]+str(report['frozen_run']))
  if report['datahub']['latest_failed_batches']:raise ValueError('DATAHUB_LATEST_BATCH_FAILURES_RETAINED')
  report['status']='COMPLETED'
 except Exception as e:report.update(status='FAILED',error=type(e).__name__+': '+str(e),traceback=traceback.format_exc());code=1
 finally:
  report['finished_at_utc']=iso(ms());atomic(ROOT/f'run-{started}.json',report);h=publish_health(report);fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
 return {'exit_code':code,'status':report['status'],'independent_source_state':h['state'],'source_health':str(ROOT/'RECOVERY_HEALTH.json'),'predictions_real':h['predictions_real'],'verified_mature':h['verified_mature'],'error':report.get('error')}

if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--seconds',type=int,default=240);p.add_argument('--diagnostic',action='store_true');a=p.parse_args();result=run(a.seconds,a.diagnostic);print(json.dumps(result,ensure_ascii=False));sys.exit(result.get('exit_code',0))
