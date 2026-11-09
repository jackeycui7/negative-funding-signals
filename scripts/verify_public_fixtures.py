"""Verify published fixture provenance without loading private inventory."""
from pathlib import Path
import hashlib,json,math
ROOT=Path(__file__).resolve().parents[1]
def main():
 provenance=json.loads((ROOT/'examples/PROVENANCE.json').read_text())
 assert provenance['not_original_private_inventory_scenario']
 for row in provenance['fixtures']:
  p=ROOT/'examples'/row['fixture'];q=p.with_name(p.name.replace('-input.json','-output.json'))
  assert hashlib.sha256(p.read_bytes()).hexdigest()==row['input_sha256']
  assert hashlib.sha256(q.read_bytes()).hexdigest()==row['output_sha256']
  request=json.loads(p.read_text());f=request['features']
  assert request['request_id'].startswith('public-historical-market-synthetic-inventory-')
  assert math.isclose(math.expm1(f['log_received_notional']),10000.,rel_tol=1e-12)
  assert 0<math.expm1(f['log_effective_capacity'])<=10000.00000001
  assert f['conditional_quantity_fraction']==request['conditional_arrival_fraction']==1.
  assert p.read_bytes()==(ROOT/'interface'/p.name).read_bytes()
  assert q.read_bytes()==(ROOT/'interface'/q.name).read_bytes()
 assert (ROOT/'schemas/INPUT_SCHEMA.json').read_bytes()==(ROOT/'interface/INPUT_SCHEMA.json').read_bytes()
 print(json.dumps({'public_hybrid_fixtures_verified':len(provenance['fixtures']),'private_inventory_loaded':False}))
if __name__=='__main__':main()
