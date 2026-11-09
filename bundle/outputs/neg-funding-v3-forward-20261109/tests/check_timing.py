"""The exact original1h OI prelag and actual received-at cutoffs on synthetic5m observations."""
import sys,tempfile,sqlite3,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import feature_worker as w
np=w.np;pd=w.pd;live=w.live
root=live.ROOT
with tempfile.TemporaryDirectory() as d:
 live.ROOT=Path(d);(live.ROOT/'data/raw').mkdir(parents=True);c=sqlite3.connect(live.ROOT/'data/market.sqlite');c.executescript('CREATE TABLE records(kind,symbol,event_ms,received_ms,payload,request_id);CREATE TABLE requests(id,hash);')
 base=live.ORIGIN;asof=base+3*live.H
 observations=[('oi','BTCUSDT',base+55*60000,100,{'sumOpenInterestValue':'111'},1),('oi','BTCUSDT',base+50*60000,200,{'sumOpenInterestValue':'50'},2),('top_accounts','BTCUSDT',base+55*60000,100,{'longShortRatio':'2'},3),('top_accounts','BTCUSDT',base+2*live.H+55*60000,1001,{'longShortRatio':'9999'},4),('top_accounts','BTCUSDT',asof+55*60000,100,{'longShortRatio':'8888'},5)]
 c.executemany('INSERT INTO records VALUES(?,?,?,?,?,?)',[(k,s,t,r,json.dumps(x),i) for k,s,t,r,x,i in observations]);c.commit();c.close();arr={k:np.zeros((4,1)) if k in ['ev','ivh'] else np.full((4,1),np.nan) for k in ['sc','fc','sq','fq','r8','oih','ev','ivh']};pre=np.full((4,1),np.nan);pos=np.full((4,1,4),np.nan);meta=pd.DataFrame({'mult':[1]});proof,cross=w.observed(arr,pre,pos,meta,['BTCUSDT'],0,asof,1000)
 assert arr['oih'][1,0]==111 # Last event timestamp wins, even if older page arrived later.
 assert np.isnan(arr['oih'][0,0])
 assert pos[0,0,1]==2
 assert np.isnan(pos[2,0,1]) # received after cutoff
 assert np.isnan(pos[3,0,1]) # event after asof
live.ROOT=root
print(json.dumps({'passed':True,'checks':5,'synthetic_records_never_entered_live_ledger':True}))
