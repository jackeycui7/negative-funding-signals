from independent_sources import *
from decimal import Decimal

def validate():
 c=sqlite3.connect(FORWARD/'data/market.sqlite');symbols=['BTCUSDT','1000PEPEUSDT','1000FLOKIUSDT','GRTUSDT'];details=[];mismatch=[]
 for symbol in symbols:
  for kind in ['spot','perp','premium','funding']:
   original={int(t):json.loads(p) for t,p in c.execute("SELECT o.event_ms,o.payload FROM records o JOIN requests r ON r.id=o.request_id WHERE o.kind=? AND o.symbol=? AND r.venue IN ('binance_futures','binance_spot','binance_public_archive') ORDER BY o.received_ms",(kind,symbol))}
   if symbol=='BTCUSDT' and kind=='funding':
    probe=json.loads((FORWARD/'data/connector-funding-probe.json').read_text())['structuredContent']['result'];original.update({int(x['fundingTime']):x for x in probe})
   new={int(t):json.loads(p) for t,p in c.execute("SELECT o.event_ms,o.payload FROM records o JOIN requests r ON r.id=o.request_id WHERE o.kind=? AND o.symbol=? AND r.venue='aurabit_datahub' ORDER BY o.received_ms",(kind,symbol))}
   common=sorted(set(original)&set(new));fields=[4,7] if kind in ['spot','perp'] else [4] if kind=='premium' else ['fundingRate'];count=0
   for t in common:
    for field in fields:
     a,b=original[t][field],new[t][field]
     if a is None or b is None or Decimal(str(a))!=Decimal(str(b)):mismatch.append({'kind':kind,'symbol':symbol,'event_ms':t,'field':field,'original':a,'provider':b})
     count+=1
   details.append({'symbol':symbol,'kind':kind,'overlap_rows':len(common),'compared_values':count})
 result={'at_utc':iso(ms()),'representative_symbols':symbols,'compared_values':sum(x['compared_values'] for x in details),'overlap_rows':sum(x['overlap_rows'] for x in details),'mismatch_count':len(mismatch),'mismatches':mismatch[:30],'details':details,'passed':not mismatch and all(x['overlap_rows']>0 for x in details),'all339pairs_not_claimed_exhaustively_crossverified':True};atomic(ROOT/'OVERLAP_VALIDATION.json',result);c.close();return result
if __name__=='__main__':print(json.dumps(validate(),ensure_ascii=False))
