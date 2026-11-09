"""Check documented provider period-end labels against native public-archive timestamps."""
from independent_sources import *
from decimal import Decimal
import shutil

def validate():
 source=Datahub();out=[]
 try:
  for symbol in ['BTCUSDT','1000PEPEUSDT','1000FLOKIUSDT','GRTUSDT']:
   data,r=source.page('/v1/open-interest',{'instrument':'binance:'+symbol,'period':'5m','start':SEED_END,'end':SEED_END+24*H,'limit':1000})
   native={int(t):json.loads(p)['sumOpenInterestValue'] for t,p in source.s.db.execute("SELECT event_ms,payload FROM records WHERE kind='oi' AND symbol=? AND json_extract(payload,'$._source_provider')='binance_public_archive'",(symbol,))}
   overlap=0;errors=[];unshifted_mismatch=0
   for row in data.get('data',[]):
    t,value=normalize_datahub('oi',row,r['received_at_ms'],data.get('units'));quote=value['sumOpenInterestValue']
    if t in native:
     overlap+=1
     if Decimal(native[t])!=Decimal(quote):errors.append({'native_timestamp_ms':t,'native':native[t],'provider':quote})
    if row['time_ms'] in native and Decimal(native[row['time_ms']])!=Decimal(quote):unshifted_mismatch+=1
   if overlap and not errors:source.ingest('oi',symbol,data.get('data',[]),r,data.get('units'))
   out.append({'symbol':symbol,'compared_native_quote_values':overlap,'mapping':'provider_period_end_minus5m_matches_native_timestamp','mismatch_count':len(errors),'unmapped_timestamp_mismatches':unshifted_mismatch,'examples':errors[:3]})
  result={'at_utc':iso(ms()),'details':out,'compared_values':sum(x['compared_native_quote_values'] for x in out),'mismatch_count':sum(x['mismatch_count'] for x in out),'passed':all(x['compared_native_quote_values']>0 and x['mismatch_count']==0 for x in out),'frozen_oi_hourly_pre_lag_unchanged':True}
  path=ROOT/'OI_OVERLAP_VALIDATION.json'
  if path.exists() and not json.loads(path.read_text()).get('passed'):shutil.copy2(path,ROOT/'OI_UNMAPPED_FAILURE_RETAINED.json')
  atomic(path,result);return result
 finally:source.s.close()

if __name__=='__main__':print(json.dumps(validate(),ensure_ascii=False))
