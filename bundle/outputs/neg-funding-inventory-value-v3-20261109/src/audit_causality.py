from common import *
from features import build
import copy,types,time

def main():
 start=time.monotonic();import runtime_boot as B
 gate,capq=B.setup();before=loadnp(ROOT/'data/features.npz');hash_before=sha(ROOT/'data/features.npz');cut=hour('2026-07-01');D=copy.copy(B.D);D.arr=[a.copy() for a in B.D.arr]
 for j in range(len(D.arr)):
  D.arr[j][cut:]=np.where(np.isfinite(D.arr[j][cut:]),D.arr[j][cut:]*3+.0001,0.)
 D.oih=B.D.oih.copy();D.oih[cut:]*=5;D._iv=B.D._iv.copy();D._iv[cut:]=1
 proxy=types.SimpleNamespace(D=D,T=B.T,N=B.N,HB=B.HB);d,X,cols,core,eligible,raw,fresh=build(proxy,capq,persist=False);mask=before['hours']<=cut;after=before['hours']>cut;np.testing.assert_allclose(X[mask],before['X'][mask],rtol=0,atol=0,equal_nan=True);np.testing.assert_allclose(core[mask],before['core'][mask],rtol=0,atol=0,equal_nan=True);np.testing.assert_array_equal(eligible[mask],before['eligible'][mask]);assert not np.allclose(X[after],before['X'][after],equal_nan=True);assert sha(ROOT/'data/features.npz')==hash_before
 save(OUT/'CAUSALITY_AUDIT.json',{'created_at':now(),'decision_boundary':stamp(cut),'perturbed_hour_and_later_only':True,'checked_past_rows':int(mask.sum()),'past_feature_difference':0.,'past_quantity_core_difference':0.,'past_eligibility_unchanged':True,'future_positive_control_changed':True,'feature_file_unchanged':True,'scope':'Newly computed features and core from perturbed market arrays; reused base90 carries prior causal audit; cross-source static files not perturbed. Historical received_at not proven by this property.','elapsed_seconds':time.monotonic()-start});print('CAUSALITY_AUDIT_PASSED')
if __name__=='__main__':main()
