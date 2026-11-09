import sys,unittest,json,tempfile,sqlite3,threading
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import independent_sources as sources
from independent_sources import normalize_datahub,H

class SourceContract(unittest.TestCase):
 def bar(self):return {'open_time_ms':10*H,'interval':'1h','open':'1','high':'2','low':'.5','close':'1.5','volume':'10','quote_volume':'15','complete':True,'incomplete_reason':None,'finalized_at_ms':11*H+500}
 def test_closed_bar_native_slots(self):
  t,x=normalize_datahub('spot',self.bar(),12*H);self.assertEqual(t,10*H);self.assertEqual(x[4],'1.5');self.assertEqual(x[7],'15');self.assertEqual(x[6],11*H-1)
 def test_unfinished_hour_rejected(self):
  with self.assertRaisesRegex(ValueError,'UNFINISHED'):normalize_datahub('spot',self.bar(),10*H+1000)
 def test_incomplete_source_rejected(self):
  r=self.bar();r['complete']=False
  with self.assertRaisesRegex(ValueError,'SOURCE_INCOMPLETE'):normalize_datahub('perp',r,12*H)
 def test_null_volume_not_fabricated(self):
  r=self.bar();r['quote_volume']=None
  with self.assertRaisesRegex(ValueError,'NULL_TRADE_VOLUME'):normalize_datahub('spot',r,12*H)
 def test_premium_undefined_volume_stays_null(self):
  r=self.bar();r['volume']=None;r['quote_volume']=None;t,x=normalize_datahub('premium',r,12*H);self.assertIsNone(x[5]);self.assertIsNone(x[7]);self.assertEqual(x[4],'1.5')
 def test_future_revision_rejected(self):
  r=self.bar();r['finalized_at_ms']=13*H
  with self.assertRaisesRegex(ValueError,'FUTURE_FINALIZATION'):normalize_datahub('perp',r,12*H)
 def test_native_funding_timestamp_and_sign(self):
  r={'rate_type':'regular','source':'binance_funding_rate','period_end_ms':10*H,'funding_ts_ms':10*H+1,'rate':'-0.001','interval_hours':1,'recv_ts_ms':10*H+100};t,x=normalize_datahub('funding',r,12*H);self.assertEqual(t,10*H+1);self.assertEqual(x['fundingRate'],'-0.001');self.assertEqual(x['_provider_interval_hours'],1)
 def test_predicted_funding_not_accepted(self):
  r={'rate_type':'regular','source':'predicted','funding_ts_ms':H,'rate':'-.001'}
  with self.assertRaisesRegex(ValueError,'WRONG_FUNDING_SOURCE'):normalize_datahub('funding',r,12*H)
 def test_special_settlement_quarantined(self):
  with self.assertRaisesRegex(ValueError,'SPECIAL_SETTLEMENT'):normalize_datahub('funding',{'rate_type':'special'},12*H)
 def test_oi_quote_units_required(self):
  with self.assertRaisesRegex(ValueError,'UNIT_MISMATCH'):normalize_datahub('oi',{'period':'5m'},12*H,{'open_interest_value':'base'})
 def test_oi_null_not_estimated_from_price(self):
  with self.assertRaisesRegex(ValueError,'NULL_OI'):normalize_datahub('oi',{'period':'5m','open_interest_value':None},12*H,{'open_interest_value':'quote'})
 def test_native_oi_value_preserved(self):
  t,x=normalize_datahub('oi',{'period':'5m','time_ms':H,'open_interest_value':'123456.789','open_interest':'100','recv_ms':H+500},12*H,{'open_interest_value':'quote'});self.assertEqual(x['sumOpenInterestValue'],'123456.789');self.assertEqual(t,H-300000);self.assertEqual(x['_provider_period_end_ms'],H)

class RecoveryBehavior(unittest.TestCase):
 def test_archive_blank_is_missing_not_zero_or_previous_value(self):
  self.assertEqual(sources.archive_number(''),'nan');self.assertEqual(sources.archive_number(None),'nan');self.assertEqual(sources.archive_number('0'),'0');self.assertEqual(sources.archive_number('123.4500'),'123.4500')
 def test_unknown_instrument_does_not_drop_valid_batch_members(self):
  source=sources.Datahub.__new__(sources.Datahub);source.s=type('Store',(),{'append':lambda *args:None})();written=[]
  source.ingest=lambda kind,sym,data,receipt,units=None:(written.append((kind,sym)) or (len(data),0))
  def page(path,params):
   ids=[v for k,v in params if k=='instrument']
   if 'binance:AERGOUSDT' in ids:raise sources.ProviderHTTPError('datahub',404,json.dumps({'error':{'code':'unknown_instrument','message':'unknown instrument binance:AERGOUSDT'}}).encode(),{'received_at_ms':123},'HTTP404')
   return {'data':[{'data':{'instrument_id':iid}} for iid in ids]},{'received_at_ms':123}
  source.page=page
  result=source.latest([{'fut':'BTCUSDT','spot':'BTCUSDT'},{'fut':'AERGOUSDT','spot':'AERGOUSDT'}])
  self.assertFalse(any(x['status']=='FAILED' for x in result));self.assertEqual({kind for kind,sym in written if sym=='BTCUSDT'},{'spot','perp','premium','funding'});self.assertTrue(any('binance:AERGOUSDT' in x['missing_instruments'] for x in result))
 def test_empty_success_is_not_a_completed_history_gap(self):
  self.assertFalse(sources.history_terminal(0,0,[]));self.assertFalse(sources.history_terminal(3,1,[]));self.assertTrue(sources.history_terminal(3,0,[]))
 def test_cross_origin_redirect_cannot_forward_authorization(self):
  import urllib.request
  request=urllib.request.Request('https://datahub.aurabitcapital.space/v1/funding',headers={'Authorization':'Bearer test-placeholder'})
  with self.assertRaisesRegex(ValueError,'CROSS_ORIGIN'):sources.SameOriginRedirect().redirect_request(request,None,302,'',{},'https://another.example/v1/funding')
 def test_deferred_gap_survives_latest_snapshot_and_next_cycle(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'PROTOCOL.json').write_text(json.dumps({'universe':[{'fut':'BTCUSDT','spot':'BTCUSDT'}]}))
   db=sqlite3.connect(':memory:',check_same_thread=False,isolation_level=None)
   db.execute('CREATE TABLE records(kind,symbol,event_ms,received_ms,payload)')
   fake=type('S',(),{'db':db,'lock':threading.RLock()})();source=sources.Datahub.__new__(sources.Datahub);source.s=fake
   def latest(universe):
    self.assertGreater(db.execute('SELECT COUNT(*) FROM independent_history_queue WHERE state="PENDING"').fetchone()[0],0)
    db.execute('INSERT INTO records VALUES(?,?,?,?,?)',('perp','BTCUSDT',sources.ms()//H*H-H,sources.ms(),'{}'))
    return []
   source.latest=latest
   with patch.object(sources,'ROOT',root),patch.object(sources,'FORWARD',root):
    first=source.collect(seconds=0);self.assertEqual(first['history_deferred'],5)
    second=source.collect(seconds=0);self.assertEqual(second['history_deferred'],5)
   self.assertEqual(db.execute('SELECT COUNT(DISTINCT kind) FROM independent_history_queue WHERE state="PENDING"').fetchone()[0],5);db.close()
if __name__=='__main__':unittest.main()
