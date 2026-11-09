"""Use the frozen engine; route all scratch writes into this research directory."""
from common import *
PROFILE=json.loads((ONLINE/'runtime/MODEL_PROFILE.json').read_text());P=PROFILE['profile'];RESEARCH=P['historical_replay_profile']
os.environ.update(NFB_DATA=str(MARKET),NFB_DATA_DIR=str(MARKET),NFB_DATA_START='2025-07-01',NFB_DATA_END='2026-11-08',NFB_CAP_FILE=str(CAPS),NFB_ROOT=str(ROOT/'data/scratch'),NFB_OUT=str(ROOT/'data/scratch')+'/',NFB_DAILY=str(ROOT/'data/scratch/daily')+'/',NFB_PHASE1_ROOT=str(ROOT),NFB_S='10000000',NFB_DERISK='2')
sys.path.insert(0,str(FROZEN/'repro/lib'));sys.path.insert(0,str(FROZEN/'research'))
import v13lib as V,run_r7 as RR,r7_lib as R7,run_adapt as RA,run_signals as RS
import engine_phase1 as XE,harness_phase1 as HB
from causal_inputs import causal_sigma
D=RR.D;T=len(D.arr[0]);N=D.N
def setup():
 HB.E=XE;HB.mkp=XE.mkp;HB.MKO=V._ns['MKO'];HB.MKO.clear();HB.MKO.update({k:float(v) for k,v in RESEARCH['fees'].items()})
 def run(*a,**kw):kw['same_hour']=False;kw['dl_stop']=True;return HB.run(*a,**kw)
 RR.run=run;D.oi_cap_fraction=float(P['oi_cap_fraction']);D.entry_score=None
 D._sg=causal_sigma(D.arr[1]);R7.SIGD=D._sg;RR.SIGD=D._sg
 with np.load(MARKET/'ds/dataset.npz') as z:D._iv=z['ivh'].copy()
 registry=json.loads((FROZEN/'research/lifecycle_events.json').read_text());D.dl_exit=D.dl_exit.copy();D.dl_fin=D.dl_fin.copy()
 for ev in registry['events']:
  for sym in ev['symbols']:
   if sym in D.fut:
    n=D.fut.index(sym);D.dl_exit[n]=hour(ev['available_for_hourly_decision_utc']);D.dl_fin[n]=hour(ev['futures_delivery_utc'])
 # Preserve the frozen cost tables used in both income gate and fills.
 # Changing sigma affects realized impact and gate, as in the existing causal runner.
 income=R7.exp_income(True).copy()
 gate=~RS.ADL_MASK&np.isfinite(income)&(income>=float(P['income_cost_multiple'])*R7.entry_cost(RR.YK,RR.HM))
 qty=pd.read_csv(CAPS).set_index('fut_symbol').cap_qty_token
 capq=np.array([qty.get(s,0.) for s in D.fut])
 return gate,capq
