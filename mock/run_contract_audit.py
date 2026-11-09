"""Independent public-CLI boundary audit; no forecasting accuracy claims or ledger writes."""
from pathlib import Path
from datetime import datetime,timedelta,timezone
import argparse,copy,hashlib,json,random,subprocess,sys

ROOT=Path(__file__).resolve().parents[1]
def encoded(x):return json.dumps(x,ensure_ascii=False,separators=(',',':'))
def cases():
    base=json.loads((ROOT/'examples/historical-negative-input.json').read_text())
    positive=json.loads((ROOT/'examples/historical-nonnegative-input.json').read_text())
    out=[]
    def add(name,r,invalid=False,check=None,raw=None):out.append(dict(name=name,request=r,invalid=invalid,check=check,raw=raw))
    add('historical_negative',base)
    add('historical_nonnegative',positive)
    q=copy.deepcopy(base);keys=list(q['features']);random.Random(811).shuffle(keys);q['features']={k:q['features'][k] for k in keys}
    add('key_order_invariance',q,check='same_predictions')
    q=copy.deepcopy(base);q['features']['injected_future_label']=1;add('extra_feature',q,True)
    q=copy.deepcopy(base);q['features'].pop('basis_bp');add('missing_feature',q,True)
    q=copy.deepcopy(base);q['features']['basis_bp']=True;add('boolean_feature',q,True)
    q=copy.deepcopy(base);q['features']['basis_bp']=float('inf');add('nonfinite_feature',q,True)
    q=copy.deepcopy(base);q['features']['conditional_quantity_fraction']=None;add('unknown_quantity_scenario',q,True)
    q=copy.deepcopy(base);q['features']['conditional_quantity_fraction']=.5;add('quantity_scenario_mismatch',q,True)
    q=copy.deepcopy(base);q['features']['settled_r8_bp']=None;add('missing_latest_settlement',q,True)
    q=copy.deepcopy(base);q['conditional_arrival_fraction']=True;add('boolean_quantity_fraction',q,True)
    q=copy.deepcopy(base);q['asof_utc']='2026-11-05T01:00:00+00:00';add('off_daily_grid',q,True)
    q=copy.deepcopy(base);q['feature_hour_start_utc']=q['asof_utc'];add('future_uncompleted_feature_hour',q,True)
    q=copy.deepcopy(base);q['raw24_known']=False;add('unknown_raw24',q,check='survival_null')
    q=copy.deepcopy(base);q['inventory_status']='AVAILABLE';add('already_available_inventory',q,check='economic_null')
    q=copy.deepcopy(base)
    for k in list(q['features'])[10:70]:q['features'][k]=None
    add('high_missingness',q,check='quality_limited')
    q=copy.deepcopy(base);q['information_mode']='unknown';add('invalid_information_mode',q,True)
    q=copy.deepcopy(base);day=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
    q.update(asof_utc=day.isoformat(),feature_hour_start_utc=(day-timedelta(hours=1)).isoformat(),information_mode='observed_asof_snapshot')
    add('observed_future_snapshot',q,True)
    raw=encoded(base).replace('"request_id":','"request_id":"hidden-duplicate", "request_id":',1)
    add('duplicate_json_keys',base,True,raw=raw)
    add('nonobject_json',[],True)
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);args=ap.parse_args()
    output=Path(args.output).resolve();output.mkdir(parents=True,exist_ok=True)
    if (output/'RESULTS.json').exists():raise RuntimeError('Do not overwrite audit evidence')
    suite=cases();protocol={'purpose':'Public scoring contract, adversarial input and metamorphic audit','cases':[dict(name=c['name'],expected_invalid=c['invalid'],check=c['check']) for c in suite],
      'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),ROOT/'scripts/score.py']},
      'model_predictions_not_accuracy_measure':True,'real_forward_predictions_created':0}
    (output/'PROTOCOL.json').write_text(json.dumps(protocol,indent=2)+'\n')
    rows=[];baseline=None
    for c in suite:
        inp=output/(c['name']+'.input.json');inp.write_text((c['raw'] or encoded(c['request']))+'\n')
        run=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/score.py'),'--input',str(inp)],capture_output=True,text=True,cwd=ROOT,timeout=90)
        try:response=json.loads(run.stdout)
        except json.JSONDecodeError:response=None
        (output/(c['name']+'.stdout.txt')).write_text(run.stdout)
        (output/(c['name']+'.stderr.txt')).write_text(run.stderr)
        passed=(run.returncode==2 and response is not None and response.get('status')=='INVALID_INPUT') if c['invalid'] else (run.returncode==0 and response is not None)
        if response and not c['invalid']:
            passed=passed and response.get('submission_allowed') is False and response.get('execution_actions')==[]
            for k,v in response.get('forecasts',{}).items():
                if k.startswith('p_') and v is not None:passed=passed and 0<=v<=1
            if c['name']=='historical_negative':baseline=response['forecasts']
            if c['check']=='same_predictions':passed=passed and response['forecasts']==baseline
            if c['check']=='survival_null':passed=passed and response['forecasts']['p_no_raw24_exit_next168h'] is None
            if c['check']=='economic_null':passed=passed and response['forecasts']['conditional_30d_reference_net_usdt'] is None
            if c['check']=='quality_limited':passed=passed and response['status']=='DATA_OR_TIMING_LIMITED'
        rows.append({'case':c['name'],'passed':bool(passed),'expected_invalid':c['invalid'],'exit_code':run.returncode,
          'status':None if response is None else response.get('status'),'forecasts':None if response is None else response.get('forecasts')})
        print(json.dumps(rows[-1]),flush=True)
    result={'cases':len(rows),'passed':sum(x['passed'] for x in rows),'failed':sum(not x['passed'] for x in rows),
       'failures':[x for x in rows if not x['passed']],'details':rows,'real_forward_predictions_created':0,'network_used':False}
    (output/'RESULTS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ['details','failures']}))
    return 1 if result['failed'] else 0

if __name__=='__main__':raise SystemExit(main())
