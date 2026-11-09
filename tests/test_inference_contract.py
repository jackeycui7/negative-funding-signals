from pathlib import Path
import json,subprocess,sys,tempfile,unittest
from datetime import datetime,timedelta,timezone
ROOT=Path(__file__).resolve().parents[1]
class Interface(unittest.TestCase):
 def reject(self,change):
  request=json.loads((ROOT/'examples/historical-negative-input.json').read_text());change(request)
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'request.json';p.write_text(json.dumps(request));r=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/score.py'),'--input',str(p)],capture_output=True,text=True)
  self.assertEqual(r.returncode,2);result=json.loads(r.stdout);self.assertEqual(result['status'],'INVALID_INPUT');self.assertFalse(result['submission_allowed'])
 def test_intraday_input_cannot_pass_daily_model(self):self.reject(lambda r:r.update(asof_utc='2026-11-05T01:00:00+00:00'))
 def test_feature_name_mismatch_is_not_silently_filled(self):self.reject(lambda r:r['features'].update(unknown_new_feature=1))
 def test_quantity_scenario_must_agree_with_feature(self):self.reject(lambda r:r.update(conditional_arrival_fraction=0.5))
 def test_null_quantity_feature_cannot_bypass_consistency(self):self.reject(lambda r:r['features'].update(conditional_quantity_fraction=None))
 def test_future_observed_snapshot_rejected(self):
  day=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
  self.reject(lambda r:r.update(asof_utc=day.isoformat(),feature_hour_start_utc=(day-timedelta(hours=1)).isoformat(),information_mode='observed_asof_snapshot'))
 def test_duplicate_json_key_rejected(self):
  raw=(ROOT/'examples/historical-negative-input.json').read_text().replace('"request_id":','"request_id":"duplicate", "request_id":',1)
  r=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/score.py')],input=raw,capture_output=True,text=True)
  self.assertEqual(r.returncode,2);self.assertEqual(json.loads(r.stdout)['status'],'INVALID_INPUT')
 def test_nonobject_json_returns_structured_error(self):
  r=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/score.py')],input='[]',capture_output=True,text=True)
  self.assertEqual(r.returncode,2);self.assertEqual(json.loads(r.stdout)['status'],'INVALID_INPUT')
if __name__=='__main__':unittest.main()
