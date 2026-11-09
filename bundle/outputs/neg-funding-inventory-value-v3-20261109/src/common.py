import os,sys
sys.dont_write_bytecode=True
for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']:os.environ[k]='4'
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results'
PHASE2=ROOT.parent/'neg-funding-strategy-phase2-20261107'
ONLINE=ROOT.parent/'neg-funding-strategy-online-20261108'
FROZEN=ONLINE/'frozen_reference'
MARKET=ROOT.parent/'neg-funding-empirical-calibration-20261109/data'
CAPS=ROOT.parent.parent/'neg-funding-strategy-v1/private/inventory_caps.csv'
ORIGIN=pd.Timestamp('2025-07-01',tz='UTC')
def hour(x):
 p=pd.Timestamp(x);p=p.tz_localize('UTC') if p.tzinfo is None else p.tz_convert('UTC')
 return int((p-ORIGIN).total_seconds()//3600)
def stamp(t):return (ORIGIN+pd.Timedelta(hours=int(t))).isoformat()
def now():return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def clean(x):
 if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
 if isinstance(x,(tuple,list,np.ndarray)):return [clean(v) for v in x]
 if isinstance(x,(np.integer,)):return int(x)
 if isinstance(x,(np.bool_,)):return bool(x)
 if isinstance(x,(float,np.floating)):return float(x) if np.isfinite(x) else None
 return x
def save(p,x):Path(p).write_text(json.dumps(clean(x),ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def log(action,**kw):
 with (ROOT/'experiment-log.jsonl').open('a') as f:f.write(json.dumps(clean(dict(at=now(),action=action,**kw)),ensure_ascii=False)+'\n')
def loadnp(p):
 with np.load(p) as z:return {k:z[k] for k in z.files}
