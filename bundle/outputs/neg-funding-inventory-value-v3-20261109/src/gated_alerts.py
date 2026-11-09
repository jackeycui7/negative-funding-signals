from common import *
from features import SOURCE
from event_diagnostics import selected

def main():
 p=pd.read_csv(OUT/'event_predictions.csv');f=loadnp(ROOT/'data/features.npz');lookup={(int(t),str(f['symbols'][int(n)])):i for i,(t,n) in enumerate(zip(f['hours'],f['symbol_id']))};result=[]
 for task in ['new_negative_72h','survival_168h','arrival_entry_7d']:
  for method in ['fixed_HGB_full','fixed_HGB_base90','EMA72_calibrated']:
   g=p[(p.task==task)&(p.method==method)&(p.month<=10)]
   for scope in (['all_currently_eligible','currently_nonnegative'] if task=='arrival_entry_7d' else ['all_currently_eligible']):
    if scope=='currently_nonnegative':
     ii=np.array([lookup[(int(t),s)] for t,s in zip(g.hour,g.symbol)]);gg=g.loc[f['X'][ii,0]>=0]
    else:gg=g
    a=selected(gg[gg.prediction>=.5]);o=a[a.observed] if len(a) else a;result.append({'task':task,'method':method,'pool':scope,'fixed_probability_gate':.5,'alerts':len(a),'observed':len(o),'unknown':len(a)-len(o),'hits':int(o.y.sum()) if len(o) else 0,'precision_observed':float(o.y.mean()) if len(o) else None,'days_with_no_alerts':245-len(a.hour.unique()) if len(a) else 245,'warning':'Exploratory policy diagnostic, not an adopted borrow/execution rule; probabilities calibrated on preceding60days only.'})
 save(OUT/'FIXED_05_GATE_DIAGNOSTIC.json',{'created_at':now(),'summary':result,'event_outcomes_overlap_not_independent_trials':True});print(json.dumps(clean(result)))
if __name__=='__main__':main()
