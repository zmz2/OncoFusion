from __future__ import annotations
import argparse,copy,json,os,sys,threading,hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from oncofusion.datasets import read_jsonl
from oncofusion.evidence import fragment_documents,visible_case
from oncofusion.providers import provider_from_env
from oncofusion.schemas import CaseInput,RunResult,VoteArbitration
from oncofusion.vote_runner import VoteEngine
from oncofusion.voting import aggregate_ballots,arbitration_required
from oncofusion.audit import attach_raw_audit
sys.path.insert(0,str(Path(__file__).resolve().parent))
import analyze_vote_extensions as analysis

POLICIES=(('no_arbitration',None,None,False),('share_050',.50,.25,False),('share_060',.60,.25,False),('share_075',.75,.25,False),('share_100',1.00,.25,False),('always',None,None,True))
def labels_for(case): return list(case.verification_labels) if case.task=='verification' else sorted(case.options)
def read_result(path): return RunResult.model_validate_json(Path(path).read_text()) if Path(path).exists() else None
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--run',type=Path,required=True); ap.add_argument('--dataset',type=Path,required=True); ap.add_argument('--case-ids',type=Path,required=True); ap.add_argument('--out',type=Path,required=True); ap.add_argument('--workers',type=int,default=20); ap.add_argument('--raw-audit',type=Path); ap.add_argument('--dry-run',action='store_true'); args=ap.parse_args()
 ids=json.loads(args.case_ids.read_text())
 if isinstance(ids,dict): ids=ids['case_ids']
 inputs={r['id']:CaseInput.model_validate(r) for r in read_jsonl(args.dataset/'inputs.jsonl')}
 gold={r['case_id']:r['label'] for r in read_jsonl(args.dataset/'_gold'/'labels.jsonl')}
 groups={r['case_id']:str(r.get('group_id') or r.get('patient_id') or r['case_id']) for r in read_jsonl(args.dataset/'_gold'/'labels.jsonl')}
 base={}; initial={}; cache={}; missing=[]
 for cid in ids:
  p=args.run/'p_k_specialists'/'0'/(cid+'.json'); r=read_result(p)
  if r is None:
   fp=args.run/'p_k_specialists'/'0'/(cid+'.failed.json')
   if fp.exists():
    base[cid]=None; initial[cid]=None
   else: base[cid]=None; initial[cid]=None
   continue
  base[cid]=r
  v=aggregate_ballots(case_id=cid,ballots=r.ballots,labels=labels_for(inputs[cid]),planned_roles=r.vote_result.planned_roles,pool=r.vote_result.pool,rule='v0',tie_seed=0)
  if v.label!=r.vote_result.label or v.valid_votes!=r.vote_result.valid_votes: raise ValueError(f'initial vote replay mismatch: {cid}')
  initial[cid]=v
  vp=args.run/'v3'/'p_k_specialists'/'0'/(cid+'.json'); vr=read_result(vp)
  if vr and vr.vote_result and vr.vote_result.arbitration.triggered:
   if [b.model_dump() for b in vr.ballots] != [b.model_dump() for b in r.ballots]: raise ValueError(f'V3 cache ballots differ: {cid}')
   if vr.vote_result.arbitration.initial_label!=v.label: raise ValueError(f'V3 cache initial label differs: {cid}')
   cache[cid]={'arbitration':vr.vote_result.arbitration,'usage':{'calls':vr.usage.calls-r.usage.calls,'input_tokens':vr.usage.input_tokens-r.usage.input_tokens,'output_tokens':vr.usage.output_tokens-r.usage.output_tokens,'http_attempts':vr.usage.http_attempts-r.usage.http_attempts},'source':'same-run V3 .75'}
 def needs(policy,cid):
  name,share,margin,always=policy; v=initial.get(cid)
  if not v or v.completion_status=='failed' or v.label is None: return False
  return True if always else bool(share is not None and arbitration_required(v,share,margin))
 needed={cid for cid in ids if any(needs(pol,cid) for pol in POLICIES) and cid not in cache}
 if args.dry_run:
  print(json.dumps({'cases':len(ids),'valid_initial_vote_n':sum(bool(initial.get(c) and initial[c].label is not None and initial[c].completion_status!='failed') for c in ids),'cached_075_arbitrations':len(cache),'additional_unique_arbitrations_needed':len(needed),'by_policy':{p[0]:sum(needs(p,c) for c in ids) for p in POLICIES}},ensure_ascii=False)); return 0
 if args.out.exists(): raise FileExistsError(args.out)
 args.out.mkdir(parents=True)
 provider=provider_from_env()
 if not provider.simulated and (not os.getenv('ONCOFUSION_API_CONCURRENCY') or not 1 <= int(os.environ['ONCOFUSION_API_CONCURRENCY']) <= 20): raise ValueError('threshold sweep process cap must be between 1 and the global 20-slot limit')
 if args.raw_audit: attach_raw_audit(provider,args.raw_audit)
 engine=VoteEngine(provider)
 def arbitrate(cid):
  r=base[cid]; case=visible_case(inputs[cid]); cfg=r.config.model_copy(update={'vote_rule':'v3','vote_arbitration_min_share':.75,'vote_arbitration_margin':.25,'max_calls':r.config.max_calls+3})
  query=' '.join(filter(None,[case.question,*[str(x) for x in case.entities.model_dump().values() if x]]))
  evidence,index,_=fragment_documents(case.documents,cfg.fragment_chars,cfg.max_fragments_per_document,query,cfg.fragment_budget,role='decision')
  prior=r.usage; usage=prior.model_copy(deep=True); trace=list(r.trace)
  arb=engine._adjudicate(case,labels_for(case),r.ballots,evidence,index,cfg,initial[cid].label,usage,trace,threading.RLock(),None)
  return cid,{'arbitration':arb,'usage':{'calls':usage.calls-prior.calls,'input_tokens':usage.input_tokens-prior.input_tokens,'output_tokens':usage.output_tokens-prior.output_tokens,'http_attempts':usage.http_attempts-prior.http_attempts},'source':'new unique request'}
 with ThreadPoolExecutor(max_workers=args.workers) as pool:
  for cid,item in pool.map(arbitrate,sorted(needed)): cache[cid]=item
 manifest={'case_ids':ids,'cached_from_v3_075':[c for c,v in cache.items() if v['source']=='same-run V3 .75'],'new_unique_arbitrations':[c for c,v in cache.items() if v['source']=='new unique request'],'arbitration_cache':{c:{'status':x['arbitration'].status,'triggered':x['arbitration'].triggered,'usage':x['usage'],'source':x['source']} for c,x in cache.items()}}
 (args.out/'arbitration_cache_index.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
 rows=[]; case_rows=[]; per_results={}
 for name,share,margin,always in POLICIES:
  result_map={}; trig=arb_done=arb_fail=changed_to_right=changed_to_wrong=hold_right=hold_wrong=0; calls=itok=otok=sweep_calls=sweep_itok=sweep_otok=0
  for cid in ids:
   r=base.get(cid); v=initial.get(cid)
   if not r or not v:
    result_map[cid]=None; case_rows.append({'case_id':cid,'policy':name,'gold':gold[cid],'prediction':None,'completion_status':'failed','triggered':False,'arbitration_status':'not_available'}); continue
   trigger=needs((name,share,margin,always),cid)
   arb=cache.get(cid,{}).get('arbitration') if trigger else VoteArbitration(triggered=False,status='not_triggered',initial_label=v.label,final_label=v.label)
   if trigger:
    trig+=1
    if arb is None: raise ValueError(f'missing arbitration cache for {name}/{cid}')
    arb_done+=int(arb.status=='completed'); arb_fail+=int(arb.status=='failed')
    usage=cache[cid]['usage']; calls+=usage['calls']; itok+=usage['input_tokens']; otok+=usage['output_tokens']
    if cache[cid]['source']=='new unique request': sweep_calls+=usage['calls']; sweep_itok+=usage['input_tokens']; sweep_otok+=usage['output_tokens']
   vr=aggregate_ballots(case_id=cid,ballots=r.ballots,labels=labels_for(inputs[cid]),planned_roles=r.vote_result.planned_roles,pool='specialist',rule='v3' if trigger else 'v0',tie_seed=0,arbitration=arb if trigger else None,min_share=share if share is not None else 1.0,min_margin=margin if margin is not None else .25)
   pr=vr.label if vr.completion_status!='failed' else None
   result_map[cid]={'vote_result':{'label':pr,'completion_status':vr.completion_status}}
   base_correct=v.label==gold[cid]; final_correct=pr==gold[cid]
   changed_to_right+=int(trigger and v.label!=gold[cid] and final_correct)
   changed_to_wrong+=int(trigger and v.label==gold[cid] and not final_correct)
   hold_right+=int(trigger and v.label==gold[cid] and pr==v.label)
   hold_wrong+=int(trigger and v.label!=gold[cid] and pr==v.label)
   case_rows.append({'case_id':cid,'group_id':groups[cid],'policy':name,'gold':gold[cid],'initial_label':v.label,'prediction':pr,'completion_status':vr.completion_status,'top_share':v.top_share,'margin':v.margin,'triggered':trigger,'arbitration_status':arb.status,'arbitration_changed':bool(trigger and arb.status=='completed' and arb.final_label!=v.label),'correct':int(pr==gold[cid])})
  mm=analysis.metrics(ids,gold,result_map,('SUPPORTS','REVISIONS','NEI') if inputs[ids[0]].task=='verification' else sorted({lab for cid in ids for lab in labels_for(inputs[cid])}))
  rows.append({'policy':name,'n':len(ids),'correct':mm['correct'],'accuracy':mm['accuracy'],'macro_f1':mm['macro_f1'],'completion_rate':mm['completion_rate'],'triggered':trig,'arbitration_completed':arb_done,'arbitration_failed':arb_fail,'changed_to_correct':changed_to_right,'changed_to_wrong':changed_to_wrong,'kept_correct':hold_right,'kept_wrong':hold_wrong,'policy_added_calls':calls,'policy_added_input_tokens':itok,'policy_added_output_tokens':otok,'policy_added_tokens':itok+otok,'sweep_incremental_calls':sweep_calls,'sweep_incremental_input_tokens':sweep_itok,'sweep_incremental_output_tokens':sweep_otok,'full_logical_calls':sum((r.usage.calls if r else 0) for r in base.values())+calls})
  per_results[name]=result_map
 analysis.write_csv(args.out/'threshold_results.csv',rows); analysis.write_csv(args.out/'threshold_case_results.csv',case_rows)
 trigger_sets={p[0]:[c for c in ids if needs(p,c)] for p in POLICIES}
 (args.out/'threshold_trigger_sets.json').write_text(json.dumps(trigger_sets,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'cases':len(ids),'cached_075':len(manifest['cached_from_v3_075']),'new_unique_arbitrations':len(manifest['new_unique_arbitrations']),'policies':rows,'concurrency':getattr(getattr(provider,'scheduler',None),'snapshot',lambda:None)()},ensure_ascii=False))
 return 0
if __name__=='__main__': raise SystemExit(main())
