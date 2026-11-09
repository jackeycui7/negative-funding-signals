"""Past-only cash flow features and strict exit-lock outcome definitions."""
import numpy as np
import pandas as pd

UNIT=1e-8

def rolling(a,h):
    if h>len(a):return np.zeros_like(a)
    prefix=np.vstack([np.zeros((1,a.shape[1]),dtype=a.dtype),np.cumsum(a,axis=0,dtype=a.dtype)])
    out=prefix[h:]-prefix[:-h]
    return np.vstack([np.zeros((h-1,a.shape[1]),dtype=a.dtype),out])

def cash_state(events,intervals,fresh):
    settled=intervals>0
    valid=~settled|np.isfinite(events)
    values=events[settled&np.isfinite(events)]
    if len(values) and np.max(np.abs(values/UNIT-np.rint(values/UNIT)))>1e-6:
        raise ValueError('Funding precision exceeds audited 1e-8 integer units')
    payments=np.where(settled&np.isfinite(events),events,0.)
    units=np.rint(payments/UNIT).astype(np.int64)
    known=rolling((fresh&valid).astype(np.int64),24)==24
    known[:23]=False
    balance=rolling(units,24)
    age=np.zeros_like(payments)
    for q in range(len(events)):
        prior=age[q-1] if q else np.zeros(events.shape[1])
        age[q]=np.where(known[q]&(balance[q]<=0),np.minimum(prior+1,720),0)
    return dict(units=units,balance=balance,known=known,age=age,settled=settled)

def raw_features(state,fresh,hours,ids):
    u,b,k=state['units'],state['balance'],state['known'];q=hours-1
    values=[];names=[]
    def put(name,v):
        values.append(v);names.append(name)
    for h in [8,24,72,168]:
        cov=rolling(fresh.astype(np.int64),h)
        ok=(q>=h-1)&(cov[q,ids]==h)
        for sign,label in [(None,'net'),(1,'positive'),(-1,'negative')]:
            x=u if sign is None else np.where(u*sign>0,u,0)
            put(f'raw_{label}_sum_{h}h_bp',np.where(ok,rolling(x,h)[q,ids]*UNIT*1e4,np.nan))
    for sign,label in [(1,'positive'),(-1,'negative')]:
        put(f'raw_{label}_settlements_24h',np.where(k[q,ids],rolling((u*sign>0).astype(np.int64),24)[q,ids],np.nan))
    put('actual_settlements_24h',np.where(k[q,ids],rolling(state['settled'].astype(np.int64),24)[q,ids],np.nan))
    for h in [8,24]:
        ok=(q>=h)&k[q,ids]&k[np.maximum(q-h,0),ids]
        put(f'raw24_balance_change_{h}h_bp',np.where(ok,(b[q,ids]-b[np.maximum(q-h,0),ids])*UNIT*1e4,np.nan))
    put('known_nonpositive_raw24_age_hours',np.where(k[q,ids],state['age'][q,ids],np.nan))
    # Project only expiry of already-known cash payments. No future settlements or schedule.
    for h in [1,4,8]:
        put(f'raw24_no_new_payments_after_{h}h_bp',np.where(k[q,ids],rolling(u,24-h)[q,ids]*UNIT*1e4,np.nan))
    return np.column_stack(values).astype(np.float32),names

def regime_features(rates,fresh,hours,ids):
    q=hours-1;obs=np.where(fresh,rates,np.nan)
    denom=fresh.sum(axis=1)
    share=np.divide(((rates<0)&fresh).sum(axis=1),denom,out=np.full(len(rates),np.nan),where=denom>0)
    deep=np.divide(((rates<-.001)&fresh).sum(axis=1),denom,out=np.full(len(rates),np.nan),where=denom>0)
    median=np.full(len(rates),np.nan);observed=denom>0
    median[observed]=np.nanmedian(obs[observed],axis=1)
    ranks=pd.DataFrame(obs).rank(axis=1,pct=True).to_numpy()
    out=np.column_stack([share[q],deep[q],median[q]*1e4,share[q]-share[np.maximum(0,q-24)],
                         ranks[q,ids],(rates[q,ids]-median[q])*1e4])
    names=['market_negative_fraction','market_deep_fraction','market_median_r8_bp',
           'market_negative_fraction_change_24h','current_r8_cross_section_percentile','r8_minus_market_median_bp']
    return out.astype(np.float32),names

def exit_labels(state,rates,intervals,hours,ids,deliveries,horizon):
    """Known failures before missingness are zero; unobserved survivors stay censored."""
    b,k=state['balance'],state['known'];T=len(b)
    y=np.full(len(hours),np.nan);exit_after=np.full(len(hours),np.nan)
    censor_after=np.full(len(hours),np.nan);current_known=k[hours-1,ids]
    eligible=current_known&(b[hours-1,ids]<=0)
    for j,(t,n) in enumerate(zip(hours,ids)):
        if not current_known[j]:continue
        if not eligible[j]:y[j]=0.;exit_after[j]=0.;censor_after[j]=0.;continue
        stop=min(T,t+horizon)
        missing=np.flatnonzero(~k[t:stop,n]);censor=int(missing[0]) if len(missing) else stop-t
        known_prefix=min(censor,horizon)
        crossings=np.flatnonzero(b[t:t+known_prefix,n]>0)
        failure=int(crossings[0])+1 if len(crossings) else np.inf
        death=deliveries[n]-t
        if 0<=death<horizon and death<=censor:failure=min(failure,death+1)
        censor_after[j]=known_prefix
        if np.isfinite(failure):y[j]=0.;exit_after[j]=failure;continue
        if known_prefix<horizon:continue
        deep=(intervals[t:t+horizon,n]>0)&(rates[t:t+horizon,n]<-.001)
        y[j]=float(deep.any());exit_after[j]=horizon+1
    return y,eligible,exit_after,censor_after

def earliest_exit(state,hours,ids,horizon):
    out=np.full(len(hours),np.nan)
    for j,(t,n) in enumerate(zip(hours,ids)):
        if not state['known'][t-1,n]:continue
        if state['balance'][t-1,n]>0:out[j]=0;continue
        end=min(t+horizon,len(state['balance']))
        for q in range(t,end):
            if not state['known'][q,n]:break
            if state['balance'][q,n]>0:out[j]=q-t+1;break
        else:
            if end==t+horizon:out[j]=horizon+1
    return out
