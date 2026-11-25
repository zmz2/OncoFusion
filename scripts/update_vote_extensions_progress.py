from __future__ import annotations
import argparse, fcntl, json, os, subprocess, tempfile
from datetime import datetime, timezone
from pathlib import Path

def main():
 p=argparse.ArgumentParser(); p.add_argument('--progress',required=True,type=Path); p.add_argument('--run-dir',required=True,type=Path); p.add_argument('--plan',required=True,type=Path); p.add_argument('--pid',required=True,type=int); a=p.parse_args()
 state_path=a.progress; lock_path=state_path.with_suffix('.lock'); run=a.run_dir
 with lock_path.open('a+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  state=json.loads(state_path.read_text())
  plan=json.loads(a.plan.read_text())
  planned=len(plan['case_ids'])*len(plan['treatments'])*len(plan.get('seeds',[0]))
  terminal=failed=full=degraded=0; calls=input_tokens=output_tokens=http_attempts=0
  arms={}
  for treatment in plan['treatments']:
   name=treatment['name']; d=run/name/'0'
   nterm=nfailed=nfull=ndegraded=0; ncall=nit=notok=nhttp=0
   if d.exists():
    for fp in d.glob('*.json'):
     if fp.name=='summary.json' or fp.name.endswith('.failed.json'): continue
     rec=json.loads(fp.read_text()); usage=rec.get('usage') or {}; vote=rec.get('vote_result') or {}
     nterm+=1
     st=vote.get('completion_status','failed')
     nfailed+=int(st=='failed'); nfull+=int(st=='full'); ndegraded+=int(st=='degraded')
     ncall+=int(usage.get('calls',0)); nit+=int(usage.get('input_tokens',0)); notok+=int(usage.get('output_tokens',0)); nhttp+=int(usage.get('http_attempts',0))
    for fp in d.glob('*.failed.json'):
     nterm+=1; nfailed+=1
     rec=json.loads(fp.read_text()); usage=rec.get('usage') or {}
     ncall+=int(usage.get('calls',0)); nit+=int(usage.get('input_tokens',0)); notok+=int(usage.get('output_tokens',0)); nhttp+=int(usage.get('http_attempts',0))
   arms[name]={'terminal':nterm,'full':nfull,'degraded':ndegraded,'failed':nfailed,'calls':ncall,'input_tokens':nit,'output_tokens':notok,'http_attempts':nhttp}
   terminal+=nterm; failed+=nfailed; full+=nfull; degraded+=ndegraded; calls+=ncall; input_tokens+=nit; output_tokens+=notok; http_attempts+=nhttp
  try: ps=subprocess.check_output(['ps','-p',str(a.pid),'-o','pid=,lstart=,args='],text=True).strip()
  except subprocess.CalledProcessError: ps=''
  is_live=bool(ps and str(a.pid) in ps and str(run) in ps)
  order=run/'provider_calls.jsonl'; order_calls=sum(1 for line in order.open() if line.strip()) if order.exists() else 0
  state.update({'planned_case_executions':planned,'terminal_case_executions':terminal,'completed':full+degraded,'failed':failed,'remaining':max(0,planned-terminal),'calls':max(calls,order_calls),'reported_usage_calls':calls,'http_attempts':http_attempts,'input_tokens':input_tokens,'output_tokens':output_tokens,'tokens':input_tokens+output_tokens,'arms':arms,'process_pid':a.pid,'process_identity':ps if is_live else None,'process_live':is_live,'status':'RUNNING' if is_live else ('COMPLETE' if terminal>=planned else 'INCOMPLETE'),'updated_utc':datetime.now(timezone.utc).isoformat()})
  fd,tmp=tempfile.mkstemp(prefix=state_path.name+'.',suffix='.tmp',dir=state_path.parent)
  with os.fdopen(fd,'w') as f: json.dump(state,f,ensure_ascii=False,indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
  os.replace(tmp,state_path)
  print(json.dumps({k:state[k] for k in ('phase','status','planned_case_executions','terminal_case_executions','completed','failed','remaining','calls','tokens','process_live','updated_utc')},ensure_ascii=False))
if __name__=='__main__': main()
