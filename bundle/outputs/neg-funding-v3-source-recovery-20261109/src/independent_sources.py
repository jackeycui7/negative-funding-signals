"""Authorized Datahub and checksum-verified public archive ingestion. Frozen model untouched."""
from pathlib import Path
import sys,json,time,hashlib,urllib.request,urllib.error,urllib.parse,sqlite3,io,csv,zipfile,datetime,concurrent.futures,threading,math
from email.utils import parsedate_to_datetime
ROOT=Path(__file__).resolve().parents[1]
FORWARD=ROOT.parent/'neg-funding-v3-forward-20261109'
sys.path.insert(0,str(FORWARD/'src'))
from public_store import Store
from common import canonical,iso,ms,atomic

class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  if urllib.parse.urlsplit(req.full_url).netloc!=urllib.parse.urlsplit(newurl).netloc:raise ValueError('CROSS_ORIGIN_REDIRECT_REJECTED')
  return super().redirect_request(req,fp,code,msg,headers,newurl)

class ProviderHTTPError(ValueError):
 def __init__(self,provider,status,body,receipt,error):
  super().__init__(provider+' HTTP '+str(status)+': '+str(error));self.status=status;self.body=body;self.receipt=receipt

def history_terminal(count,rejected,unavailable):
 # A successful empty HTTP response without an explicit coverage decision is not completion.
 return bool((count or unavailable) and not rejected)

def archive_number(value):
 # The unchanged reader accepts float('nan'); JSON null/blank would raise. This encodes absence, never zero.
 try:return value if math.isfinite(float(value)) else 'nan'
 except (ValueError,TypeError):return 'nan'

class IndependentSources:
 def __init__(self):self.s=Store(FORWARD);self.last=0;self.lock=threading.Lock()
 def fetch(self,url,provider,auth=False,timeout=20):
  host=urllib.parse.urlparse(url).hostname
  if host not in ['datahub.aurabitcapital.space','data.binance.vision']:raise ValueError('INDEPENDENT_SOURCE_HOST_NOT_ALLOWED')
  if auth and host!='datahub.aurabitcapital.space':raise ValueError('CREDENTIAL_DESTINATION_MISMATCH')
  with self.s.lock:cool=self.s.db.execute('SELECT until_ms FROM cooldown WHERE venue=?',(provider,)).fetchone()
  if cool and ms()<cool[0]:raise ValueError('INDEPENDENT_PROVIDER_COOLDOWN')
  with self.lock:
   delay=max(0,.2-(time.monotonic()-self.last))
   if delay:time.sleep(delay)
   self.last=time.monotonic()
  requested=ms();headers={'User-Agent':'nfb-independent-source/1.0'}
  if auth:headers['Authorization']='Bearer '+(Path.home()/'.datahub/api_key').read_text().strip()
  body=b'';status=0;error=None;response_headers={}
  try:
   with urllib.request.build_opener(SameOriginRedirect()).open(urllib.request.Request(url,headers=headers),timeout=timeout) as r:status=r.status;response_headers=dict(r.headers);body=r.read()
  except urllib.error.HTTPError as e:status=e.code;response_headers=dict(e.headers);body=e.read();error=str(e)
  except Exception as e:error=type(e).__name__+': '+str(e)
  received=ms();digest=hashlib.sha256(body).hexdigest();file=FORWARD/'data/raw'/(digest+'.json')
  if not file.exists():
   try:
    with file.open('xb') as f:f.write(body)
   except FileExistsError:pass
  with self.s.lock:
   ident=self.s.db.execute('INSERT INTO requests(url,venue,path,requested,received,status,hash,error) VALUES(?,?,?,?,?,?,?,?)',(url,provider,urllib.parse.urlparse(url).path,requested,received,status,digest,error)).lastrowid
   if status in [403,418,429,451]:
    retry=response_headers.get('Retry-After',response_headers.get('retry-after',''));delay=3600000
    try:delay=max(delay,int(float(retry)*1000))
    except (TypeError,ValueError):
     try:delay=max(delay,int(parsedate_to_datetime(retry).timestamp()*1000)-received)
     except (TypeError,ValueError,OverflowError):pass
    self.s.db.execute('INSERT OR REPLACE INTO cooldown VALUES(?,?,?)',(provider,received+delay,'HTTP_'+str(status)))
  receipt={'request_id':ident,'requested_at_ms':requested,'received_at_ms':received,'raw_sha256':digest,'url':url,'provider':provider,'response_headers':response_headers}
  if status!=200:raise ProviderHTTPError(provider,status,body,receipt,error)
  return body,receipt
 def register_cached(self,path,checksum,original_url):
  body=path.read_bytes();digest=hashlib.sha256(body).hexdigest()
  if checksum.read_text().split()[0]!=digest:raise ValueError('CACHED_OFFICIAL_CHECKSUM_MISMATCH')
  now=ms();file=FORWARD/'data/raw'/(digest+'.json')
  if not file.exists():
   with file.open('xb') as f:f.write(body)
  with self.s.lock:ident=self.s.db.execute('INSERT INTO requests(url,venue,path,requested,received,status,hash,error) VALUES(?,?,?,?,?,?,?,?)',(original_url,'binance_public_archive_cached_import',str(path),now,now,200,digest,None)).lastrowid
  return body,{'request_id':ident,'received_at_ms':now,'requested_at_ms':now,'raw_sha256':digest,'url':original_url,'cache_imported_now_not_historical_receipt':True}
 def metrics(self,symbol,day):
  url=f'https://data.binance.vision/data/futures/um/daily/metrics/{symbol}/{symbol}-metrics-{day}.zip';key=canonical(['independent_archive_metrics',symbol,day])
  with self.s.lock:done=self.s.db.execute("SELECT finished_ms,status FROM completed_jobs WHERE key=?",(key,)).fetchone()
  if done and done[1]=='OK':return {'symbol':symbol,'day':day,'status':'ALREADY_IMPORTED'}
  if done and done[1]=='SOURCE_404' and ms()-done[0]<6*H:return {'symbol':symbol,'day':day,'status':'SOURCE_404_RETRY_AFTER6H'}
  cached=ROOT.parent/'neg-funding-last30d-20261108/raw/oi'/symbol/(day+'.zip');check=cached.with_suffix('.zip.CHECKSUM')
  if cached.exists() and check.exists():body,r=self.register_cached(cached,check,url)
  else:
   try:body,r=self.fetch(url,'binance_public_archive');checksum,rr=self.fetch(url+'.CHECKSUM','binance_public_archive')
   except ValueError as e:
    if ' HTTP 404:' in str(e):
     with self.s.lock:self.s.db.execute('INSERT OR REPLACE INTO completed_jobs VALUES(?,?,?,?)',(key,ms(),0,'SOURCE_404'))
    raise
   if checksum.decode().split()[0]!=hashlib.sha256(body).hexdigest():raise ValueError('OFFICIAL_CHECKSUM_MISMATCH')
  groups={k:[] for k in ['oi','global_accounts','top_accounts','top_positions','taker_flow']}
  with zipfile.ZipFile(io.BytesIO(body)) as z:
   rows=list(csv.DictReader(io.TextIOWrapper(z.open(z.namelist()[0]))))
  for x in rows:
   t=int(datetime.datetime.fromisoformat(x['create_time']).replace(tzinfo=datetime.timezone.utc).timestamp()*1000)
   groups['oi'].append((t,{'symbol':symbol,'timestamp':t,'sumOpenInterest':archive_number(x['sum_open_interest']),'sumOpenInterestValue':archive_number(x['sum_open_interest_value']),'_source_provider':'binance_public_archive'}))
   for kind,column in [('global_accounts','count_long_short_ratio'),('top_accounts','count_toptrader_long_short_ratio'),('top_positions','sum_toptrader_long_short_ratio'),('taker_flow','sum_taker_long_short_vol_ratio')]:groups[kind].append((t,{'symbol':symbol,'timestamp':t,'buySellRatio' if kind=='taker_flow' else 'longShortRatio':archive_number(x[column]),'_source_provider':'binance_public_archive'}))
  for kind,values in groups.items():self.s.append_many(kind,symbol,values,r)
  with self.s.lock:self.s.db.execute('INSERT OR REPLACE INTO completed_jobs VALUES(?,?,?,?)',(key,ms(),len(rows),'OK'))
  return {'symbol':symbol,'day':day,'status':'OK','five_minute_rows':len(rows),'normalized_rows':sum(len(v) for v in groups.values()),'checksum_verified':True}
 def repair_blank_archive_fields(self):
  # Append normalization revisions; retain every original row,raw ZIP and failure. No historical prediction is changed.
  query="""SELECT kind,symbol,event_ms,payload,hash,request_id FROM records WHERE json_extract(payload,'$._source_provider')='binance_public_archive' AND (json_extract(payload,'$.longShortRatio')='' OR json_extract(payload,'$.buySellRatio')='' OR json_extract(payload,'$.sumOpenInterestValue')='')"""
  with self.s.lock:rows=self.s.db.execute(query).fetchall()
  added=0
  for kind,symbol,t,payload,digest,rid in rows:
   p=json.loads(payload);changed=[]
   for key in ['sumOpenInterest','sumOpenInterestValue','longShortRatio','buySellRatio']:
    if key in p and archive_number(p[key])!=p[key]:p[key]=archive_number(p[key]);changed.append(key)
   if not changed:continue
   p['_normalization_revision']={'missing_fields':changed,'original_normalized_sha256':digest,'reason':'SOURCE_BLANK_REMAINS_MISSING_NOT_ZERO'}
   value=canonical(p);newhash=hashlib.sha256(value.encode()).hexdigest()
   with self.s.lock:
    added+=self.s.db.execute('INSERT OR IGNORE INTO records VALUES(?,?,?,?,?,?,?)',(kind,symbol,t,ms(),value,newhash,rid)).rowcount
  return {'original_blank_rows_retained':len(rows),'missing_encoding_revisions_appended':added,'history_or_model_modified':False}
 def repair_oi_period_end_mapping(self):
  key=canonical(['source_normalization','datahub_oi_period_end_minus5m_v1'])
  with self.s.lock:
   if self.s.db.execute("SELECT 1 FROM completed_jobs WHERE key=? AND status='OK'",(key,)).fetchone():return {'status':'ALREADY_REPLAYED'}
   legacy=self.s.db.execute("SELECT symbol,event_ms,payload,hash,request_id FROM records WHERE kind='oi' AND json_extract(payload,'$._provider')='aurabit_datahub' AND json_extract(payload,'$._provider_period_end_ms') IS NULL").fetchall()
   requests=self.s.db.execute("SELECT id,received,hash FROM requests WHERE venue='aurabit_datahub' AND path='/v1/open-interest' AND status=200 ORDER BY received,id").fetchall()
  # Old normalization is preserved, but cannot override native archive observations or masquerade as current OI.
  revised=0
  for symbol,t,payload,digest,rid in legacy:
   with self.s.lock:reference=self.s.db.execute("SELECT payload,request_id FROM records WHERE kind='oi' AND symbol=? AND event_ms=? AND json_extract(payload,'$._source_provider')='binance_public_archive' ORDER BY received_ms DESC LIMIT 1",(symbol,t)).fetchone()
   if reference:p=json.loads(reference[0]);reference_id=reference[1]
   else:p={'timestamp':t,'sumOpenInterestValue':'nan','sumOpenInterest':'nan'};reference_id=rid
   p['_source_normalization_revision']={'reason':'OLD_PROVIDER_PERIOD_END_WAS_NOT_NATIVE_TIMESTAMP','retained_original_sha256':digest,'native_archive_used':bool(reference)}
   self.s.append('oi',symbol,t,p,{'received_at_ms':ms(),'request_id':reference_id});revised+=1
  replayed=0;quarantined=0
  for rid,received,digest in requests:
   data=json.loads((FORWARD/'data/raw'/(digest+'.json')).read_bytes());groups={}
   for row in data.get('data',[]):
    iid=row.get('instrument_id','')
    if not iid.startswith('binance:') or iid.startswith('binance:spot:'):continue
    groups.setdefault(iid.removeprefix('binance:'),[]).append(row)
   for symbol,rows in groups.items():
    g,b=self.ingest('oi',symbol,rows,{'received_at_ms':ms(),'request_id':rid},data.get('units'));replayed+=g;quarantined+=b
  with self.s.lock:self.s.db.execute('INSERT OR REPLACE INTO completed_jobs VALUES(?,?,?,?)',(key,ms(),replayed,'OK'))
  return {'legacy_rows_retained':len(legacy),'superseding_revisions':revised,'native_timestamp_rows_replayed':replayed,'quarantined':quarantined,'no_earlier_forecasts_changed':True}
 def archive_cycle(self,seconds=40):
  now=ms();deadline=now+seconds*1000;protocol=json.loads((FORWARD/'PROTOCOL.json').read_text());day=now//86400000*86400000;jobs=[]
  with self.s.lock:done={key:(t,status) for key,t,status in self.s.db.execute('SELECT key,finished_ms,status FROM completed_jobs')}
  for offset in [1,2]:
   date=datetime.datetime.fromtimestamp((day-offset*86400000)/1000,datetime.timezone.utc).date().isoformat()
   for m in protocol['universe']:
    key=canonical(['independent_archive_metrics',m['fut'],date]);prior=done.get(key)
    if prior and (prior[1]=='OK' or prior[1]=='SOURCE_404' and now-prior[0]<6*H):continue
    jobs.append((m['fut'],date))
  def one(job):
   if ms()>deadline-20000:return {'symbol':job[0],'day':job[1],'status':'TIME_BUDGET_DEFERRED'}
   try:return self.metrics(*job)
   except Exception as e:return {'symbol':job[0],'day':job[1],'status':'FAILED','error':str(e)}
  with concurrent.futures.ThreadPoolExecutor(3) as pool:results=list(pool.map(one,jobs))
  return {'pending_at_start':len(jobs),'results':results,'ok':sum(x['status']=='OK' for x in results),'failed':sum(x['status']=='FAILED' for x in results),'deferred':sum(x['status']=='TIME_BUDGET_DEFERRED' for x in results)}
 def archive_batch(self,symbols,days):
  jobs=[(s,d) for d in days for s in symbols];out=[]
  def one(job):
   try:return self.metrics(*job)
   except Exception as e:return {'symbol':job[0],'day':job[1],'status':'FAILED','error':str(e)}
  with concurrent.futures.ThreadPoolExecutor(3) as pool:
   for i,row in enumerate(pool.map(one,jobs)):
    out.append(row)
    if i%30==0:atomic(ROOT/'archive-progress.json',{'finished':len(out),'total':len(jobs),'ok':sum(x['status']=='OK' for x in out),'failures':sum(x['status']=='FAILED' for x in out),'at_utc':iso(ms())})
  path=ROOT/f'archive-run-{ms()}.json';atomic(path,{'results':out,'summary':{'total':len(out),'OK':sum(x['status']=='OK' for x in out),'already_imported':sum(x['status']=='ALREADY_IMPORTED' for x in out),'failures':sum(x['status']=='FAILED' for x in out),'normalized_rows_added':sum(x.get('normalized_rows',0) for x in out)}});return str(path)

H=3600000
SEED_END=1794096000000
EXTRA_END=1793923200000
def normalize_datahub(kind,row,received,units=None):
 """Return native-shaped values consumed by the unchanged125-feature builder."""
 if kind in ['spot','perp','premium']:
  t=int(row['open_time_ms'])
  if row.get('interval')!='1h' or t%H or t+H>received:raise ValueError('UNFINISHED_OR_OFFGRID_BAR')
  if row.get('complete') is not True or row.get('incomplete_reason') is not None:raise ValueError('SOURCE_INCOMPLETE_BAR')
  if row.get('finalized_at_ms') and row['finalized_at_ms']>received:raise ValueError('FUTURE_FINALIZATION')
  prices=[row.get(k) for k in ['open','high','low','close']]
  if any(x is None for x in prices):raise ValueError('NULL_OHLC')
  if kind!='premium' and (row.get('quote_volume') is None or row.get('volume') is None):raise ValueError('NULL_TRADE_VOLUME_NO_FABRICATION')
  x=[t,*prices,row.get('volume'),t+H-1,row.get('quote_volume'),row.get('trade_count'),row.get('taker_buy_volume'),row.get('taker_buy_quote_volume'),None]
  return t,x
 if kind=='funding':
  if row.get('rate_type')!='regular':raise ValueError('SPECIAL_SETTLEMENT_REQUIRES_SEPARATE_ACCOUNTING')
  if row.get('source')!='binance_funding_rate':raise ValueError('WRONG_FUNDING_SOURCE')
  t=int(row['funding_ts_ms'])
  if t>received:raise ValueError('FUTURE_FUNDING_EVENT')
  return t,{'fundingTime':t,'fundingRate':row['rate'],'markPrice':row.get('mark_px'),'_provider':'aurabit_datahub','_provider_interval_hours':row.get('interval_hours'),'_provider_recv_ms':row.get('recv_ts_ms'),'_provider_revision':row.get('revision')}
 if kind=='oi':
  if row.get('period')!='5m' or not units or units.get('open_interest_value')!='quote':raise ValueError('OI_PERIOD_OR_QUOTE_UNIT_MISMATCH')
  if row.get('open_interest_value') is None:raise ValueError('NULL_OI_VALUE_NO_PRICE_ESTIMATION')
  period_end=int(row['time_ms']);t=period_end-300000
  if period_end>received:raise ValueError('FUTURE_OI')
  if period_end%300000:raise ValueError('OFFGRID_OI_PERIOD_END')
  return t,{'timestamp':t,'sumOpenInterest':row.get('open_interest'),'sumOpenInterestValue':row['open_interest_value'],'_provider':'aurabit_datahub','_provider_recv_ms':row.get('recv_ms'),'_provider_source':row.get('source'),'_provider_period_end_ms':period_end,'_native_timestamp_rule':'period_end_minus_5m'}
 raise ValueError('UNSUPPORTED_DATAHUB_FEATURE_KIND')

class Datahub(IndependentSources):
 def page(self,path,params):
  if path not in ['/v1/status','/v1/instruments','/v1/markets','/v1/klines','/v1/funding','/v1/open-interest','/v1/latest/klines','/v1/latest/funding']:raise ValueError('DATAHUB_ENDPOINT_NOT_ALLOWED')
  body,receipt=self.fetch('https://datahub.aurabitcapital.space'+path+'?'+urllib.parse.urlencode(params),'aurabit_datahub',True)
  result=json.loads(body)
  if 'error' in result:raise ValueError('DATAHUB_SOURCE_ERROR:'+canonical(result['error']))
  return result,receipt
 def ingest(self,kind,symbol,data,receipt,units=None):
  good=[];bad=[]
  for row in data:
   try:good.append(normalize_datahub(kind,row,receipt['received_at_ms'],units))
   except (ValueError,KeyError,TypeError) as e:bad.append({'reason':str(e),'row':row})
  if kind=='oi':
   # Keep the final actual observation per hour. The complete5m response remains immutable in raw.
   hourly={}
   for t,p in good:
    if t//H not in hourly or t>hourly[t//H][0]:hourly[t//H]=(t,p)
   good=list(hourly.values())
  self.s.append_many(kind,symbol,good,receipt)
  if bad:self.s.append('datahub_quarantine',symbol,receipt['received_at_ms'],{'kind':kind,'rejected':bad},receipt)
  return len(good),len(bad)
 def history(self,kind,symbol,instrument,start,end):
  path='/v1/funding' if kind=='funding' else '/v1/open-interest' if kind=='oi' else '/v1/klines'
  params={'instrument':instrument,'start':int(start),'end':int(end),'limit':1000}
  if kind in ['spot','perp','premium']:params.update(type='premium' if kind=='premium' else 'trade',interval='1h')
  if kind=='oi':params['period']='5m'
  pages=0;count=0;rejected=0;unavailable=[]
  while pages<20:
   data,r=self.page(path,params);pages+=1;g,b=self.ingest(kind,symbol,data.get('data',[]),r,data.get('units'));count+=g;rejected+=b
   self.s.append('datahub_coverage',symbol,r['received_at_ms'],{'kind':kind,'start':start,'end':end,'covered':data.get('meta',{}).get('covered'),'unavailable':data.get('unavailable',[]),'next_cursor_present':bool(data.get('next_cursor')),'rows_returned':len(data.get('data',[])),'provider_request_id':data.get('meta',{}).get('request_id')},r)
   unavailable.extend(data.get('unavailable',[]));cursor=data.get('next_cursor')
   if not cursor:return {'kind':kind,'symbol':symbol,'status':'OK' if count and not rejected else 'EXPLICIT_SOURCE_UNAVAILABLE' if unavailable and not rejected else 'PENDING_SOURCE_OR_QUARANTINE','terminal':history_terminal(count,rejected,unavailable),'rows':count,'quarantined':rejected,'pages':pages}
   params['cursor']=cursor
  raise ValueError('DATAHUB_PAGE_BUDGET_EXCEEDED')
 def latest(self,universe):
  reverse={};groups=[]
  for m in universe:
   reverse.setdefault('binance:'+m['fut'],[]).append(('perp',m['fut']));reverse.setdefault('binance:spot:'+m['spot'],[]).append(('spot',m['fut']))
  futures=['binance:'+m['fut'] for m in universe];trades=list(reverse)
  for path,kind,instruments in [('/v1/latest/klines','trade',trades),('/v1/latest/klines','premium',futures),('/v1/latest/funding','funding',futures)]:
   for offset in range(0,len(instruments),30):groups.append((path,kind,instruments[offset:offset+30]))
  def one(job):
   path,kind,instruments=job;instruments=list(instruments);missing=[]
   try:
    while instruments:
     params=[('instrument',v) for v in instruments]
     if kind!='funding':params.extend([('type',kind),('interval','1h')])
     try:data,r=self.page(path,params);break
     except ProviderHTTPError as exc:
      try:error=json.loads(exc.body).get('error',{});unknown=error.get('message','').removeprefix('unknown instrument ')
      except (ValueError,TypeError):raise exc
      if exc.status!=404 or error.get('code')!='unknown_instrument' or unknown not in instruments:raise
      instruments.remove(unknown);missing.append(unknown)
      for meta in reverse.get(unknown,[]):self.s.append('datahub_source_unavailable',meta[1],exc.receipt['received_at_ms'],{'kind':kind,'instrument':unknown,'reason':'unknown_instrument','no_universe_or_model_change':True},exc.receipt)
    if not instruments:return {'kind':kind,'status':'EXPLICIT_SOURCE_UNAVAILABLE','rows':0,'missing_instruments':missing}
    count=0;quarantine=0
    for event in data.get('data',[]):
     row=event.get('data',{});iid=row.get('instrument_id');metas=reverse.get(iid,[])
     for meta in metas:
      destkind='funding' if kind=='funding' else 'premium' if kind=='premium' else meta[0];g,b=self.ingest(destkind,meta[1],[row],r);count+=g;quarantine+=b
    return {'kind':kind,'status':'OK_WITH_SOURCE_MISSING' if missing else 'OK','rows':count,'quarantined':quarantine,'unavailable':data.get('unavailable',[]),'missing_instruments':missing}
   except Exception as e:return {'kind':kind,'status':'FAILED','error':str(e)}
  with concurrent.futures.ThreadPoolExecutor(4) as pool:results=list(pool.map(one,groups))
  return results
 def collect(self,seconds=240,latest_only=False):
  protocol=json.loads((FORWARD/'PROTOCOL.json').read_text());universe=protocol['universe'];started=ms();end=started//H*H;deadline=started+seconds*1000
  # Snapshot previous state before adding latest points, so latest never hides a missed interval.
  before={(k,s):int(t) for k,s,t in self.s.db.execute("SELECT kind,symbol,MAX(event_ms) FROM records WHERE kind IN ('spot','perp','premium','funding','oi') GROUP BY kind,symbol")}
  out=[]
  funding_now={s:(int(t),interval) for s,t,interval in self.s.db.execute("SELECT symbol,MAX(event_ms),json_extract(payload,'$._provider_interval_hours') FROM records WHERE kind='funding' GROUP BY symbol")}
  if not latest_only:
   self.s.db.execute('CREATE TABLE IF NOT EXISTS independent_history_queue(key TEXT PRIMARY KEY,kind TEXT,symbol TEXT,instrument TEXT,start_ms INTEGER,end_ms INTEGER,state TEXT,last_attempt_ms INTEGER,result TEXT)')
   covered={(s,k):int(t) for s,k,t in self.s.db.execute("SELECT symbol,json_extract(payload,'$.kind'),MIN(json_extract(payload,'$.start')) FROM records WHERE kind='datahub_coverage' AND json_extract(payload,'$.next_cursor_present')=0 AND (json_extract(payload,'$.rows_returned')>0 OR json_array_length(json_extract(payload,'$.unavailable'))>0) GROUP BY symbol,json_extract(payload,'$.kind')")}
   for m in universe:
    s=m['fut']
    for kind in ['spot','perp','premium','funding','oi']:
     last=before.get((kind,s));default=EXTRA_END if kind=='premium' else SEED_END-16*H if kind=='funding' else SEED_END
     target=end-H if kind in ['spot','perp','premium'] else end-H-5*60000 if kind=='oi' else end-8*H
     bootstrap=covered.get((s,kind),ms())>default
     needed=True
     if not bootstrap and kind=='funding' and last is not None:
      current,interval=funding_now.get(s,(last,None));cadence=max(1,float(interval or 1))*H
      if current-last<=cadence+60000 and started-current<=9*H:needed=False
     elif not bootstrap and last is not None and last>=target:needed=False
     if not needed:continue
     start=default if bootstrap else max(default,last-H if last is not None else default);stop=started if kind=='funding' else end;instrument='binance:spot:'+m['spot'] if kind=='spot' else 'binance:'+s;key=canonical([kind,s,start,stop])
     # Persist before attempting it: a latest snapshot must never hide deferred historical gaps.
     self.s.db.execute('INSERT OR IGNORE INTO independent_history_queue VALUES(?,?,?,?,?,?,?,?,?)',(key,kind,s,instrument,start,stop,'PENDING',None,None))
  # Persist intentions before latest snapshots can advance MAX(event_ms), including across process crashes.
  recent=self.latest(universe)
  if latest_only:
   # Give closed-hour publication a bounded grace period inside the unchanged5minute issue window.
   # Nothing is scored or backdated here; the original ledger enforces the actual issuance deadline.
   wait_until=min(end+65000,deadline-20000)
   while ms()<wait_until:time.sleep(min(1,(wait_until-ms())/1000))
   if ms()<deadline-10000:recent.extend(self.latest(universe))
  if not latest_only:
   queued=self.s.db.execute("SELECT key,kind,symbol,instrument,start_ms,end_ms FROM independent_history_queue WHERE state!='DONE' ORDER BY CASE kind WHEN 'funding' THEN 0 WHEN 'spot' THEN 1 WHEN 'perp' THEN 2 WHEN 'oi' THEN 3 ELSE 4 END,start_ms,end_ms").fetchall()
   # Coalesce duplicate pending intervals without discarding evidence of their creation.
   groups={}
   for key,kind,s,instrument,a,b in queued:
    g=groups.setdefault((kind,s,instrument),{'keys':[],'start':a,'end':b});g['keys'].append(key);g['start']=min(g['start'],a);g['end']=max(g['end'],b)
   jobs=[(kind,s,instrument,g['start'],g['end'],g['keys']) for (kind,s,instrument),g in groups.items()]
   def one(job):
    if ms()>deadline-20000:return {'kind':job[0],'symbol':job[1],'status':'TIME_BUDGET_DEFERRED'}
    try:
     result=self.history(*job[:5])
     with self.s.lock:self.s.db.executemany('UPDATE independent_history_queue SET state=?,last_attempt_ms=?,result=? WHERE key=?',[('DONE' if result.get('terminal') else 'PENDING',ms(),canonical(result),key) for key in job[5]])
     return result
    except Exception as e:
     result={'kind':job[0],'symbol':job[1],'status':'FAILED','error':str(e)}
     with self.s.lock:self.s.db.executemany('UPDATE independent_history_queue SET last_attempt_ms=?,result=? WHERE key=?',[(ms(),canonical(result),key) for key in job[5]])
     return result
   with concurrent.futures.ThreadPoolExecutor(4) as pool:
    for i,row in enumerate(pool.map(one,jobs)):
     out.append(row)
     if i%30==0:atomic(ROOT/'datahub-progress.json',{'finished':len(out),'total':len(jobs),'successful':sum(x['status']=='OK' for x in out),'at_utc':iso(ms())})
  report={'started_at_utc':iso(started),'finished_at_utc':iso(ms()),'latest_batches':recent,'history':out,'summary':{'latest_normalized_rows':sum(x.get('rows',0) for x in recent),'latest_failed_batches':sum(x['status']=='FAILED' for x in recent),'history_jobs':len(out),'history_successes':sum(x['status']=='OK' for x in out),'history_failed':sum(x['status']=='FAILED' for x in out),'history_deferred':sum(x['status']=='TIME_BUDGET_DEFERRED' for x in out),'history_normalized_rows':sum(x.get('rows',0) for x in out)}}
  atomic(ROOT/f'datahub-run-{started}.json',report);atomic(ROOT/'datahub-latest.json',{k:v for k,v in report.items() if k not in ['latest_batches','history']});return report['summary']

if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--days',nargs='+',required=True);p.add_argument('--limit',type=int);a=p.parse_args();config=json.loads((FORWARD/'PROTOCOL.json').read_text());symbols=[x['fut'] for x in config['universe']];symbols=symbols[:a.limit] if a.limit else symbols;source=IndependentSources()
 try:print(source.archive_batch(symbols,a.days),flush=True)
 finally:source.s.close()
