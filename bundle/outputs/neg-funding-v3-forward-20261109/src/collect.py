"""Resumable public GET acquisition. No credentials or account endpoints."""
from common import *
from public_store import Store,Cooldown
import csv,concurrent.futures,time

META=OUTPUTS/'neg-funding-empirical-calibration-20261109/data/ds/dataset_meta.csv'
EXTRA_END=ORIGIN+11832*H
SEED_END=ORIGIN+11880*H
METRICS=[('oi','openInterestHist'),('global_accounts','globalLongShortAccountRatio'),('top_accounts','topLongShortAccountRatio'),('top_positions','topLongShortPositionRatio'),('taker_flow','takerlongshortRatio')]

def prepare():
 if (ROOT/'PROTOCOL.json').exists():return json.loads((ROOT/'PROTOCOL.json').read_text())
 meta=list(csv.DictReader(META.open()));binding=json.loads((OUTPUTS/'neg-funding-completion-20261109/runtime/v3_binding.json').read_text())
 inputs=[META,OUTPUTS/'neg-funding-empirical-calibration-20261109/data/ds/dataset.npz',OUTPUTS/'neg-funding-strategy-phase1-20261106/data/ds/dataset.npz',PHASE2/'model_v1/extra_features.npz',OUTPUTS.parent/'neg-funding-strategy-v1/private/inventory_caps.csv']
 protocol={'registered_at_utc':iso(ms()),'activation_ms':ms(),'version':'nfb.inventory-value.v3.20261109','status':'WATCH_ONLY','grid':'daily00UTC','recording_deadline_minutes':5,'feature_cutoff':'preceding completed hour; only sources actually received before issue','diagnostic_probability_threshold':0.5,'daily_top_k':10,'same_coin_cooldown_hours':72,'scenarios':[1.0,0.5],'primary_fraction':1.0,'model_stale_at_utc':'2026-12-01T00:00:00+00:00','model_stale_action':'STOP_PREDICTIONS_CONTINUE_COLLECTION_NO_RETRAIN','model_bindings':binding,'warm_history_imports':{str(p.resolve()):{'sha256':sha(p),'imported_at_utc':iso(ms()),'provenance':'pre-existing historical cache; historical received_at unavailable; imported before future forecasts'} for p in inputs},'universe':[dict(fut=m['fut'],spot=m['spot'],mult=float(m['mult']),delisted=m['delisted'],dl_exit=m['dl_exit']) for m in meta],'windows_hours':{'new_negative_72h':[0,72],'survival_168h':[0,168],'arrival_entry_7d':[72,240],'economic_reference':[72,1008]},'execution':False,'retraining':False,'selection_note':'Frozen339pair research universe, no performance-driven filtering.501inventorycoverage is separate. Threshold/ranking are diagnostics, not trading instructions.'}
 immutable(ROOT/'PROTOCOL.json',protocol);return protocol

def normalize(kind,obj,end):
 if kind in ['spot','perp','premium']:
  return [(int(x[0]),x) for x in obj if int(x[6])<=end and int(x[6])-int(x[0])>=H-1]
 if kind=='funding':return [(int(x['fundingTime']),x) for x in obj if int(x['fundingTime'])<=end]
 if kind=='bybit_funding':return [(int(x['fundingRateTimestamp']),x) for x in obj['result']['list'] if int(x['fundingRateTimestamp'])<=end]
 if kind in dict(METRICS):return [(int(x['timestamp']),x) for x in obj if int(x['timestamp'])<=end]
 return [(end,obj)]

def jobs(store,end,protocol,quotes_only=False):
 out=[];fmeta=store.db.execute("SELECT payload FROM records WHERE kind='futures_metadata' ORDER BY received_ms DESC LIMIT 1").fetchone();active={x['symbol'] for x in json.loads(fmeta[0])['symbols'] if x['status']=='TRADING'} if fmeta else None
 def add(kind,symbol,venue,path,params,priority):
  if quotes_only and kind not in ['spot','perp','premium']:return
  stop=params.get('endTime',end);recent=store.db.execute('SELECT MAX(received_ms) FROM records WHERE kind=? AND symbol=?',(kind,symbol)).fetchone()[0] or 0
  out.append(dict(kind=kind,symbol=symbol,venue=venue,path=path,params=params,end=stop,key=canonical([kind,symbol,params]),priority=priority,previous_receive=recent))
 def latest(kind,symbol,default):
  row=store.db.execute('SELECT MAX(event_ms) FROM records WHERE kind=? AND symbol=?',(kind,symbol)).fetchone()[0];return max(default,(row-H if row is not None else default))
 for m in protocol['universe']:
  sym=m['fut']
  if active is not None and sym not in active:continue
  for kind,venue,path,name,start in [('spot','binance_spot','/api/v3/klines',m['spot'],SEED_END),('perp','binance_futures','/fapi/v1/klines',sym,SEED_END),('premium','binance_futures','/fapi/v1/premiumIndexKlines',sym,EXTRA_END)]:
   a=latest(kind,sym,start)
   closed=(end//H)*H-1
   newest=store.db.execute('SELECT MAX(event_ms) FROM records WHERE kind=? AND symbol=?',(kind,sym)).fetchone()[0]
   if newest is not None and newest>=closed-H+1:continue
   for b in range(a,closed+1,499*H):add(kind,sym,venue,path,{'symbol':name,'interval':'1h','startTime':b,'endTime':min(closed,b+499*H-1),'limit':499},0)
  last_verified=store.db.execute("SELECT MAX(r.received) FROM requests r JOIN records o ON r.id=o.request_id WHERE o.kind='funding' AND o.symbol=?",(sym,)).fetchone()[0] or 0
  if last_verified//H<end//H:
   a=latest('funding',sym,SEED_END-16*H);add('funding',sym,'binance_futures','/fapi/v1/fundingRate',{'symbol':sym,'startTime':a,'endTime':end,'limit':1000},0)
  for kind,path in METRICS:
   # Exact5minute timestamps, last observation within each hour, matching the frozen archives.
   a=latest(kind,sym,EXTRA_END)
   for b in range(a,end+1,500*300000):
    stop=min(end,b+500*300000-1)
    add(kind,sym,'binance_futures','/futures/data/'+path,{'symbol':sym,'period':'5m','startTime':b,'endTime':stop,'limit':500},1 if stop>=end-24*H else 2)
 mapping=json.loads((PHASE2/'signal_strengthening_20261107/CROSS_VENUE_MAPPING.json').read_text())['mappings']
 for m in mapping:
  if active is not None and m['binance'] not in active:continue
  a=latest('bybit_funding',m['binance'],end-176*H)
  add('bybit_funding',m['binance'],'bybit','/v5/market/funding/history',{'category':'linear','symbol':m['bybit'],'startTime':a,'endTime':end,'limit':200},1)
 completed={r[0] for r in store.db.execute("SELECT key FROM completed_jobs WHERE status='OK'")}
 return sorted([j for j in out if j['key'] not in completed],key=lambda j:(j['priority'],j['previous_receive']))

def collect(seconds=240,max_requests=800,workers=6,quotes_only=False):
 p=prepare();s=Store();start=ms();deadline=start+int(seconds*1000);end=start-1;results=[]
 try:
  for kind,v,path in [('futures_metadata','binance_futures','/fapi/v1/exchangeInfo'),('funding_metadata','binance_futures','/fapi/v1/fundingInfo')]:
   recent=s.db.execute('SELECT MAX(received_ms) FROM records WHERE kind=?',(kind,)).fetchone()[0]
   if recent and start-recent<6*H:continue
   try:
    obj,r=s.get(v,path,deadline=deadline);s.append(kind,'ALL',r['received_at_ms'],obj,r)
   except Exception as e:results.append({'kind':kind,'error':str(e)})
  queue=jobs(s,end,p,quotes_only);cool={r[0]:r[1] for r in s.db.execute('SELECT venue,until_ms FROM cooldown') if r[1]>ms()};suspended=[j for j in queue if j['venue'] in cool];available=[j for j in queue if j['venue'] not in cool];selected=available[:max_requests]
  def one(j):
   if ms()>=deadline-16000:return {'kind':j['kind'],'symbol':j['symbol'],'status':'BUDGET_DEFERRED'}
   try:
    obj,r=s.get(j['venue'],j['path'],j['params'],deadline);rows=normalize(j['kind'],obj,j['end']);s.append_many(j['kind'],j['symbol'],rows,r)
    status='OK' if rows else 'EMPTY_RETRY_LATER'
    with s.lock:s.db.execute('INSERT OR REPLACE INTO completed_jobs VALUES(?,?,?,?)',(j['key'],ms(),len(rows),status))
    return {'kind':j['kind'],'symbol':j['symbol'],'status':status,'rows':len(rows),'received_at_ms':r['received_at_ms']}
   except Exception as e:return {'kind':j['kind'],'symbol':j['symbol'],'status':'DEFERRED' if isinstance(e,(Cooldown,TimeoutError)) else 'FAILED','error':str(e)}
  with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
   for r in pool.map(one,selected):results.append(r)
  report={'started_utc':iso(start),'finished_utc':iso(ms()),'source_cutoff_exclusive_utc':iso(end+1),'queued':len(queue),'attempted':len(selected),'suspended_by_source_cooldown':len(suspended),'deferred_by_page_budget':max(0,len(available)-len(selected)),'results':results,'cooldowns':s.db.execute('SELECT * FROM cooldown').fetchall()}
  immutable(ROOT/'data/runs'/f'collect-{start}.json',report)
  summary={k:v for k,v in report.items() if k!='results'};summary['statuses']={k:sum(r.get('status')==k for r in results) for k in ['OK','EMPTY_RETRY_LATER','FAILED','DEFERRED','BUDGET_DEFERRED']};atomic(ROOT/'data/collection-latest.json',summary);return summary
 finally:s.close()

if __name__=='__main__':
 import argparse
 ap=argparse.ArgumentParser();ap.add_argument('--seconds',type=int,default=240);ap.add_argument('--max-requests',type=int,default=800);args=ap.parse_args();print(json.dumps(collect(args.seconds,args.max_requests),ensure_ascii=False))
