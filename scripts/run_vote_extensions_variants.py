from __future__ import annotations
import argparse, copy, hashlib, json, math, os, re, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from oncofusion.datasets import read_jsonl
from oncofusion.evidence import fragment_documents as base_fragment_documents, visible_case
from oncofusion.providers import provider_from_env
from oncofusion.schemas import CaseInput, RunConfig, TraceEvent
from oncofusion.vote_runner import VoteEngine
import oncofusion.vote_runner as vote_runner
from oncofusion.audit import attach_raw_audit

TLS=threading.local(); MANIFEST_LOCK=threading.Lock()
MOLECULAR_ORIGIN=re.compile(r"cna|mutation|gene|variant|genom",re.I)
PATH_ORIGIN=re.compile(r"patholog|histolog|specimen",re.I)
MOLECULAR_TEXT=re.compile(r"\b(?:mutation|variant|copy number|amplification|deletion|fusion|genomic|genomics|translocation|alteration)\b",re.I)
PATH_TEXT=re.compile(r"\b(?:histolog\w*|biopsy|specimen|immunohistochem\w*|patholog\w*|adenocarcinoma|carcinoma|morpholog\w*|tumou?r grade)\b",re.I)

def sha(value): return hashlib.sha256(value.encode('utf-8')).hexdigest()
def read_jsonl(path): return [json.loads(x) for x in Path(path).read_text(encoding='utf-8').splitlines() if x.strip()]
def update_coverage(evidence,index,coverage,documents):
    cov=copy.deepcopy(coverage)
    ids=[e['evidence_id'] for e in evidence]
    chars=sum(len(e.get('text','')) for e in evidence)
    cov['sent']=len(evidence); cov['chars_sent']=chars; cov['evidence_ids']=ids
    perdoc=cov.get('documents',{})
    bydoc={}
    for e in evidence: bydoc.setdefault(e['document_id'],[]).append(e)
    for did,rec in perdoc.items():
        items=bydoc.get(did,[]); rec['sent']=len(items); rec['chars_sent']=sum(len(e.get('text','')) for e in items); rec['evidence_ids']=[e['evidence_id'] for e in items]
        if 'required_sent' in rec:
            rec['required_sent']=sum(1 for e in items if e.get('required'))
    cov['documents_without_evidence']=sorted({d for d in perdoc if d not in bydoc})
    cov['tail_dropped']=any(rec['sent'] < rec['candidates'] for rec in perdoc.values())
    required=cov.get('required',{})
    for label,record in required.items():
        sent=[e['evidence_id'] for e in evidence if label in e.get('required',[])]
        old=[x for x in record.get('unsent',[]) if x not in ids]
        removed=[x['evidence_id'] for x in TLS.last_removed if label in x.get('required',[])] if getattr(TLS,'last_removed',None) else []
        record['sent']=len(sent); record['unsent']=list(dict.fromkeys(old+removed))
    cov['guaranteed_unsent']=list(cov.get('guaranteed_unsent',[]))
    cov['chars_sent']=chars
    return cov

def reorder_evidence(evidence, anchor_id, target):
    items=list(evidence); idx=next((i for i,e in enumerate(items) if e['evidence_id']==anchor_id),None)
    if idx is None: raise ValueError(f"anchor absent from frozen evidence snapshot: {anchor_id}")
    anchor=items.pop(idx)
    if target=='front': insert=0
    elif target=='end': insert=len(items)
    else:
        total=sum(len(e.get('text','')) for e in items)+len(anchor.get('text',''))
        candidates=[]; prefix=0
        for pos in range(len(items)+1):
            frac=(prefix+len(anchor.get('text',''))/2)/max(total,1)
            candidates.append((abs(frac-.5),pos,frac))
            if pos<len(items): prefix+=len(items[pos].get('text',''))
        _,insert,_=min(candidates)
    items.insert(insert,anchor)
    total=sum(len(e.get('text','')) for e in items)
    center=sum(len(e.get('text','')) for e in items[:insert])+len(anchor.get('text',''))/2
    return items, center/max(total,1)

def mask_evidence(case_id,evidence,index,coverage):
    items=list(evidence); n=len(items); drop_n=min(max(0,n-1),int(math.floor(.25*n+.5)))
    dropped=sorted(items,key=lambda e:sha(f"0:{case_id}:R4:{e['evidence_id']}"))[:drop_n]
    drop_ids={e['evidence_id'] for e in dropped}
    kept=[e for e in items if e['evidence_id'] not in drop_ids]
    TLS.last_removed=dropped
    new_index={key:value for key,value in index.items() if key not in drop_ids}
    return kept,new_index,update_coverage(kept,new_index,coverage,[e.get('document_id') for e in evidence]),[e['evidence_id'] for e in dropped]

def fragment_adapter(*args,**kwargs):
    evidence,index,coverage=base_fragment_documents(*args,**kwargs)
    ctx=getattr(TLS,'context',None)
    TLS.last_removed=[]
    if not ctx: return evidence,index,coverage
    if ctx['kind']=='position':
        arranged,fraction=reorder_evidence(evidence,ctx['anchor_id'],ctx['condition'])
        cov=copy.deepcopy(coverage); ids=[e['evidence_id'] for e in arranged]
        cov['evidence_ids']=ids
        for doc,rec in cov.get('documents',{}).items():
            rec['evidence_ids']=[e['evidence_id'] for e in arranged if e['document_id']==doc]
        TLS.observed={'evidence_ids':ids,'chars':sum(len(e.get('text','')) for e in arranged),'anchor_fraction':fraction,'anchor_present':True,'masked_ids':[],'evidence_snapshot':arranged,'coverage':cov}
        return arranged,index,cov
    if ctx['kind']=='mask_fragments':
        kept,new_index,cov,dropped=mask_evidence(ctx['case_id'],evidence,index,coverage)
        TLS.observed={'evidence_ids':[e['evidence_id'] for e in kept],'chars':sum(len(e.get('text','')) for e in kept),'anchor_fraction':None,'anchor_present':None,'masked_ids':dropped,'evidence_snapshot':kept,'evidence_index':new_index,'coverage':cov}
        return kept,new_index,cov
    TLS.observed={'evidence_ids':[e['evidence_id'] for e in evidence],'chars':sum(len(e.get('text','')) for e in evidence),'anchor_fraction':None,'anchor_present':None,'masked_ids':[],'evidence_snapshot':evidence,'evidence_index':index,'coverage':coverage}
    return evidence,index,coverage

def classify_doc(doc):
    kind=str(doc.kind).lower(); origin=str(doc.origin_id or '').lower()
    molecular=kind=='genomics' or bool(MOLECULAR_ORIGIN.search(origin))
    pathology=kind=='pathology' or bool(PATH_ORIGIN.search(origin))
    return molecular,pathology

def redact_lines(doc,pattern,reason,removed):
    lines=doc.text.splitlines(keepends=True); kept=[]
    for i,line in enumerate(lines):
        if pattern.search(line): removed.append({'document_id':doc.id,'line_index':i,'reason':reason,'text_sha256':sha(line.rstrip('\n'))})
        else: kept.append(line)
    return doc.model_copy(update={'text':''.join(kept)})

def transform_case(case,condition):
    removed_docs=[]; removed_lines=[]; removed_events=[]; entities=case.entities.model_dump()
    if condition in ('R1','R2'):
        docs=[]
        for doc in case.documents:
            molecular,pathology=classify_doc(doc)
            if (condition=='R1' and molecular) or (condition=='R2' and pathology):
                removed_docs.append(doc.id); continue
            if condition=='R1':
                doc=redact_lines(doc,MOLECULAR_TEXT,'remove_repeated_molecular_content',removed_lines)
            else:
                doc=redact_lines(doc,PATH_TEXT,'remove_repeated_pathology_content',removed_lines)
            doc_entities=doc.entities.model_dump()
            clear_keys=('gene','variant','molecular_profile','molecularProfile') if condition=='R1' else ('histology','specimen','pathology','tissue')
            for key in clear_keys:
                if key in doc_entities: doc_entities[key]=''
            title=doc.title
            if (condition=='R1' and MOLECULAR_TEXT.search(title)) or (condition=='R2' and PATH_TEXT.search(title)):
                title=''
            doc=doc.model_copy(update={'entities':type(doc.entities).model_validate(doc_entities),'title':title})
            if doc.text.strip(): docs.append(doc)
            else: removed_docs.append(doc.id)
        if condition=='R1':
            for key in ('gene','variant','molecular_profile','molecularProfile'):
                if key in entities: entities[key]=''
        if condition=='R2':
            for key in ('histology','specimen','pathology','tissue'):
                if key in entities: entities[key]=''
        new_entities=type(case.entities).model_validate(entities)
        return case.model_copy(update={'documents':docs,'entities':new_entities}),{'removed_document_ids':removed_docs,'removed_line_indices':removed_lines,'removed_event_lines':removed_events}
    if condition=='R3':
        event_lines=[]
        for doc in case.documents:
            if str(doc.kind).lower()!='clinical' or str(doc.origin_id or '').lower().startswith('context-'):
                continue
            for i,line in enumerate(doc.text.splitlines(keepends=True)):
                if line.strip(): event_lines.append((doc.id,i,line))
        remove_n=min(max(0,len(event_lines)-1),int(math.floor(.25*len(event_lines)+.5)))
        removed_rows=sorted(event_lines,key=lambda x:sha(f"0:{case.id}:R3:{x[0]}:{x[1]}"))[:remove_n]
        removed_keys={(doc_id,line_i) for doc_id,line_i,_ in removed_rows}
        removed_texts=[re.sub(r'\W+',' ',line.lower()).strip() for _,_,line in removed_rows]
        docs=[]; duplicate_summary_lines=[]
        for doc in case.documents:
            lines=doc.text.splitlines(keepends=True); kept=[]
            for i,line in enumerate(lines):
                norm=re.sub(r'\W+',' ',line.lower()).strip()
                direct=(doc.id,i) in removed_keys
                duplicate=bool(norm and len(norm)>=24 and any(norm in old or old in norm for old in removed_texts if len(old)>=24))
                if direct or duplicate:
                    row={'document_id':doc.id,'line_index':i,'text_sha256':sha(line.rstrip('\n'))}
                    if direct: removed_events.append(row)
                    else: duplicate_summary_lines.append(row)
                else: kept.append(line)
            docs.append(doc.model_copy(update={'text':''.join(kept)}))
        return case.model_copy(update={'documents':docs}),{'removed_document_ids':[],'removed_line_indices':[],'removed_event_lines':removed_events,'duplicate_summary_lines':duplicate_summary_lines,'event_block_summary':{'original_blocks':len(event_lines),'removed_blocks':remove_n}}
    return case,{'removed_document_ids':[],'removed_line_indices':[],'removed_event_lines':[]}

def jsonl_append(path,row):
    with MANIFEST_LOCK:
        with Path(path).open('a',encoding='utf-8') as f:
            f.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--mode',choices=['position','robustness'],required=True); ap.add_argument('--dataset-name',choices=['MTB','CIViC'],required=True)
    ap.add_argument('--data',type=Path,required=True); ap.add_argument('--dev-plan',type=Path,required=True); ap.add_argument('--selection',type=Path,required=True); ap.add_argument('--out',type=Path,required=True); ap.add_argument('--workers',type=int,default=5); ap.add_argument('--raw-audit',type=Path); ap.add_argument('--dry-run',action='store_true')
    args=ap.parse_args(); data=Path(args.data); plan=json.loads(Path(args.dev_plan).read_text()); selection=json.loads(Path(args.selection).read_text())
    cases={x['id']:CaseInput.model_validate(x) for x in read_jsonl(data/'inputs.jsonl')}
    treatments={t['name']:RunConfig.model_validate(t['overrides']) for t in plan['treatments']}
    arm_names=('b0_common_single','p_k_specialists')
    if args.mode=='position':
        anchors=selection['e02b_anchor_candidates'][args.dataset_name]; conditions=('front','middle','end')
        records=[(row['case_id'],condition,row['anchor_evidence_id']) for row in anchors for condition in conditions]
    else:
        if args.dataset_name!='MTB': raise ValueError('robustness is preregistered for MTB only')
        anchors=selection['e04_mtb_cases']; conditions=('R1','R2','R3','R4')
        records=[(row['case_id'],condition,None) for row in anchors for condition in conditions]
    jobs=[]
    preflight=[]
    for cid,condition,anchor in records:
        case=cases[cid]
        if args.mode=='robustness': case,change=transform_case(case,condition)
        else: change={'removed_document_ids':[],'removed_line_indices':[],'removed_event_lines':[]}
        for arm in arm_names:
            jobs.append((cid,condition,anchor,arm,case,change))
        preflight.append({'case_id':cid,'condition':condition,'anchor_id':anchor,'case_input_sha256':sha(json.dumps(case.model_dump(mode='json'),sort_keys=True,ensure_ascii=False)),'removed_document_ids':change.get('removed_document_ids',[]),'removed_line_count':len(change.get('removed_line_indices',[]))+len(change.get('removed_event_lines',[]))})
    position_checks=[]
    if args.mode=='position':
        for cid in sorted({x[0] for x in records}):
            case=visible_case(cases[cid]); q=' '.join(filter(None,[case.question,*[str(v) for v in case.entities.model_dump().values() if v]]))
            ev,idx,cov=base_fragment_documents(case.documents,600,8,q,12000,role='decision')
            row=next(x for x in anchors if x['case_id']==cid)
            ids=set()
            positions={}
            for condition in conditions:
                arranged,fraction=reorder_evidence(ev,row['anchor_evidence_id'],condition); ids.add(frozenset(e['evidence_id'] for e in arranged)); positions[condition]=fraction
            if len(ids)!=1: raise AssertionError('position conditions changed the evidence ID set')
            if not (positions['front']<.1 and positions['end']>.9):
                raise ValueError(f"anchor edge placement failed for {cid}: {positions}")
            position_checks.append({'case_id':cid,**positions,'middle_within_target':.45<=positions['middle']<=.55})
    if args.dry_run:
        bycondition={c:{'cases':sum(x['condition']==c for x in preflight),'removed_documents':sum(len(x['removed_document_ids']) for x in preflight if x['condition']==c),'removed_lines':sum(x['removed_line_count'] for x in preflight if x['condition']==c)} for c in conditions}
        payload={'mode':args.mode,'dataset':args.dataset_name,'cases':len(records)//len(conditions),'conditions':bycondition,'arms':list(arm_names),'case_executions':len(jobs),'max_model_calls':sum(treatments[a].max_calls for *_,a,__,___ in jobs)}
        if position_checks: payload['middle_outside_target_cases']=[r['case_id'] for r in position_checks if not r['middle_within_target']]
        print(json.dumps(payload,ensure_ascii=False))
        return 0
    args.out.mkdir(parents=True,exist_ok=False)
    vote_runner.fragment_documents=fragment_adapter
    provider=provider_from_env()
    if not provider.simulated:
        if not os.getenv('ONCOFUSION_API_CONCURRENCY') or not 1 <= int(os.environ['ONCOFUSION_API_CONCURRENCY']) <= 20:
            raise ValueError('real experiment requires process-wide concurrency 20')
    if args.raw_audit: attach_raw_audit(provider,args.raw_audit)
    engine=VoteEngine(provider)
    code_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    manifest={'mode':args.mode,'dataset':args.dataset_name,'code_commit':code_commit,'cases':len(records)//len(conditions),'conditions':list(conditions),'arms':list(arm_names),'workers':args.workers,'scheduler_capacity':getattr(getattr(provider,'scheduler',None),'capacity',None),'started_utc':datetime.now(timezone.utc).isoformat(),'preflight':preflight}
    (args.out/'identity.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    plan_rows=[]
    for cid,condition,anchor,arm,case,change in jobs:
        plan_rows.append({'case_id':cid,'condition':condition,'anchor_id':anchor,'arm':arm,'case':case,'change':change})
    outputs=[]
    def execute(job):
        cid=job["case_id"]; condition=job["condition"]; anchor=job["anchor_id"]; arm=job["arm"]; case=job["case"]; change=job["change"]
        TLS.context={'kind':'position' if args.mode=='position' else ('mask_fragments' if condition=='R4' else 'docs'),'condition':condition,'case_id':cid,'anchor_id':anchor}
        TLS.last_removed=[]; TLS.observed={}
        result=engine.run(case,treatments[arm])
        observed=getattr(TLS,'observed',{})
        result.fingerprint=sha(json.dumps({'base':result.fingerprint,'mode':args.mode,'condition':condition,'anchor_id':anchor,'evidence_ids':observed.get('evidence_ids',[]),'masked_ids':observed.get('masked_ids',[])},sort_keys=True,ensure_ascii=False))
        result.trace.append(TraceEvent(sequence=len(result.trace),kind='vote_extension_variant',role='adapter',details={'mode':args.mode,'condition':condition,'anchor_id':anchor,'anchor_fraction':observed.get('anchor_fraction'),'evidence_ids':observed.get('evidence_ids',[]),'evidence_chars':observed.get('chars'),'masked_evidence_ids':observed.get('masked_ids',[]),'removed_document_ids':change.get('removed_document_ids',[]),'removed_line_indices':change.get('removed_line_indices',[]),'removed_event_line_indices':[(x['document_id'],x['line_index']) for x in change.get('removed_event_lines',[])],'case_input_sha256':sha(json.dumps(case.model_dump(mode='json'),sort_keys=True,ensure_ascii=False))}))
        dest=args.out/condition/arm/'0'; dest.mkdir(parents=True,exist_ok=True)
        target=dest/(cid+'.json'); target.write_text(result.model_dump_json(indent=2),encoding='utf-8')
        row={'case_id':cid,'condition':condition,'arm':arm,'status':result.vote_result.completion_status,'prediction':result.vote_result.label,'gold_only_in_eval':True,'actual_calls':result.usage.calls,'input_tokens':result.usage.input_tokens,'output_tokens':result.usage.output_tokens,'seconds':result.duration_seconds,'evidence_chars':observed.get('chars'),'evidence_ids':observed.get('evidence_ids'),'anchor_id':anchor,'anchor_fraction':observed.get('anchor_fraction'),'masked_ids':observed.get('masked_ids'),'removed_document_ids':change.get('removed_document_ids',[]),'removed_line_count':len(change.get('removed_line_indices',[]))+len(change.get('removed_event_lines',[])),'result_path':str(target)}
        jsonl_append(args.out/'variant_results_private.jsonl',row)
        jsonl_append(args.out/'variant_inputs_private.jsonl',{'case_id':cid,'condition':condition,'arm':arm,'change':change,'case_input_sha256':sha(json.dumps(case.model_dump(mode='json'),sort_keys=True,ensure_ascii=False)),'case_input':case.model_dump(mode='json'),'evidence_snapshot':observed.get('evidence_snapshot'),'coverage':observed.get('coverage')})
        return row
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for row in pool.map(execute,plan_rows): outputs.append(row)
    summary={'mode':args.mode,'dataset':args.dataset_name,'completed_case_executions':len(outputs),'failed_case_executions':sum(x['status']=='failed' for x in outputs),'calls':sum(x['actual_calls'] for x in outputs),'input_tokens':sum(x['input_tokens'] for x in outputs),'output_tokens':sum(x['output_tokens'] for x in outputs),'concurrency':getattr(getattr(provider,'scheduler',None),'snapshot',lambda:None)(),'finished_utc':datetime.now(timezone.utc).isoformat(),'result_rows':outputs}
    (args.out/'summary_private.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:summary[k] for k in ('mode','dataset','completed_case_executions','failed_case_executions','calls','input_tokens','output_tokens','concurrency')},ensure_ascii=False))
    return 0
if __name__=='__main__': raise SystemExit(main())
