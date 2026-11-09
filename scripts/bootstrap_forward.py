"""Hash-preserving path relocation into this clone; does not modify source assets or model bytes."""
from pathlib import Path
import argparse,json,sys,hashlib,datetime,os
ROOT=Path(__file__).resolve().parents[1];BUNDLE=ROOT/'bundle'
PREFIX='/Users/leslie/Documents/同花顺/'
FWD=BUNDLE/'outputs/neg-funding-v3-forward-20261109'
RECOVERY=BUNDLE/'outputs/neg-funding-v3-source-recovery-20261109'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def relative(old):
 if not old.startswith(PREFIX):raise ValueError('Unrecognized original source root')
 return old[len(PREFIX):]
def main():
 p=argparse.ArgumentParser();p.add_argument('--asset-root',required=True,type=Path);a=p.parse_args();assets=a.asset_root.expanduser().resolve();resolved={};missing=[]
 originals=json.loads((ROOT/'provenance/RUNTIME_BINDING.original.json').read_text())
 for old,wanted in originals.items():
  rel=relative(old);local=BUNDLE/rel;source=local if local.exists() else assets/rel
  if not source.is_file():missing.append({'path':rel,'reason':'MISSING'})
  elif sha(source)!=wanted:missing.append({'path':rel,'reason':'SHA256_MISMATCH'})
  else:resolved[rel]=(local,source,wanted)
 if missing:print(json.dumps({'status':'EXTERNAL_ASSETS_REQUIRED','missing':missing},ensure_ascii=False));return 2
 # All assets are verified before any path or binding is created.
 for rel,(local,source,wanted) in resolved.items():
  if not local.exists():local.parent.mkdir(parents=True,exist_ok=True);local.symlink_to(source)
 new={str(BUNDLE/relative(old)):wanted for old,wanted in originals.items()}
 for path in [FWD/'data/raw',FWD/'data/state',FWD/'data/runs',FWD/'data/features']:path.mkdir(parents=True,exist_ok=True)
 generated=FWD/'RUNTIME_BINDING.json';body=json.dumps(new,ensure_ascii=False,indent=2)+'\n'
 if generated.exists() and generated.read_text()!=body:raise ValueError('Existing local binding differs; keep evidence and use a new clone')
 generated.write_text(body)
 recovery_original=json.loads((ROOT/'provenance/SOURCE_BINDING.original.json').read_text());source_binding={str(BUNDLE/relative(old)):wanted for old,wanted in recovery_original.items()}
 for file,wanted in source_binding.items():
  if sha(Path(file))!=wanted:raise ValueError('SOURCE_ADAPTER_HASH_MISMATCH:'+file)
 dest=RECOVERY/'SOURCE_BINDING.json';body=json.dumps(source_binding,ensure_ascii=False,indent=2)+'\n'
 if dest.exists() and dest.read_text()!=body:raise ValueError('Existing source binding differs')
 dest.write_text(body)
 environment=BUNDLE/'outputs/neg-funding-strategy-phase2-20261107/forward_validation_v2_20261107/.venv';environment.parent.mkdir(parents=True,exist_ok=True)
 # Link the complete environment: resolving only its python binary loses venv site-packages.
 if not environment.exists():environment.symlink_to(Path(sys.prefix).resolve(),target_is_directory=True)
 elif not environment.is_symlink() or environment.resolve()!=Path(sys.prefix).resolve():raise ValueError('Existing Python environment differs; preserve it and bootstrap a new clone')
 marker={'bootstrapped_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'original_files_verified':len(new),'source_adapter_files_verified':len(source_binding),'expected_hashes_changed':False,'old_ledgers_imported':False,'assets_root':str(assets)}
 (BUNDLE/'LOCAL_BOOTSTRAP.json').write_text(json.dumps(marker,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'status':'READY','files_verified':len(new),'source_files_verified':len(source_binding),'ledger':'NEW_EMPTY_UNLESS_THIS_CLONE_PREVIOUSLY_COLLECTED'}));return 0
if __name__=='__main__':raise SystemExit(main())
