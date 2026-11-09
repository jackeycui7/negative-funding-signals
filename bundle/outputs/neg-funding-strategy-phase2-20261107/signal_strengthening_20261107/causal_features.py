"""Pure, past-only feature construction and separately computed future labels."""
import numpy as np
import pandas as pd


def shift(a, hours=1):
    out=np.full_like(a,np.nan,dtype=float)
    out[hours:]=a[:-hours]
    return out


def rolling(a, hours, operation='mean'):
    frame=pd.DataFrame(a)
    window=frame.rolling(hours,min_periods=max(1,hours//2))
    return getattr(window,operation)().to_numpy()


def age_of_negative(rate):
    out=np.zeros_like(rate)
    age=np.zeros(rate.shape[1])
    for t in range(len(rate)):
        age=np.where(np.isfinite(rate[t])&(rate[t]<0),age+1,0.)
        out[t]=np.minimum(age,720.)
    return out


def build_features(arr, premium, positioning, sample_hours, btc_index, symbol_ids=None):
    """Each row at t only uses completed hours <=t-1, including funding."""
    clock=np.arange(len(arr['r8']))[:,None]
    last=np.maximum.accumulate(np.where(arr['ivh']>0,clock,-10000),axis=0)
    observation_age=clock-last
    rate=np.where(observation_age<=8,arr['r8'],np.nan);sc=arr['sc'];fc=arr['fc']
    known_interval=pd.DataFrame(np.where(arr['ivh']>0,arr['ivh'],np.nan)).ffill().to_numpy()
    sq=np.where(np.isfinite(arr['sq'])&(arr['sq']>=0),arr['sq'],0.)
    fq=np.where(np.isfinite(arr['fq'])&(arr['fq']>=0),arr['fq'],0.)
    age=age_of_negative(rate)
    columns=[];groups=[];values=[]
    def add(name,group,a,already_lagged=False):
        x=a if already_lagged else shift(a)
        sampled = x[sample_hours].reshape(-1) if symbol_ids is None else x[sample_hours, symbol_ids]
        values.append(sampled.astype(np.float32))
        columns.append(name);groups.append(group)
    add('settled_r8_bp','history',rate*1e4)
    add('funding_observation_age_hours','history',observation_age)
    add('latest_settled_interval_hours','history',known_interval)
    add('known_negative_age_hours','history',age)
    for h in [24,72,168,720]:
        add(f'r8_mean_{h}h_bp','history',rolling(rate,h)*1e4)
        negative=np.where(np.isfinite(rate),(rate<0).astype(float),np.nan)
        deep=np.where(np.isfinite(rate),(rate<-.001).astype(float),np.nan)
        add(f'negative_fraction_{h}h','history',rolling(negative,h))
        add(f'deep_fraction_{h}h','history',rolling(deep,h))
    add('r8_change_24h_bp','history',(rate-shift(rate,24))*1e4)
    add('r8_std_168h_bp','history',rolling(rate,168,'std')*1e4)
    with np.errstate(divide='ignore',invalid='ignore'):
        basis=(fc-sc)/sc
        oi=arr['oih']
        coin_oi=oi/fc
        logsc=np.log(np.where(sc>0,sc,np.nan))
        logfc=np.log(np.where(fc>0,fc,np.nan))
        for h in [24,72,168]:
            sr=logsc-shift(logsc,h);fr=logfc-shift(logfc,h)
            add(f'spot_return_{h}h','market',sr)
            add(f'perp_minus_spot_return_{h}h','market',fr-sr)
            add(f'spot_minus_BTC_return_{h}h','market',sr-sr[:,btc_index,None])
            add(f'coin_OI_log_change_{h}h','market',np.log(coin_oi/shift(coin_oi,h)))
        add('basis_bp','market',basis*1e4)
        add('basis_change_24h_bp','market',(basis-shift(basis,24))*1e4)
        adv_s=rolling(sq,24,'sum');adv_f=rolling(fq,24,'sum')
        add('log_spot_volume_24h','market',np.log1p(adv_s))
        add('log_perp_spot_volume_ratio_24h','market',np.log((adv_f+1)/(adv_s+1)))
        add('log_OI_to_paired_volume','market',np.log((oi+1)/(np.minimum(adv_s,adv_f)+1)))
        add('spot_volatility_24h','market',rolling(logsc-shift(logsc),24,'std'))
        add('premium_close_bp','premium',premium*1e4)
        for h in [24,72,168]:add(f'premium_mean_{h}h_bp','premium',rolling(premium,h)*1e4)
        add('premium_change_24h_bp','premium',(premium-shift(premium,24))*1e4)
        for j,name in enumerate(['global_accounts','top_accounts','top_positions','taker_flow']):
            x=np.log(np.where(positioning[:,:,j]>0,positioning[:,:,j],np.nan))
            add(name+'_log_ratio','positioning',x)
            add(name+'_mean_24h','positioning',rolling(x,24))
    matrix=np.column_stack(values)
    matrix[~np.isfinite(matrix)]=np.nan
    # Fixed physical clipping, never whole-sample winsorisation.
    matrix=np.clip(matrix,-1e6,1e6)
    return matrix,columns,groups


def build_labels(events, intervals, rates, futures_close, decisions, delivery_hours):
    T,N=events.shape
    times=np.arange(T)[:,None]
    event=intervals>0
    last=np.maximum.accumulate(np.where(event,times,-10000),axis=0)
    fresh=(times-last<=8)&np.isfinite(rates)&(futures_close>0)
    negative=(rates<0)&fresh
    deep_event=event&(rates<-.001)
    new_negative=np.zeros_like(event)
    prior=np.full(N,np.nan)
    for t in range(T):
        new_negative[t]=event[t]&(events[t]<0)&(prior>=0)
        prior=np.where(event[t],events[t],prior)
    prefix={name:np.vstack([np.zeros((1,N)),np.cumsum(value,axis=0)])
            for name,value in [('fresh',fresh),('negative',negative),('deep',deep_event),('onset',new_negative)]}
    labels={};ends={}
    for days in [7,14]:
        length=days*24;name=f'persistent_opportunity_{days}d'
        y=np.full((len(decisions),N),np.nan)
        for i,t in enumerate(decisions):
            a=t+73;b=t+72+length+1
            if b>T:continue
            coverage=prefix['fresh'][b]-prefix['fresh'][a]
            n=prefix['negative'][b]-prefix['negative'][a]
            d=prefix['deep'][b]-prefix['deep'][a]
            known=coverage>=.95*length
            y[i,known]=((n[known]/length>=.75)&(d[known]>0)).astype(float)
            # A known contract delivery is a failure, not a favourable censor.
            failed=(delivery_hours>t)&(delivery_hours<b)
            y[i,failed]=0.
        labels[name]=y.reshape(-1)
        ends[name]=np.repeat(decisions+72+length,N)
    name='new_negative_72h';y=np.full((len(decisions),N),np.nan)
    for i,t in enumerate(decisions):
        a=t+1;b=t+73
        if b>T or t<1:continue
        known=(rates[t-1]>=0)&fresh[t-1]
        coverage=prefix['fresh'][b]-prefix['fresh'][a]
        known &= coverage>=.95*72
        y[i,known]=((prefix['onset'][b]-prefix['onset'][a])[known]>0).astype(float)
    labels[name]=y.reshape(-1);ends[name]=np.repeat(decisions+72,N)
    return labels,ends
