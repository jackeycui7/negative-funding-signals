"""Allowlisted GET-only public market collector with immutable source versions and persistent cooldowns."""
from common import *
import sqlite3,urllib.request,urllib.error,urllib.parse,time,threading

ALLOWED={
 'binance_futures':('https://fapi.binance.com',{'/fapi/v1/exchangeInfo','/fapi/v1/fundingInfo','/fapi/v1/fundingRate','/fapi/v1/klines','/fapi/v1/premiumIndexKlines','/fapi/v1/markPriceKlines','/futures/data/openInterestHist','/futures/data/globalLongShortAccountRatio','/futures/data/topLongShortAccountRatio','/futures/data/topLongShortPositionRatio','/futures/data/takerlongshortRatio'}),
 'binance_spot':('https://api.binance.com',{'/api/v3/klines','/api/v3/exchangeInfo'}),
 'bybit':('https://api.bybit.com',{'/v5/market/funding/history','/v5/market/instruments-info'})}

class Cooldown(ValueError):pass
class Store:
 def __init__(self,root=ROOT):
  self.root=Path(root);(self.root/'data/raw').mkdir(parents=True,exist_ok=True)
  self.db=sqlite3.connect(self.root/'data/market.sqlite',timeout=30,isolation_level=None,check_same_thread=False);self.db.execute('PRAGMA journal_mode=WAL');self.lock=threading.RLock()
  self.db.executescript('''CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY,url TEXT,venue TEXT,path TEXT,requested INTEGER,received INTEGER,status INTEGER,hash TEXT,error TEXT);
  CREATE TABLE IF NOT EXISTS records(kind TEXT,symbol TEXT,event_ms INTEGER,received_ms INTEGER,payload TEXT,hash TEXT,request_id INTEGER,PRIMARY KEY(kind,symbol,event_ms,hash));
  CREATE TABLE IF NOT EXISTS cooldown(venue TEXT PRIMARY KEY,until_ms INTEGER,reason TEXT);
  CREATE TABLE IF NOT EXISTS completed_jobs(key TEXT PRIMARY KEY,finished_ms INTEGER,response_count INTEGER,status TEXT);
  ''')
 def close(self):self.db.close()
 def _throttle(self,venue,path,deadline):
  group='funding' if path in ['/fapi/v1/fundingRate','/fapi/v1/fundingInfo'] else 'metrics' if path.startswith('/futures/data/') else 'general'
  while True:
   now=ms()
   with self.lock:
    cool=self.db.execute('SELECT until_ms,reason FROM cooldown WHERE venue=?',(venue,)).fetchone()
    if cool and now<cool[0]:raise Cooldown(f'{venue} cooldown until {iso(cool[0])}: {cool[1]}')
    # Conservative shared endpoint-group limits and global pacing, retained across invocations.
    if group=='funding':count=self.db.execute("SELECT COUNT(*) FROM requests WHERE venue='binance_futures' AND path IN ('/fapi/v1/fundingRate','/fapi/v1/fundingInfo') AND requested>?",(now-300000,)).fetchone()[0];cap=440
    elif group=='metrics':count=self.db.execute("SELECT COUNT(*) FROM requests WHERE venue='binance_futures' AND path LIKE '/futures/data/%' AND requested>?",(now-300000,)).fetchone()[0];cap=850
    else:count=0;cap=1
    last=self.db.execute('SELECT MAX(requested) FROM requests').fetchone()[0] or 0
    wait=max(0.,(last+180-now)/1000)
   if count>=cap:wait=max(wait,1.)
   if not wait:
    with self.lock:
     # Reserve a request slot before another worker can pass the same gate.
     latest=self.db.execute('SELECT MAX(requested) FROM requests').fetchone()[0] or 0
     if ms()<latest+180:continue
     ident=self.db.execute('INSERT INTO requests(venue,path,requested) VALUES(?,?,?)',(venue,path,ms())).lastrowid
    return ident
   if now+wait*1000>=deadline:raise TimeoutError('PERSISTENT_RATE_BUDGET_DEFERRED')
   time.sleep(min(wait,1.))
 def get(self,venue,path,params=None,deadline=None):
  deadline=deadline or ms()+15000
  if venue not in ALLOWED or path not in ALLOWED[venue][1]:raise ValueError('Endpoint is not allowlisted')
  ident=self._throttle(venue,path,deadline)
  url=ALLOWED[venue][0]+path+('?' +urllib.parse.urlencode(params) if params else '')
  requested=ms();status=0;error=None;headers={};body=b''
  with self.lock:self.db.execute('UPDATE requests SET url=?,requested=? WHERE id=?',(url,requested,ident))
  try:
   req=urllib.request.Request(url,headers={'User-Agent':'nfb-forward-v3/1.0','Accept':'application/json'},method='GET')
   with urllib.request.urlopen(req,timeout=max(1,min(15,(deadline-ms())/1000))) as response:status=response.status;headers=dict(response.headers);body=response.read()
  except urllib.error.HTTPError as exc:status=exc.code;headers=dict(exc.headers);body=exc.read();error=str(exc)
  except Exception as exc:error=type(exc).__name__+': '+str(exc)
  received=ms();digest=hashlib.sha256(body).hexdigest();raw=self.root/'data/raw'/(digest+'.json')
  if not raw.exists():
   try:
    with raw.open('xb') as f:f.write(body)
   except FileExistsError:pass
  with self.lock:
   self.db.execute('UPDATE requests SET received=?,status=?,hash=?,error=? WHERE id=?',(received,status,digest,error,ident))
   if status in [403,418,429,451]:
    retry=headers.get('Retry-After',headers.get('retry-after',''))
    try:delay=max(600000,int(float(retry)*1000))
    except (ValueError,TypeError):delay=3600000 if status in [403,418,451] else 600000
    self.db.execute('INSERT OR REPLACE INTO cooldown VALUES(?,?,?)',(venue,received+delay,'HTTP_'+str(status)))
  if status!=200:raise ValueError(f'{venue} HTTP {status}: {error}')
  obj=json.loads(body)
  if isinstance(obj,dict) and (obj.get('code',0)<0 or obj.get('retCode',0)!=0):raise ValueError('SOURCE_ERROR:'+canonical(obj)[:300])
  return obj,{'request_id':ident,'requested_at_ms':requested,'received_at_ms':received,'raw_sha256':digest,'url':url}
 def append(self,kind,symbol,timestamp,payload,receipt):
  text=canonical(payload);h=hashlib.sha256(text.encode()).hexdigest()
  with self.lock:self.db.execute('INSERT OR IGNORE INTO records VALUES(?,?,?,?,?,?,?)',(kind,symbol,int(timestamp),int(receipt['received_at_ms']),text,h,receipt['request_id']))
 def records(self,kind=None,received_before=None):
  sql='SELECT kind,symbol,event_ms,received_ms,payload,request_id FROM records WHERE 1=1';args=[]
  if kind:sql+=' AND kind=?';args.append(kind)
  if received_before is not None:sql+=' AND received_ms<=?';args.append(received_before)
  sql+=' ORDER BY received_ms,request_id'
  with self.lock:return self.db.execute(sql,args).fetchall()
 def append_many(self,kind,symbol,rows,receipt):
  values=[]
  for timestamp,payload in rows:
   value=canonical(payload);digest=hashlib.sha256(value.encode()).hexdigest()
   values.append((kind,symbol,int(timestamp),int(receipt['received_at_ms']),value,digest,receipt['request_id']))
  with self.lock:
   self.db.execute('BEGIN IMMEDIATE')
   try:self.db.executemany('INSERT OR IGNORE INTO records VALUES(?,?,?,?,?,?,?)',values);self.db.execute('COMMIT')
   except BaseException:self.db.execute('ROLLBACK');raise
