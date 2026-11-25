from __future__ import annotations
import argparse, json, os, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from oncofusion.datasets import read_jsonl
from oncofusion.evidence import visible_case
from oncofusion.providers import provider_from_env
from oncofusion.schemas import CaseInput, RunResult, TraceEvent, VoteArbitration
from oncofusion.vote_runner import VoteEngine, build_vote_decision
from oncofusion.voting import aggregate_ballots, arbitration_required


def labels_for(case):
    return list(case.verification_labels) if case.task == 'verification' else sorted(case.options)


def main():
    ap=argparse.ArgumentParser(description='Derive V3 from saved position/robustness P-K ballots and exact evidence snapshots.')
    ap.add_argument('--run',type=Path,required=True,help='base variants run directory')
    ap.add_argument('--data',type=Path,required=True)
    ap.add_argument('--mode',choices=['position','robustness'],required=True)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--min-share',type=float,default=.75); ap.add_argument('--min-margin',type=float,default=.25)
    ap.add_argument('--workers',type=int,default=20); ap.add_argument('--raw-audit',type=Path)
    args=ap.parse_args()
    if args.workers<1: raise ValueError('workers must be positive')
    cases={x['id']:CaseInput.model_validate(x) for x in read_jsonl(args.data/'inputs.jsonl')}
    snapshots={}
    with (args.run/'variant_inputs_private.jsonl').open(encoding='utf-8') as f:
        for line in f:
            row=json.loads(line)
            if row.get('arm')=='p_k_specialists': snapshots[(row['case_id'],row['condition'])]=row
    base_rows=[]
    for condition_dir in sorted(p for p in args.run.iterdir() if p.is_dir() and p.name not in {'v3'}):
        condition=condition_dir.name
        if args.mode=='position' and condition not in {'front','middle','end'}: continue
        if args.mode=='robustness' and condition not in {'R1','R2','R3','R4'}: continue
        root=condition_dir/'p_k_specialists'/'0'
        if not root.exists(): continue
        for path in sorted(root.glob('*.json')):
            if path.name=='summary.json' or path.name.endswith('.failed.json'): continue
            result=RunResult.model_validate_json(path.read_text())
            snap=snapshots.get((result.case_id,condition))
            if not snap or not snap.get('case_input') or not snap.get('evidence_snapshot'):
                raise ValueError(f'missing exact private snapshot for {condition}/{result.case_id}')
            case=CaseInput.model_validate(snap['case_input'])
            visible=visible_case(case)
            evidence=snap['evidence_snapshot']
            if [x['evidence_id'] for x in evidence] != next((e.details.get('evidence_ids',[]) for e in result.trace if e.kind=='vote_extension_variant'),[]):
                raise ValueError(f'evidence order differs from saved P-K input for {condition}/{result.case_id}')
            docs={d.id:d for d in visible.documents}
            index={}
            for item in evidence:
                doc=docs[item['document_id']]; start,end=item['record_span']
                if doc.text[start:end] != item['text']:
                    raise ValueError(f'evidence snapshot no longer matches transformed source {condition}/{result.case_id}/{item["evidence_id"]}')
                index[item['evidence_id']]=(doc,start,end)
            initial=aggregate_ballots(case_id=result.case_id,ballots=result.ballots,labels=labels_for(visible),planned_roles=result.vote_result.planned_roles,pool=result.vote_result.pool,rule='v0')
            if initial.label!=result.vote_result.label or initial.completion_status!=result.vote_result.completion_status:
                raise ValueError(f'variant P-K initial vote does not replay {condition}/{result.case_id}')
            base_rows.append((condition,case,visible,result,initial,evidence,index))
    if args.out.exists(): raise FileExistsError(args.out)
    args.out.mkdir(parents=True)
    provider=provider_from_env()
    if not provider.simulated and (not os.getenv('ONCOFUSION_API_CONCURRENCY') or int(os.environ['ONCOFUSION_API_CONCURRENCY'])!=20):
        raise ValueError('variant arbitration requires shared process concurrency 20')
    if args.raw_audit:
        from oncofusion.audit import attach_raw_audit
        attach_raw_audit(provider,args.raw_audit)
    engine=VoteEngine(provider); trigger=[x for x in base_rows if x[4].completion_status!='failed' and arbitration_required(x[4],args.min_share,args.min_margin)]
    output_rows=[]
    def run(item):
        condition,case,visible,result,initial,evidence,index=item
        cfg=result.config.model_copy(update={'vote_rule':'v3','vote_arbitration_min_share':args.min_share,'vote_arbitration_margin':args.min_margin,'max_calls':result.config.max_calls+3})
        usage=result.usage.model_copy(deep=True); trace=list(result.trace); ledger=threading.RLock()
        arb=engine._adjudicate(visible,labels_for(visible),result.ballots,evidence,index,cfg,initial.label,usage,trace,ledger,None)
        vote=aggregate_ballots(case_id=visible.id,ballots=result.ballots,labels=labels_for(visible),planned_roles=result.vote_result.planned_roles,pool=result.vote_result.pool,rule='v3',arbitration=arb,min_share=args.min_share,min_margin=args.min_margin)
        decision=build_vote_decision(visible,cfg,vote,result.ballots,index)
        updated=result.model_copy(update={'config':cfg,'decision':decision,'usage':usage,'trace':trace,'status':'failed' if decision is None else 'completed','vote_result':vote,'duration_seconds':result.duration_seconds+sum(e.details.get('seconds',0) for e in trace[len(result.trace):] if e.kind=='model_usage')})
        dest=args.out/condition/'p_k_specialists'/'0'; dest.mkdir(parents=True,exist_ok=True); dest.joinpath(case.id+'.json').write_text(updated.model_dump_json(indent=2),encoding='utf-8')
        return {'case_id':case.id,'condition':condition,'initial_label':initial.label,'final_label':vote.label,'arbitration_status':arb.status,'changed':arb.final_label!=arb.initial_label,'extra_calls':usage.calls-result.usage.calls}
    with ThreadPoolExecutor(max_workers=args.workers) as pool: output_rows=list(pool.map(run,trigger))
    triggered={(x[0],x[1].id) for x in trigger}
    copied=0
    for condition,case,visible,result,initial,evidence,index in base_rows:
        if (condition,case.id) in triggered: continue
        arb=VoteArbitration(triggered=False,status='not_triggered',initial_label=initial.label,final_label=initial.label)
        cfg=result.config.model_copy(update={'vote_rule':'v3','vote_arbitration_min_share':args.min_share,'vote_arbitration_margin':args.min_margin})
        vote=aggregate_ballots(case_id=visible.id,ballots=result.ballots,labels=labels_for(visible),planned_roles=result.vote_result.planned_roles,pool=result.vote_result.pool,rule='v3',arbitration=arb,min_share=args.min_share,min_margin=args.min_margin)
        decision=build_vote_decision(visible,cfg,vote,result.ballots,index)
        updated=result.model_copy(update={'config':cfg,'decision':decision,'status':'failed' if decision is None else 'completed','vote_result':vote})
        dest=args.out/condition/'p_k_specialists'/'0'; dest.mkdir(parents=True,exist_ok=True); dest.joinpath(case.id+'.json').write_text(updated.model_dump_json(indent=2),encoding='utf-8'); copied+=1
    scheduler=getattr(provider,'scheduler',None)
    summary={'mode':args.mode,'source_run':str(args.run),'total_cases':len(base_rows),'triggered':len(trigger),'arbitrated_completed':sum(x['arbitration_status']=='completed' for x in output_rows),'arbitrated_failed':sum(x['arbitration_status']!='completed' for x in output_rows),'changed':sum(x['changed'] for x in output_rows),'extra_calls':sum(x['extra_calls'] for x in output_rows),'v0_copied':copied,'concurrency':scheduler.snapshot() if scheduler else None,'cases':output_rows}
    (args.out/'arbitration.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:summary[k] for k in ['mode','total_cases','triggered','arbitrated_completed','arbitrated_failed','changed','extra_calls','v0_copied','concurrency']},ensure_ascii=False))
if __name__=='__main__': raise SystemExit(main())
