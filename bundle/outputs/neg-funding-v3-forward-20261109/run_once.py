"""One bounded acquisition / frozen-grid forward cycle. Public market data only."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from common import *
from collect import collect,prepare
from ledger import Ledger
import argparse,fcntl,subprocess,sqlite3,traceback

PYTHON=PHASE2/'forward_validation_v2_20261107/.venv/bin/python'
def verify():
 p=prepare()
 for rel,h in p['model_bindings'].items():
  if sha(V3/rel)!=h:raise ValueError('FROZEN_MODEL_HASH_MISMATCH:'+rel)
 manifest=ROOT/'RUNTIME_BINDING.json'
 if not manifest.exists():raise ValueError('RUNTIME_NOT_RELEASED')
 for file,h in json.loads(manifest.read_text()).items():
  if sha(file)!=h:raise ValueError('FROZEN_PIPELINE_OR_HISTORY_HASH_MISMATCH:'+file)
 check=json.loads((ROOT/'tests/parity/parity.json').read_text())
 if not check.get('passed'):raise ValueError('FEATURE_PARITY_NOT_PASSED')
 return p

def worker(script,arguments,timeout):
 r=subprocess.run([str(PYTHON),'-B',str(ROOT/'src'/script),*arguments],capture_output=True,text=True,timeout=timeout)
 if r.returncode:raise RuntimeError(script+':'+r.stderr[-4000:])
 return json.loads(r.stdout.strip().splitlines()[-1])

def health(ledger,cycle):
 c=sqlite3.connect(ROOT/'data/market.sqlite');counts=[dict(kind=k,symbols=n,records=rows,latest_source_utc=iso(t),latest_received_utc=iso(r)) for k,n,rows,t,r in c.execute('SELECT kind,COUNT(DISTINCT symbol),COUNT(*),MAX(event_ms),MAX(received_ms) FROM records GROUP BY kind')];cool=[dict(venue=v,until_utc=iso(t),reason=reason,active=t>ms()) for v,t,reason in c.execute('SELECT * FROM cooldown')];fail=[dict(venue=v,path=p,http_status=s,count=n) for v,p,s,n in c.execute('SELECT venue,path,status,COUNT(*) FROM requests WHERE status IS NOT NULL AND status!=200 GROUP BY venue,path,status')];last=c.execute('SELECT MAX(received) FROM requests WHERE status=200').fetchone()[0];c.close();m=ledger.metrics()
 state={'created_at_utc':iso(ms()),'state':'DEGRADED_SOURCE_COOLDOWN' if any(x['active'] for x in cool) else 'COLLECTING','last_successful_response_utc':iso(last) if last else None,'source_coverage':counts,'persistent_cooldowns':cool,'historical_http_failures':fail,'next_daily_grid_utc':iso((ms()//86400000+1)*86400000),'models_and_thresholds_changed':False,'old_ledgers_changed':False,'predictions':m['primary_fraction1_prediction_rows'],'matured_verified':sum(h['verified'] for h in m['heads'].values()),'last_cycle':cycle}
 atomic(ROOT/'data/health.json',state);atomic(ROOT/'data/metrics-latest.json',m);return state

def run(seconds,max_requests,diagnostic=False):
 started=ms();stamp=iso(started);lock=(ROOT/'data/state/run.lock').open('a+')
 try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:return {'status':'ALREADY_RUNNING','at_utc':stamp}
 log=Ledger();cycle={'started_at_utc':stamp,'predictions_created':0};code=0
 try:
  protocol=verify();asof=started//86400000*86400000;grid=log.db.execute('SELECT status FROM grids WHERE asof_ms=?',(asof,)).fetchone();on_time=asof>=protocol['activation_ms'] and started<asof+300000 and not grid
  # Quotes close at00; funding/positioning were prefetched during the preceding hour.
  cycle['collection']=collect(min(seconds,185) if on_time else seconds,max_requests,quotes_only=on_time)
  stale=asof>=int(datetime.fromisoformat(protocol['model_stale_at_utc']).timestamp()*1000)
  if on_time and stale:log.grid(asof,'MODEL_MONTH_STALE',{'stop_predictions':True,'continue_public_collection':True,'no_retraining':True})
  elif on_time and ms()<asof+240000:
   folder=ROOT/'data/features'/f'grid-{asof}';folder.mkdir(parents=True,exist_ok=True);remain=max(1,int((asof+295000-ms())/1000));cycle['features']=worker('feature_worker.py',['--asof-ms',str(asof),'--folder',str(folder)],min(70,remain))
   remain=max(1,int((asof+295000-ms())/1000));cycle['score']=worker('feature_worker.py',['--score','--asof-ms',str(asof),'--folder',str(folder)],remain);rows=json.loads((folder/'scores.json').read_text());evidence=json.loads((folder/'evidence.json').read_text());evidence['model_file_hashes']=protocol['model_bindings'];evidence['warm_history_protocol_sha256']=sha(ROOT/'PROTOCOL.json')
   if log.record(asof,rows,evidence,protocol):cycle['predictions_created']=len(rows)
  elif not grid:log.grid(asof,'MISSED_AT_START' if asof<protocol['activation_ms'] else 'MISSED_FIXED_GRID',{'observed_at_utc':iso(ms()),'no_backdated_forecasts':True})
  if diagnostic:
   t=ms()//H*H;folder=ROOT/'data/features'/f'diagnostic-{started}';cycle['readiness_only']=worker('feature_worker.py',['--asof-ms',str(t),'--folder',str(folder)],90)
  cycle['maturation']=worker('outcome_worker.py',[],90);cycle['status']='COMPLETED'
 except Exception as exc:
  code=1;cycle['status']='FAILED';cycle['error']=type(exc).__name__+': '+str(exc);cycle['traceback']=traceback.format_exc();log.audit('FAILED',cycle)
 finally:
  cycle['finished_at_utc']=iso(ms());immutable(ROOT/'data/runs'/f'run-{started}.json',cycle);state=health(log,cycle);log.close();fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
 return {'exit_code':code,'state':state['state'],'predictions_created':cycle['predictions_created'],'health':str(ROOT/'data/health.json'),'metrics':str(ROOT/'data/metrics-latest.json'),'error':cycle.get('error')}

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--collect-seconds',type=int,default=240);ap.add_argument('--max-requests',type=int,default=2000);ap.add_argument('--diagnostic',action='store_true');args=ap.parse_args();result=run(args.collect_seconds,args.max_requests,args.diagnostic);print(json.dumps(result,ensure_ascii=False));sys.exit(result.get('exit_code',0))
