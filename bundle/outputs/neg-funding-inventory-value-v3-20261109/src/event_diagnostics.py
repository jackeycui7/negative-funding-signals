from common import *
from features import SOURCE

def selected(g):
 last={};rows=[];perday={}
 for row in g.sort_values(['hour','prediction'],ascending=[True,False],kind='stable').itertuples():
  t=int(row.hour)
  if t-last.get(row.symbol,-100000)<72 or perday.get(t,0)>=10:continue
  last[row.symbol]=t;perday[t]=perday.get(t,0)+1;rows.append(row._asdict())
 return pd.DataFrame(rows)

def main():
 pred=pd.read_csv(OUT/'event_predictions.csv');f=loadnp(ROOT/'data/features.npz');d=loadnp(SOURCE/'data/daily_samples.npz');symbols=f['symbols'].tolist();lookup={s:n for n,s in enumerate(symbols)};row_lookup={(int(t),int(n)):j for j,(t,n) in enumerate(zip(f['hours'],f['symbol_id']))}
 with np.load(MARKET/'ds/dataset.npz') as z:iv=z['ivh'];rate=z['r8'];ev=z['ev']
 T=len(rate);items=[];records=[]
 for method,g in pred[(pred.task=='new_negative_72h')&(pred.month<=10)].groupby('method'):
  alert=selected(g);detail=[]
  for row in alert.itertuples():
   t,n=int(row.hour),lookup[row.symbol];j=row_lookup[(t,n)];stop=min(t+72,T);neg=np.flatnonzero((iv[t:stop,n]>0)&(ev[t:stop,n]<0));first=int(neg[0]) if len(neg) else np.nan;deep=bool(((iv[t:stop,n]>0)&(rate[t:stop,n]<-.001)).any());detail.append(dict(method=method,hour=t,symbol=row.symbol,y=row.y,observed=row.observed,turn_delay_h=first,deep_turn_within72h=deep,known_arrival_entry7d=d['y_arrival'][j],latest_rate_bp=float(f['X'][j,0]),rate_absolute_bp=float(abs(f['X'][j,0]))))
  dd=pd.DataFrame(detail);ok=dd[dd.observed];hit=ok[ok.y==1];arr=dd[np.isfinite(dd.known_arrival_entry7d)];items.append({'method':method,'alerts':len(dd),'observed':len(ok),'hits':int(ok.y.sum()),'base_rate_all_current_nonnegative':float(g[g.observed].y.mean()),'ordinary_turn_precision':float(ok.y.mean()),'median_turn_delay_h_hits':float(hit.turn_delay_h.median()),'fraction_hits_turn_before_inventory_arrives72h':float((hit.turn_delay_h<72).mean()),'deep_turn_within72h_fraction_all_alerts':float(dd.deep_turn_within72h.mean()),'arrival7d_entry_observed':len(arr),'arrival7d_entry_hits':int(arr.known_arrival_entry7d.sum()),'arrival7d_qualifying_entry_fraction':float(arr.known_arrival_entry7d.mean()),'median_latest_nonnegative_rate_bp':float(dd.latest_rate_bp.median()),'half_of_alerts_have_current_rate_below_bp':float(dd.latest_rate_bp.median()),'not_trade_profitability':True});records.append(dd)
 pd.concat(records).to_csv(OUT/'turn_alerts_with_arrival_outcomes.csv',index=False);save(OUT/'TURN_VS_BORROW_VALUE.json',{'created_at':now(),'summary':items,'interpretation':'A single negative settlement can be shallow/short. A turn within72h will occur before a72h delivery. The existing frozen cost+rate+basis opportunity gate after arrival is a separate target, still not a profit guarantee.'});print(json.dumps(clean(items)),flush=True)
if __name__=='__main__':main()
