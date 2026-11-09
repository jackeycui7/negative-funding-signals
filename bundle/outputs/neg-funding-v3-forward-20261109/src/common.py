from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,sys,os
sys.dont_write_bytecode=True
for key in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']:os.environ.setdefault(key,'4')
ROOT=Path(__file__).resolve().parents[1]
OUTPUTS=ROOT.parent
V3=OUTPUTS/'neg-funding-inventory-value-v3-20261109'
PHASE2=OUTPUTS/'neg-funding-strategy-phase2-20261107'
H=3600000;ORIGIN=1751328000000
def ms():return int(datetime.now(timezone.utc).timestamp()*1000)
def iso(t):return datetime.fromtimestamp(t/1000,timezone.utc).isoformat()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def atomic(path,obj):
    path=Path(path);temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n');temp.replace(path)
def immutable(path,obj):
    with Path(path).open('x') as f:f.write(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
