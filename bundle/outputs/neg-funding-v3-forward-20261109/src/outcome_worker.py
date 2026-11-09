"""Independent realized funding-event labels, with append-only censor/revision evidence."""
import feature_worker as w
live=w.live;np=w.np;pd=w.pd
import sqlite3,json,hashlib

def mature():
 db=sqlite3.connect(live.ROOT/'data/forward.sqlite',isolation_level=None);now=live.ms();pred=db.execute('SELECT id,asof_ms,issued_ms,symbol,payload FROM forecasts WHERE fraction=1 AND asof_ms+72*3600000<=?',(now,)).fetchall()
 if not pred:return {'mature_predictions':0,'new_outcome_revisions':0}
 T=(now-live.ORIGIN)//live.H;arr,pre,pos,meta,syms,seedlen=w.loadhistory(T);proof,_=w.observed(arr,pre,pos,meta,syms,seedlen,live.ORIGIN+T*live.H,now);fresh=w.em.fresh_funding(arr['r8'],arr['ivh'],arr['fc']);state=w.ec.cash_state(arr['ev'],arr['ivh'],fresh);revisions=0
 for ident,asof,issued,sym,payload in pred:
  p=json.loads(payload)['prediction'];n=syms.index(sym);a=(asof-live.ORIGIN)//live.H
  for head,stop in [('p_new_negative_within72h',72),('p_no_raw24_exit_next168h',168),('p_qualified_entry_after72h_within7d',240),('conditional_30d_reference_net_usdt',1008)]:
   if now<asof+stop*live.H or p['forecasts'][head] is None:continue
   out={'prediction_id':ident,'head':head,'window_start_utc':live.iso(asof+(72 if stop in [240,1008] else 0)*live.H),'window_end_exclusive_utc':live.iso(asof+stop*live.H),'outcome':None,'evaluation_status':'MISSING_OR_CENSORED','late_data':False,'label_basis':'frozen_v3_target_definition','source_evidence_sha256':hashlib.sha256(live.canonical(proof).encode()).hexdigest(),'first_event_utc':None}
   if stop in [240,1008]:out['evaluation_status']='PENDING_FROZEN_STRATEGY_RECOMPUTATION';out['reason']='Requires full frozen cost/lifecycle/qualified-entry or constrained-exit replay, not inferred from a negative funding print.'
   elif a+stop<=T:
    known=fresh[a:a+stop,n] if stop==72 else state['known'][a:a+stop,n];bad=np.flatnonzero(~known);first_bad=int(bad[0]) if len(bad) else stop
    hitmask=(arr['ivh'][a:a+stop,n]>0)&(arr['ev'][a:a+stop,n]<0) if stop==72 else state['balance'][a:a+stop,n]>0;hits=np.flatnonzero(hitmask[:first_bad]);first=int(hits[0]) if len(hits) else None
    death=int(meta.dl_fin.iloc[n]);death_delay=death-a
    if 0<=death_delay<first_bad and (first is None or death_delay<first):first=death_delay;out['reason']='KNOWN_DELIVERY'
    if first is not None:
     event=asof+first*live.H;out['first_event_utc']=live.iso(event);out['outcome']=int(stop==72 and out.get('reason')!='KNOWN_DELIVERY');out['evaluation_status']='VERIFIED'
     if event<issued:out['outcome']=None;out['evaluation_status']='EVENT_ALREADY_OCCURRED_BEFORE_ISSUE'
    elif first_bad==stop:out['outcome']=0 if stop==72 else 1;out['evaluation_status']='VERIFIED'
    out['known_prefix_hours']=first_bad;out['fixed_horizon_hours']=stop
   # Later source repairs are appended, never overwrite the initial missing/censored label.
   previous=db.execute('SELECT payload FROM outcomes WHERE prediction_id=? AND head=? ORDER BY logged_ms DESC LIMIT 1',(ident,head)).fetchone()
   if previous:
    old=json.loads(previous[0]);same=lambda x:{k:v for k,v in x.items() if k!='source_evidence_sha256'}
    if same(old)==same(out):continue
    out['late_data']=True;out['correction_reason']='New public observations or coverage revision after first mature evaluation; excluded from primary result.'
   body=live.canonical(out);digest=hashlib.sha256(body.encode()).hexdigest();db.execute('INSERT OR IGNORE INTO outcomes VALUES(?,?,?,?,?)',(ident,head,digest,now,body));revisions+=1
 db.close();return {'mature_predictions':len(pred),'new_outcome_revisions':revisions}
if __name__=='__main__':print(json.dumps(mature()))
