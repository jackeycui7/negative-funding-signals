from independent_sources import *
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--seconds',type=int,default=240);p.add_argument('--latest-only',action='store_true');a=p.parse_args();s=Datahub()
 try:print(json.dumps(s.collect(a.seconds,a.latest_only),ensure_ascii=False),flush=True)
 finally:s.s.close()
