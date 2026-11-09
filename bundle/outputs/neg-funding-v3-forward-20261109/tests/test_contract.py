"""Public-seam behavior checks; synthetic records never enter the live ledger."""
import sys,unittest,tempfile,json,sqlite3
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from common import *
from ledger import Ledger
from collect import normalize
from public_store import Store,Cooldown

class Contract(unittest.TestCase):
 def fixture(self,d,asof,probability=.6):
  raw=Path(d)/'source.json';raw.write_text('{}');evidence={'source_file_hashes':{str(raw):sha(raw)},'received_at_utc':iso(asof-1)}
  row={'request':{'request_id':str(asof),'symbol':'BTCUSDT','information_mode':'observed_asof_snapshot'},'prediction':{'request_id':str(asof),'symbol':'BTCUSDT','asof_utc':iso(asof),'model_version':'frozen','research_only':True,'submission_allowed':False,'data_quality':{'model_stale':False,'snapshot_stale':False},'status':'WATCH_ONLY','conditional_arrival_fraction':1.,'forecasts':{'p_new_negative_within72h':probability,'p_no_raw24_exit_next168h':None,'p_qualified_entry_after72h_within7d':None,'conditional_30d_reference_net_usdt':0}}}
  protocol={'activation_ms':0,'version':'frozen','universe':[{'fut':'BTCUSDT'},{'fut':'ETHUSDT'}],'diagnostic_probability_threshold':.5};return row,evidence,protocol
 def test_atomic_cohort_and_missing_coverage(self):
  with tempfile.TemporaryDirectory() as d:
   log=Ledger(Path(d)/'log.sqlite');r,e,p=self.fixture(d,86400000);self.assertTrue(log.record(86400000,[r],e,p,now=86400001));self.assertEqual(log.db.execute('SELECT COUNT(*) FROM coverage').fetchone()[0],2);self.assertFalse(log.record(86400000,[r],e,p,now=86400001));self.assertEqual(log.db.execute('SELECT COUNT(*) FROM forecasts').fetchone()[0],1);log.close()
 def test_diagnostic_probability_fixed(self):
  with tempfile.TemporaryDirectory() as d:
   log=Ledger(Path(d)/'log.sqlite');r,e,p=self.fixture(d,86400000,.49);log.record(86400000,[r],e,p,now=86400001);self.assertEqual(log.db.execute('SELECT COUNT(*) FROM alerts').fetchone()[0],0);log.close()
 def test_72hour_coin_cooldown(self):
  with tempfile.TemporaryDirectory() as d:
   log=Ledger(Path(d)/'log.sqlite')
   for t in [86400000,2*86400000,4*86400000]:
    r,e,p=self.fixture(d,t);log.record(t,[r],e,p,now=t+1)
   self.assertEqual([r[0] for r in log.db.execute('SELECT status FROM alerts ORDER BY asof_ms')],['SELECTED','COOLDOWN','SELECTED']);log.close()
 def test_tampered_raw_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   log=Ledger(Path(d)/'log.sqlite');r,e,p=self.fixture(d,86400000);Path(d,'source.json').write_text('{"changed":1}')
   with self.assertRaisesRegex(ValueError,'HASH_MISMATCH'):log.record(86400000,[r],e,p,now=86400001)
   self.assertEqual(log.db.execute('SELECT COUNT(*) FROM forecasts').fetchone()[0],0);log.close()
 def test_future_receive_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   log=Ledger(Path(d)/'log.sqlite');r,e,p=self.fixture(d,86400000);e['received_at_utc']=iso(86400002)
   with self.assertRaisesRegex(ValueError,'FUTURE_RECEIPT'):log.record(86400000,[r],e,p,now=86400001)
   log.close()
 def test_historical_test_cannot_become_forward(self):
  with tempfile.TemporaryDirectory() as d:
   log=Ledger(Path(d)/'log.sqlite');r,e,p=self.fixture(d,86400000);r['request']['information_mode']='historical_hourly_proxy'
   with self.assertRaisesRegex(ValueError,'RECEIVE_PROOF'):log.record(86400000,[r],e,p,now=86400001)
   log.close()
 def test_no_backdating(self):
  with tempfile.TemporaryDirectory() as d:
   log=Ledger(Path(d)/'log.sqlite')
   for t in [86400000-1,86400000+300000]:
    with self.assertRaisesRegex(ValueError,'NO_BACKDATING'):log.record(86400000,[],{}, {'activation_ms':0},now=t)
   self.assertEqual(log.db.execute('SELECT COUNT(*) FROM forecasts').fetchone()[0],0);log.close()
 def test_no_pred_before_activation(self):
  with tempfile.TemporaryDirectory() as d:
   log=Ledger(Path(d)/'log.sqlite')
   with self.assertRaisesRegex(ValueError,'PRECEDES_ACTIVATION'):log.record(86400000,[],{}, {'activation_ms':86400001},now=86400001)
   log.close()
 def test_public_get_allowlist(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(Path(d))
   with self.assertRaises(ValueError):s.get('binance_futures','/fapi/v1/order')
   self.assertEqual(s.db.execute('SELECT COUNT(*) FROM requests').fetchone()[0],0);s.close()
 def test_cooldown_not_bypassed(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(Path(d));s.db.execute('INSERT INTO cooldown VALUES(?,?,?)',('binance_futures',ms()+H,'HTTP_403'))
   with self.assertRaises(Cooldown):s.get('binance_futures','/fapi/v1/fundingRate')
   self.assertEqual(s.db.execute('SELECT COUNT(*) FROM requests').fetchone()[0],0);s.close()
 def test_immutable_source_revisions(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(Path(d));r={'received_at_ms':10,'request_id':1};s.append('funding','BTCUSDT',1,{'rate':-.001},r);s.append('funding','BTCUSDT',1,{'rate':-.001},{'received_at_ms':20,'request_id':2});s.append('funding','BTCUSDT',1,{'rate':-.002},{'received_at_ms':30,'request_id':3})
   self.assertEqual(len(s.records()),2);self.assertEqual(len(s.records(received_before=15)),1);self.assertEqual(s.records(received_before=15)[0][3],10);s.close()
 def test_closed_hour_only(self):
  a=[0,0,0,0,1,0,H-1,10];b=[H,0,0,0,9999,0,2*H-1,10]
  self.assertEqual(normalize('spot',[a,b],H-1),[(0,a)])
 def test_funding_preserves_zero(self):
  a={'fundingTime':1,'fundingRate':'0'};self.assertEqual(normalize('funding',[a],1),[(1,a)])
 def test_empty_metrics_no_fabrication(self):self.assertEqual(normalize('oi',[],100),[])
 def test_grid_idempotency(self):
  with tempfile.TemporaryDirectory() as d:
   log=Ledger(Path(d)/'log.sqlite');log.grid(86400000,'MISSED_FIXED_GRID',{});log.grid(86400000,'ISSUED',{});self.assertEqual(log.db.execute('SELECT status FROM grids').fetchone()[0],'MISSED_FIXED_GRID');log.close()
 def test_censored_is_not_failure(self):
  with tempfile.TemporaryDirectory() as d:
   log=Ledger(Path(d)/'log.sqlite');x={'prediction_id':'x','head':'p_new_negative_within72h','outcome':None,'evaluation_status':'MISSING_OR_CENSORED'};log.db.execute('INSERT INTO outcomes VALUES(?,?,?,?,?)',('x',x['head'],'h',1,json.dumps(x)));m=log.metrics()['heads'][x['head']];self.assertEqual(m['verified'],0);self.assertIsNone(m['hit_rate']);log.close()

if __name__=='__main__':unittest.main()
