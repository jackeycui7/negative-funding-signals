"""Validate trusted model hashes, schemas and public historical-market / synthetic-inventory outputs; no live collection."""
import subprocess,sys,json,math
from package_tools import ROOT,verify_manifest
from jsonschema import Draft202012Validator
n=verify_manifest();schema=json.loads((ROOT/'schemas/OUTPUT_SCHEMA.json').read_text());validator=Draft202012Validator(schema);count=0
for path in sorted((ROOT/'examples').glob('historical-*-input.json')):
 result=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/score.py'),'--input',str(path)],capture_output=True,text=True,check=True,cwd=ROOT);got=json.loads(result.stdout);validator.validate(got)
 expected=json.loads(path.with_name(path.name.replace('-input.json','-output.json')).read_text())
 for key,value in expected['forecasts'].items():
  if value is None:
   if got['forecasts'][key] is not None:raise ValueError('Inapplicable head changed: '+key)
  elif not math.isclose(value,got['forecasts'][key],rel_tol=1e-12,abs_tol=1e-12):raise ValueError('Public fixture frozen-model score mismatch: '+key)
 if not got['research_only'] or got['submission_allowed'] or got['execution_actions']:raise ValueError('Unexpected execution permission')
 count+=1
print(json.dumps({'passed':True,'release_files':n,'public_hybrid_inputs_recomputed':count,'network_used':False,'forward_predictions_created':0}))

subprocess.run([sys.executable,'-B',str(ROOT/'scripts/verify_public_fixtures.py')],check=True,cwd=ROOT)
