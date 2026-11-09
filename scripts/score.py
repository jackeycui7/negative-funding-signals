"""Load only the hash-verified frozen models and score a supplied125-feature request."""
from pathlib import Path
import argparse,json,sys,hashlib
from datetime import datetime,timezone
from jsonschema import Draft202012Validator,ValidationError
ROOT=Path(__file__).resolve().parents[1]
CANDIDATE=ROOT/'bundle/outputs/neg-funding-inventory-value-v3-20261109'
def check_models():
 for rel,expected in json.loads((ROOT/'CURRENT_RELEASE.json').read_text())['frozen_bindings'].items():
  if hashlib.sha256((CANDIDATE/rel).read_bytes()).hexdigest()!=expected:raise ValueError('FROZEN_MODEL_HASH_MISMATCH:'+rel)
def main():
 p=argparse.ArgumentParser();p.add_argument('--input');p.add_argument('--output');args=p.parse_args()
 check_models();sys.path.insert(0,str(CANDIDATE/'src'))
 from signal_cli import score,InputError,parse_time
 from common import clean
 try:
  def unique_object(pairs):
   obj={}
   for key,value in pairs:
    if key in obj:raise InputError('Duplicate JSON key: '+key)
    obj[key]=value
   return obj
  def nonfinite(value):raise InputError('Non-finite JSON constant: '+value)
  text=Path(args.input).read_text() if args.input else sys.stdin.read()
  request=json.loads(text,object_pairs_hook=unique_object,parse_constant=nonfinite)
  Draft202012Validator(json.loads((ROOT/'schemas/INPUT_SCHEMA.json').read_text())).validate(request)
  if request['features']['conditional_quantity_fraction'] is None:raise InputError('Conditional quantity feature is required')
  if parse_time(request['asof_utc'])>datetime.now(timezone.utc):raise InputError('Snapshot is in the future')
  result=clean(score(request));code=0
 except (InputError,KeyError,json.JSONDecodeError,ValidationError) as e:result={'schema_version':'nfb.signal-output.v3','status':'INVALID_INPUT','submission_allowed':False,'error':e.message if isinstance(e,ValidationError) else str(e)};code=2
 text=json.dumps(result,ensure_ascii=False,allow_nan=False)
 if args.output:Path(args.output).write_text(text+'\n')
 print(text);return code
if __name__=='__main__':raise SystemExit(main())
