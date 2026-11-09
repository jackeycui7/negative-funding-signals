from common import *
import sqlite3

HEADS={'p_new_negative_within72h':(0,72),'p_no_raw24_exit_next168h':(0,168),'p_qualified_entry_after72h_within7d':(72,240),'conditional_30d_reference_net_usdt':(72,1008)}
def probability_metrics(pairs):
 if not pairs:return {'n':0,'Brier':None,'AP':None,'fixed_bins':[]}
 brier=sum((p-y)**2 for p,y in pairs)/len(pairs);ordered=sorted(pairs,reverse=True);positives=sum(y for _,y in ordered);seen=0;hits=0;area=0.;groups={}
 for p,y in ordered:groups.setdefault(p,[]).append(y)
 for p,yy in groups.items():
  seen+=len(yy);hits+=sum(yy)
  if positives:area+=(sum(yy)/positives)*(hits/seen)
 bins=[]
 for i in range(10):
  yy=[(p,y) for p,y in pairs if i/10<=p<((i+1)/10) or (i==9 and p==1)]
  bins.append({'low':i/10,'high':(i+1)/10,'n':len(yy),'mean_probability':sum(p for p,y in yy)/len(yy) if yy else None,'event_rate':sum(y for p,y in yy)/len(yy) if yy else None})
 return {'n':len(pairs),'Brier':brier,'AP':area if positives else None,'fixed_bins':bins}
class Ledger:
 def __init__(self,path=None):
  self.db=sqlite3.connect(path or ROOT/'data/forward.sqlite',isolation_level=None)
  self.db.executescript('''CREATE TABLE IF NOT EXISTS grids(asof_ms INTEGER PRIMARY KEY,issued_ms INTEGER,status TEXT,payload TEXT);
   CREATE TABLE IF NOT EXISTS forecasts(id TEXT PRIMARY KEY,asof_ms INTEGER,issued_ms INTEGER,symbol TEXT,fraction REAL,hash TEXT,payload TEXT);
   CREATE TABLE IF NOT EXISTS coverage(asof_ms INTEGER,symbol TEXT,status TEXT,payload TEXT,PRIMARY KEY(asof_ms,symbol));
   CREATE TABLE IF NOT EXISTS alerts(asof_ms INTEGER,head TEXT,symbol TEXT,probability REAL,status TEXT,payload TEXT,PRIMARY KEY(asof_ms,head,symbol));
   CREATE TABLE IF NOT EXISTS outcomes(prediction_id TEXT,head TEXT,hash TEXT,logged_ms INTEGER,payload TEXT,PRIMARY KEY(prediction_id,head,hash));
   CREATE TABLE IF NOT EXISTS audit(at_ms INTEGER,status TEXT,payload TEXT);''')
 def audit(self,status,payload):self.db.execute('INSERT INTO audit VALUES(?,?,?)',(ms(),status,canonical(payload)))
 def grid(self,asof,status,payload):self.db.execute('INSERT OR IGNORE INTO grids VALUES(?,?,?,?)',(asof,ms(),status,canonical(payload)))
 def record(self,asof,rows,evidence,protocol,now=None):
  issued=ms() if now is None else now
  if asof%86400000 or not asof<=issued<asof+300000:raise ValueError('MISSED_FIXED_GRID_NO_BACKDATING')
  if asof<protocol['activation_ms']:raise ValueError('GRID_PRECEDES_ACTIVATION')
  if self.db.execute('SELECT 1 FROM grids WHERE asof_ms=?',(asof,)).fetchone():return False
  if not evidence.get('source_file_hashes'):raise ValueError('ACTUAL_SOURCE_HASHES_REQUIRED')
  latest=int(__import__('datetime').datetime.fromisoformat(evidence['received_at_utc']).timestamp()*1000)
  if latest>issued:raise ValueError('FUTURE_RECEIPT')
  for file,expected in evidence['source_file_hashes'].items():
   if sha(file)!=expected:raise ValueError('RAW_HASH_MISMATCH')
  for row in rows:
   q,p=row['request'],row['prediction']
   if q['request_id']!=p['request_id'] or q['symbol']!=p['symbol'] or int(__import__('datetime').datetime.fromisoformat(p['asof_utc']).timestamp()*1000)!=asof:raise ValueError('INPUT_OUTPUT_BINDING')
   if q['information_mode']!='observed_asof_snapshot':raise ValueError('PROSPECTIVE_RECEIVE_PROOF_REQUIRED')
   if p['model_version']!=protocol['version'] or p['submission_allowed'] is not False or p['research_only'] is not True:raise ValueError('FROZEN_RESEARCH_ONLY_REQUIRED')
   if p['data_quality']['model_stale'] or p['data_quality']['snapshot_stale']:raise ValueError('STALE_MODEL_OR_SNAPSHOT')
  # A full daily cohort is issued atomically with its coverage, not cherry-picked later.
  self.db.execute('BEGIN IMMEDIATE')
  try:
   self.db.execute('INSERT INTO grids VALUES(?,?,?,?)',(asof,issued,'ISSUED',canonical({'evidence':evidence,'rows':len(rows)})))
   symbols=set()
   for row in rows:
    p=row['prediction'];symbols.add(p['symbol']);body=canonical(row);h=hashlib.sha256(body.encode()).hexdigest();self.db.execute('INSERT INTO forecasts VALUES(?,?,?,?,?,?,?)',(p['request_id'],asof,issued,p['symbol'],p['conditional_arrival_fraction'],h,body))
   for m in protocol['universe']:self.db.execute('INSERT INTO coverage VALUES(?,?,?,?)',(asof,m['fut'],'SCORED' if m['fut'] in symbols else 'NOT_ELIGIBLE_OR_MISSING',canonical({'no_fill_or_imputation_of_missing_payments':True})))
   for head in list(HEADS)[:3]:
    eligible=[]
    for row in rows:
     p=row['prediction'];value=p['forecasts'][head]
     if p['conditional_arrival_fraction']==1 and value is not None and value>=protocol['diagnostic_probability_threshold']:eligible.append((p['symbol'],value,p['status']))
    eligible.sort(key=lambda x:-x[1]);selected=0
    for symbol,value,status in eligible:
     prev=self.db.execute("SELECT MAX(asof_ms) FROM alerts WHERE head=? AND symbol=? AND status='SELECTED'",(head,symbol)).fetchone()[0]
     reason='DATA_LIMITED' if status!='WATCH_ONLY' else 'COOLDOWN' if prev is not None and asof-prev<72*H else 'BELOW_DAILY_TOP10' if selected>=10 else 'SELECTED'
     if reason=='SELECTED':selected+=1
     self.db.execute('INSERT INTO alerts VALUES(?,?,?,?,?,?)',(asof,head,symbol,value,reason,canonical({'threshold':.5,'top_k':10,'cooldown_hours':72,'execution':False})))
   self.db.execute('COMMIT');return True
  except BaseException:self.db.execute('ROLLBACK');raise
 def metrics(self):
  forecasts=self.db.execute('SELECT COUNT(*),COUNT(DISTINCT asof_ms),COUNT(DISTINCT symbol) FROM forecasts').fetchone();out=[json.loads(x[0]) for x in self.db.execute('SELECT payload FROM outcomes ORDER BY logged_ms')];latest={}
  for x in out:latest[(x['prediction_id'],x['head'])]=x
  heads={};predictions={i:json.loads(payload) for i,payload in self.db.execute('SELECT id,payload FROM forecasts WHERE fraction=1')};selected={(a,h,s) for a,h,s in self.db.execute("SELECT asof_ms,head,symbol FROM alerts WHERE status='SELECTED'")}
  for head in HEADS:
   obs=[x for x in latest.values() if x['head']==head];good=[x for x in obs if x.get('evaluation_status')=='VERIFIED' and not x.get('late_data')];binary=[x for x in good if isinstance(x.get('outcome'),(int,float))]
   chosen=[x for x in binary if x['prediction_id'] in predictions and (int(datetime.fromisoformat(predictions[x['prediction_id']]['prediction']['asof_utc']).timestamp()*1000),head,predictions[x['prediction_id']]['prediction']['symbol']) in selected]
   pairs=[(predictions[x['prediction_id']]['prediction']['forecasts'][head],x['outcome']) for x in binary if x['prediction_id'] in predictions]
   baseline={method:probability_metrics([(predictions[x['prediction_id']]['frozen_baseline_probabilities'][head][method],x['outcome']) for x in binary if x['prediction_id'] in predictions and method in predictions[x['prediction_id']].get('frozen_baseline_probabilities',{}).get(head,{})]) for method in ['EMA72_calibrated','latest_or_age_calibrated']} if head!=list(HEADS)[-1] else {}
   heads[head]={'matured':len(obs),'verified':len(good),'missing_late_censored':len(obs)-len(good),'hits':sum(x['outcome'] for x in binary) if head!=list(HEADS)[-1] else None,'hit_rate':sum(x['outcome'] for x in binary)/len(binary) if binary and head!=list(HEADS)[-1] else None,'probability_metrics':probability_metrics(pairs) if head!=list(HEADS)[-1] else None,'frozen_baselines_same_observed_cohort':baseline,'selected_alert_observed':len(chosen),'selected_alert_precision_observed':sum(x['outcome'] for x in chosen)/len(chosen) if chosen else None}
  return {'created_at_utc':iso(ms()),'model_version':'nfb.inventory-value.v3.20261109','forecast_rows_including_quantity_scenarios':forecasts[0],'issued_daily_cohorts':forecasts[1],'distinct_scored_symbols':forecasts[2],'primary_fraction1_prediction_rows':self.db.execute('SELECT COUNT(*) FROM forecasts WHERE fraction=1').fetchone()[0],'grid_statuses':dict(self.db.execute('SELECT status,COUNT(*) FROM grids GROUP BY status').fetchall()),'alert_statuses':dict(self.db.execute('SELECT status,COUNT(*) FROM alerts GROUP BY status').fetchall()),'heads':heads,'quantity_scenarios_not_independent_samples':True,'adoption_status':'WATCH_ONLY','production_allowed':False}
 def close(self):self.db.close()
