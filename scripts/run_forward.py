"""Enter the frozen forward routine in this clone; never enter the author's live workspace."""
from pathlib import Path
import subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
FWD=ROOT/'bundle/outputs/neg-funding-v3-forward-20261109'
RECOVERY=ROOT/'bundle/outputs/neg-funding-v3-source-recovery-20261109'
if not (FWD/'RUNTIME_BINDING.json').exists() or not (RECOVERY/'SOURCE_BINDING.json').exists():
 raise SystemExit('Run scripts/bootstrap_forward.py with authorized, matching assets first')
raise SystemExit(subprocess.call([sys.executable,'-B',str(RECOVERY/'run_sources_once.py'),*sys.argv[1:]],cwd=ROOT))
