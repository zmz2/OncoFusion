from __future__ import annotations
import argparse,copy,hashlib,json,os,shutil,sys,threading,time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from oncofusion.agent_design import duty as original_duty
from oncofusion.audit import attach_raw_audit
from oncofusion.datasets import read_jsonl
from oncofusion.engine import TASK_FRAMING
from oncofusion.evidence import visible_case
from oncofusion.providers import ModelReply,ProviderError,provider_from_env
from oncofusion.schemas import Ballot,CaseInput,RunConfig,RunResult,TraceEvent,Usage,VoteBallotOutput
from oncofusion.vote_runner import VoteEngine
import oncofusion.vote_runner as vote_runner

ACTIVE_ROLE=None; ACTIVE_DUTY=None; LOCK=threading.Lock()

def digest(v): return hashlib.sha256(v.encode()).hexdigest()
def dumps(v): return json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def replace_exact(text,old,new):
 if old not in text: raise ValueError('frozen role duty text changed; cannot apply the preregistered prompt replacement')
 return text.replace(old,new,1)
def altered_duty(role,base):
 if role=='timeline':
  base=replace_exact(base,'1. Keep event time, recording order, and current information availability distinct. 2. Distinguish observed events, negated events, planned treatments, family history, and uncertain events.','1. Summarize the clinical information that is present in the supplied records.')
 elif role=='genomics':
  base=replace_exact(base,'1. Resolve the supplied gene and exact variant spelling; retain transcript, assay and germline/somatic ambiguity where relevant. 2. Separate gene-pathway membership, variant functional consequence, and measured pathway activity into distinct assertions.','1. Summarize molecular observations stated in the supplied sources.')
  base=replace_exact(base,'4. Assign functional direction only when supported at the appropriate variant level. Record missing functional evidence as unresolved.','4. Keep unsupported molecular statements unresolved.')
 elif role=='pathology':
  base=replace_exact(base,'1. Extract supplied cancer type, histology, primary site, sampled site, stage, and assay biomarkers with citations. 2. Keep primary and metastatic specimens distinct. Distinguish patient findings from family history or hypothetical descriptions. 3. Evaluate whether external evidence concerns the same disease, specimen and biomarker definition; label missing context.','1. Summarize pathology information stated in the supplied sources.')
 elif role=='drug':
  base=replace_exact(base,'2. Separate sensitivity, primary resistance, acquired resistance, and prior exposure. Treat lexical polarity as a retrieval hint.','2. Describe drug evidence as stated in the supplied sources.')
 elif role=='literature':
  base=replace_exact(base,'2. For each finding retain an exact quote, original source identity, applicability and what the evidence directly measures.','2. For each finding retain an exact quote and original source identity.')
  base=replace_exact(base,'3. Retain relevant opposing results alongside supporting evidence; repeated copies of a paper remain one source.','3. Group repeated copies of a paper as one source.')
 else: raise ValueError(role)
 return base

def find_evidence_id(citation,evidence):
 for item in evidence:
  if item['document_id']==citation.document_id:
   s,e=item.get('record_span',[None,None])
   if citation.start is None or (s<=citation.start and citation.end<=e): return item['evidence_id']
 raise ValueError('cached ballot citation cannot be mapped to a visible evidence fragment')
def ballot_wire(ballot,evidence):
 if ballot.status=='failed': return None
 ids=[{'evidence_id':x} for x in ballot.evidence_ids]
 findings=[]
 for f in ballot.findings:
  fids=[{'evidence_id':find_evidence_id(c,evidence)} for c in f.citations]
  if not fids and ids: fids=[ids[0]]
  findings.append({'statement':f.statement,'stance':f.stance,'evidence_ids':fids})
 return json.dumps({'status':ballot.status,'label':ballot.label,'confidence':ballot.confidence,'brief_reason':ballot.brief_reason or 'Cached baseline member response.','evidence_ids':ids,'findings':findings},ensure_ascii=False)

def expected_system(case,config,role):
 visible=visible_case(case); labels=list(visible.verification_labels) if visible.task=='verification' else sorted(visible.options)
 schema=VoteBallotOutput.model_json_schema(); schema['properties']['label']={'anyOf':[{'type':'string','enum':labels},{'type':'null'}]}
 system=('You are one independent member of a research-only evidence vote. '
 'You receive the same complete question and evidence packet as every other '
 'member, and you do not see their answers. Use only the supplied evidence. '
 +original_duty(role)+' '+TASK_FRAMING[visible.task]+' '
 'First record at most two short, checkable professional findings with visible '
 'evidence ids. Then answer the same full task independently. A local absence '
 'or not-applicable observation is not automatically a global NEI vote. '
 'ABSTAIN only when your professional responsibility is completely inapplicable '
 'or you cannot form any task-level judgement. For a non-NEI answer, cite at '
 'least one visible evidence id. Do not invent labels, evidence ids, PMIDs, '
 'patient history, or outside facts. Confidence is an uncalibrated self-rating '
 'of whether your own full answer is correct. Return JSON only conforming to this schema: '
 +json.dumps(schema,ensure_ascii=False))
 if visible.task=='verification': system+=' Legal labels are '+', '.join(labels)+'. SUPPORTS means the claim is evidenced as written; REVISIONS means a specific correction is required; NEI means irrelevant, missing, or insufficient evidence.'
 if visible.task=='mcq': system+=' The label must be one option key from '+', '.join(visible.options)+'.'
 return system

class ReplayProvider:
 def __init__(self,real,target,base_result,base_ballots,prior_audit_rows=()):
  self.inner=real; self.scheduler=getattr(real,'scheduler',None)
  for attr in ('name','model','simulated','input_price','output_price'): setattr(self,attr,getattr(real,attr))
  self.target=target; self.base_result=base_result; self.base_ballots={b.role:b for b in base_ballots}; self.actual_calls=0; self.actual_in=0; self.actual_out=0; self.actual_attempts=0; self.resumed_calls=0; self.new_calls=0; self.rows=[]
  self.prior_audit_rows=list(prior_audit_rows); self.used_prior_rows=set(); self.expected={}
  for event in base_result.trace:
   if event.kind=='agent_started' and event.role and event.role not in self.expected: self.expected[event.role]=event.details.get('payload_sha256')
 def complete(self,system,payload,max_tokens,temperature,seed):
  role=payload['role']; identity_payload={k:v for k,v in payload.items() if k!='repair'}
  base_ph=hashlib.sha256(json.dumps(identity_payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
  request_ph=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest(); system_hash=digest(system); expected=self.expected.get(role)
  if expected and base_ph!=expected: raise ValueError(f'cached or target payload differs from baseline for {self.base_result.case_id}/{role}')
  if role!='generalist' and role!=self.target and role not in self.base_ballots: raise ValueError('planned baseline ballot missing')
  prior=None
  if role==self.target:
   for i,row in enumerate(self.prior_audit_rows):
    req=row.get('request') or {}
    if i not in self.used_prior_rows and row.get('role')==role and row.get('payload_sha256')==request_ph and row.get('system_sha256')==system_hash and req.get('seed')==seed and req.get('temperature')==temperature and req.get('max_output_tokens')==max_tokens:
     prior=(i,row); break
  self.rows.append({'role':role,'system_sha256':system_hash,'payload_sha256':request_ph,'baseline_payload_sha256':base_ph,'seed':seed,'temperature':temperature,'max_output_tokens':max_tokens,'actual_api_call':role==self.target,'cache_replay':role!=self.target,'source':'prior_raw_audit_replay' if prior else ('new_api_call' if role==self.target else 'baseline_ballot_replay')})
  if role==self.target:
   if prior:
    i,row=prior; self.used_prior_rows.add(i); self.resumed_calls+=1; self.actual_calls+=1
    if row.get('status')!='completed':
     observed=row.get('observed_usage')
     reply=ModelReply('',int((observed or {}).get('input_tokens',0)),int((observed or {}).get('output_tokens',0)),int((observed or {}).get('attempts',0)),bool(row.get('estimated_usage',False))) if observed else None
     if reply:
      self.actual_in+=reply.input_tokens; self.actual_out+=reply.output_tokens; self.actual_attempts+=reply.attempts
     raise ProviderError(row.get('error') or 'replayed prior provider failure',observed_reply=reply)
    reply=ModelReply(row['response'],int(row.get('input_tokens',0)),int(row.get('output_tokens',0)),int(row.get('http_attempts',1)),bool(row.get('estimated_usage',False)))
    self.actual_in+=reply.input_tokens; self.actual_out+=reply.output_tokens; self.actual_attempts+=reply.attempts
    return reply
   reply=self.inner.complete(system,payload,max_tokens,temperature,seed)
   self.actual_calls+=1; self.new_calls+=1; self.actual_in+=reply.input_tokens; self.actual_out+=reply.output_tokens; self.actual_attempts+=reply.attempts
   return reply
  ballot=self.base_ballots[role]
  if ballot.status=='failed': raise ProviderError('cached baseline member was a failed ballot')
  return ModelReply(ballot_wire(ballot,payload['evidence']),0,0,0,False)

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--selection',type=Path,required=True); ap.add_argument('--mtb-data',type=Path,required=True); ap.add_argument('--civic-data',type=Path,required=True); ap.add_argument('--mtb-run',type=Path,required=True); ap.add_argument('--civic-run',type=Path,required=True); ap.add_argument('--out',type=Path,required=True); ap.add_argument('--workers',type=int,default=15); ap.add_argument('--raw-audit',type=Path); ap.add_argument('--resume-from',type=Path); ap.add_argument('--dry-run',action='store_true'); x=ap.parse_args()
 selection=json.loads(x.selection.read_text()); targets=selection['e05b_role_case_ids']; specs={}; alljobs=[]; case_lookup={}; base_lookup={}; data_name={}
 for role,items in targets.items():
  base=original_duty(role); changed=altered_duty(role,base)
  specs[role]={'role':role,'original_duty':base,'ablated_duty':changed,'original_sha256':digest(base),'ablated_sha256':digest(changed),'targeted_change':'Remove or neutralize the preregistered role-specific mechanism only; all common vote instructions and task payload remain unchanged.'}
  for item in items:
   dataset=item['dataset']; data=x.mtb_data if dataset=='MTB' else x.civic_data; run=x.mtb_run if dataset=='MTB' else x.civic_run
   records={r['id']:r for r in read_jsonl(data/'inputs.jsonl')}; case=CaseInput.model_validate(records[item['case_id']]); result_path=run/'p_k_specialists'/'0'/(item['case_id']+'.json')
   result=RunResult.model_validate_json(result_path.read_text()) if result_path.exists() else None
   if not result: raise ValueError(f'missing fresh P-K base result for {dataset}/{item["case_id"]}')
   if role not in result.vote_result.planned_roles: raise ValueError(f'target role was not planned for {dataset}/{item["case_id"]}')
   job={'dataset':dataset,'case_id':item['case_id'],'role':role,'case':case,'base':result,'run':run,'data':data}
   alljobs.append(job); case_lookup[(dataset,item['case_id'])]=case; base_lookup[(dataset,item['case_id'])]=result; data_name[(dataset,item['case_id'])]=str(data)
 if x.dry_run:
  print(json.dumps({'target_members':len(alljobs),'per_role':{r:len(v) for r,v in targets.items()},'workers':x.workers,'all_targets_in_base_pool':True,'spec_hashes':{r:{'original':s['original_sha256'],'ablated':s['ablated_sha256']} for r,s in specs.items()}},ensure_ascii=False)); return 0
 if x.out.exists(): raise FileExistsError(x.out)
 x.out.mkdir(parents=True)
 prior_audit_rows=[]
 if x.resume_from:
  prior_path=x.resume_from/'raw_audit.jsonl'
  if prior_path.exists():
   for line in prior_path.read_text(encoding='utf-8').splitlines():
    if line.strip(): prior_audit_rows.append(json.loads(line))
   if x.raw_audit:
    Path(x.raw_audit).parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(prior_path,x.raw_audit)
 specpath=x.out/'prompt_ablation_specs.json'; specpath.write_text(json.dumps({'roles':specs,'selection_seed':0,'sample_selection':'input eligibility only, no model outcomes','cached_members':'same fresh P-K pool; unchanged members replayed from saved parsed ballots','resume_from':str(x.resume_from) if x.resume_from else None,'prior_api_request_records_replayed':len(prior_audit_rows)},ensure_ascii=False,indent=2)+'\n')
 provider=provider_from_env()
 if not provider.simulated and (not os.getenv('ONCOFUSION_API_CONCURRENCY') or not 1 <= int(os.environ['ONCOFUSION_API_CONCURRENCY']) <= 20): raise ValueError('prompt ablation requires shared process concurrency 20')
 if x.raw_audit: attach_raw_audit(provider,x.raw_audit)
 original_module_duty=vote_runner.specialist_duty
 def dispatch_duty(role): return ACTIVE_DUTY if role==ACTIVE_ROLE else original_module_duty(role)
 vote_runner.specialist_duty=dispatch_duty
 result_rows=[]; request_rows=[]
 try:
  for role,items in targets.items():
   ACTIVE_ROLE=role; ACTIVE_DUTY=specs[role]['ablated_duty']
   jobs=[j for j in alljobs if j['role']==role]
   def one(j):
    base=j['base']; cfg=base.config
    engine=VoteEngine(ReplayProvider(provider,role,base,base.ballots,prior_audit_rows))
    wrapped=engine.provider
    run=engine.run(j['case'],cfg)
    cached_roles=[b.role for b in run.ballots if b.role!=role]
    for b in run.ballots:
     if b.role!=role:
      b.usage=Usage(); b.duration_seconds=0.0
    for row in wrapped.rows:
     run.trace.append(TraceEvent(sequence=len(run.trace),kind='vote_extension_cache_replay' if row['cache_replay'] else 'vote_extension_actual_prompt',role=row['role'],details={'baseline_payload_sha256':row['payload_sha256'],'system_sha256':row['system_sha256'],'actual_api_call':row['actual_api_call'],'seed':row['seed']}))
    actual=Usage(calls=wrapped.actual_calls,http_attempts=wrapped.actual_attempts,input_tokens=wrapped.actual_in,output_tokens=wrapped.actual_out)
    run.usage=actual
    base_target=next(b for b in base.ballots if b.role==role)
    logical={'calls':base.usage.calls-base_target.usage.calls+wrapped.actual_calls,'input_tokens':base.usage.input_tokens-base_target.usage.input_tokens+wrapped.actual_in,'output_tokens':base.usage.output_tokens-base_target.usage.output_tokens+wrapped.actual_out}
    raw={'dataset':j['dataset'],'case_id':j['case_id'],'role':role,'result':run.model_dump(mode='json'),'prompt_audit':wrapped.rows,'logical_full_cost':logical,'incremental_actual_cost':{'calls':wrapped.actual_calls,'input_tokens':wrapped.actual_in,'output_tokens':wrapped.actual_out},'new_api_calls':wrapped.new_calls,'resumed_prior_api_calls':wrapped.resumed_calls,'cached_roles':cached_roles,'base_result_path':str(j['run']/'p_k_specialists'/'0'/(j['case_id']+'.json')),'base_code_commit':base.config.model_dump(mode='json')}
    path=x.out/'results'/j['dataset']/role/'0'/(j['case_id']+'.json'); path.parent.mkdir(parents=True,exist_ok=True); path.write_text(run.model_dump_json(indent=2),encoding='utf-8')
    result_rows.append({'dataset':j['dataset'],'case_id':j['case_id'],'ablated_role':role,'base_label':base.vote_result.label,'ablated_label':run.vote_result.label,'base_status':base.vote_result.completion_status,'ablated_status':run.vote_result.completion_status,'planned_members':len(base.vote_result.planned_roles),'valid_votes':run.vote_result.valid_votes,'actual_api_calls':wrapped.actual_calls,'new_api_calls':wrapped.new_calls,'resumed_prior_api_calls':wrapped.resumed_calls,'actual_input_tokens':wrapped.actual_in,'actual_output_tokens':wrapped.actual_out,'logical_full_calls':logical['calls'],'logical_full_input_tokens':logical['input_tokens'],'logical_full_output_tokens':logical['output_tokens'],'base_member_label':base_target.label,'base_member_status':base_target.status,'ablated_member_label':next(b.label for b in run.ballots if b.role==role),'ablated_member_status':next(b.status for b in run.ballots if b.role==role),'result_path':str(path)})
    request_rows.extend({'dataset':j['dataset'],'case_id':j['case_id'],'ablated_role':role,**r} for r in wrapped.rows)
    return raw
   with ThreadPoolExecutor(max_workers=x.workers) as pool:
    completed=list(pool.map(one,jobs))
   with (x.out/'prompt_ablation_private.jsonl').open('a',encoding='utf-8') as f:
    for rec in completed: f.write(json.dumps(rec,ensure_ascii=False,separators=(',',':'))+'\n')
 finally:
  vote_runner.specialist_duty=original_module_duty
 result_rows.sort(key=lambda r:(r['dataset'],r['ablated_role'],r['case_id']))
 with (x.out/'prompt_ablation_results.csv').open('w',encoding='utf-8',newline='') as f:
  import csv
  w=csv.DictWriter(f,fieldnames=list(result_rows[0])); w.writeheader(); w.writerows(result_rows)
 with (x.out/'prompt_hash_audit.csv').open('w',encoding='utf-8',newline='') as f:
  import csv
  w=csv.DictWriter(f,fieldnames=list(request_rows[0])); w.writeheader(); w.writerows(request_rows)
 (x.out/'summary.json').write_text(json.dumps({'target_members':len(result_rows),'failed_ablated_votes':sum(r['ablated_status']=='failed' for r in result_rows),'actual_calls':sum(r['actual_api_calls'] for r in result_rows),'new_api_calls':sum(r.get('new_api_calls',0) for r in result_rows),'resumed_prior_api_calls':sum(r.get('resumed_prior_api_calls',0) for r in result_rows),'input_tokens':sum(r['actual_input_tokens'] for r in result_rows),'output_tokens':sum(r['actual_output_tokens'] for r in result_rows),'concurrency':getattr(getattr(provider,'scheduler',None),'snapshot',lambda:None)(),'finished_utc':datetime.now(timezone.utc).isoformat()},ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'target_members':len(result_rows),'actual_calls':sum(r['actual_api_calls'] for r in result_rows),'failed_ablated_votes':sum(r['ablated_status']=='failed' for r in result_rows),'out':str(x.out)},ensure_ascii=False)); return 0
if __name__=='__main__': raise SystemExit(main())
