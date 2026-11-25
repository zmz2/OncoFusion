from __future__ import annotations
import argparse, csv, hashlib, json, random, sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.analyze_vote_extensions import load_dataset, load_results, metrics, pred, completion, write_csv


def bootstrap_delta(ids, gold, base, candidate, groups, repeats=2000, seed=0):
    by_group=defaultdict(list)
    for cid in ids: by_group[groups[cid]].append(cid)
    keys=sorted(by_group); rng=random.Random(seed); values=[]
    for _ in range(repeats):
        picked=[rng.choice(keys) for _ in keys]
        sample=[cid for g in picked for cid in by_group[g]]
        if sample:
            a=sum(pred(base.get(cid))==gold[cid] for cid in sample)/len(sample)
            b=sum(pred(candidate.get(cid))==gold[cid] for cid in sample)/len(sample)
            values.append(b-a)
    values.sort()
    return [values[int(.025*(len(values)-1))],values[int(.975*(len(values)-1))]] if values else [None,None]


def cost(rec):
    if not rec: return {'calls':0,'input_tokens':0,'output_tokens':0,'http_attempts':0,'seconds':0.0}
    u=rec.get('usage') or {}
    return {'calls':int(u.get('calls',0)),'input_tokens':int(u.get('input_tokens',0)),
            'output_tokens':int(u.get('output_tokens',0)),'http_attempts':int(u.get('http_attempts',0)),
            'seconds':float(rec.get('duration_seconds',0.0) or 0.0)}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--data',type=Path,required=True); ap.add_argument('--plan',type=Path,required=True)
    ap.add_argument('--run',type=Path,required=True); ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args(); args.out.mkdir(parents=True,exist_ok=True)
    cases,gold,groups=load_dataset(args.data); plan=json.loads(args.plan.read_text())
    ids=list(plan['case_ids']); labels=sorted({lab for cid in ids for lab in cases[cid].options})
    arms=('b0_common_single','p_k_specialists','v3/p_k_specialists')
    results=load_results(args.run,arms)
    absent={arm:sorted(set(ids)-set(results[arm])) for arm in arms}
    if any(absent.values()): raise ValueError(f'fixed holdout denominator has absent records: {absent}')
    table=[]; all_metrics={}
    for arm,name in [('b0_common_single','Single Agent'),('p_k_specialists','P-K without arbitration'),('v3/p_k_specialists','OncoFusion V3')]:
        m=metrics(ids,gold,results[arm],labels); all_metrics[arm]=m
        cs=[cost(results[arm][cid]) for cid in ids]
        table.append({'method':name,'n':m['n'],'correct':m['correct'],'accuracy':m['accuracy'],'macro_f1':m['macro_f1'],
          'valid_completion_rate':m['completion_rate'],'full':m['full'],'degraded':m['degraded'],'failed':m['failed'],
          'calls':sum(x['calls'] for x in cs),'http_attempts':sum(x['http_attempts'] for x in cs),
          'input_tokens':sum(x['input_tokens'] for x in cs),'output_tokens':sum(x['output_tokens'] for x in cs),
          'seconds_total':sum(x['seconds'] for x in cs)})
    b0=results['b0_common_single']; pk=results['p_k_specialists']; v3=results['v3/p_k_specialists']
    paired=[]
    for cand_name,candidate in [('P-K without arbitration',pk),('OncoFusion V3',v3)]:
        both=[]; right=wrong=recovered=lost=0
        for cid in ids:
            pa,pb=pred(b0.get(cid)),pred(candidate.get(cid)); ca,cb=pa==gold[cid],pb==gold[cid]
            if pa is not None and pb is not None:
                both.append(cid); right+=int(not ca and cb); wrong+=int(ca and not cb)
            recovered+=int(pa is None and pb is not None and cb)
            lost+=int(pa is not None and ca and pb is None)
        bm=metrics(both,gold,b0,labels); cm=metrics(both,gold,candidate,labels)
        paired.append({'comparison':'B0 to '+cand_name,'n':len(ids),'candidate_accuracy_diff':all_metrics['v3/p_k_specialists' if cand_name=='OncoFusion V3' else 'p_k_specialists']['accuracy']-all_metrics['b0_common_single']['accuracy'],
          'candidate_minus_b0_group_bootstrap_95ci':bootstrap_delta(ids,gold,b0,candidate,groups,2000,0),
          'both_valid_n':len(both),'both_valid_b0_accuracy':bm['accuracy'],'both_valid_candidate_accuracy':cm['accuracy'],
          'both_valid_changed_to_correct':right,'both_valid_changed_to_wrong':wrong,'b0_failed_candidate_correct':recovered,'b0_correct_candidate_failed':lost})
    ablation=[]
    for arm,name in [('p_k_specialists','P-K without arbitration'),('v3/p_k_specialists','OncoFusion V3')]:
        m=all_metrics[arm]
        ablation.append({'method':name,'n':m['n'],'correct':m['correct'],'accuracy':m['accuracy'],'macro_f1':m['macro_f1'],'completion_rate':m['completion_rate'],'full':m['full'],'degraded':m['degraded'],'failed':m['failed']})
    arbitration_path=args.run/'v3/arbitration.json'; arbitration=json.loads(arbitration_path.read_text())
    trigger_rows=arbitration['cases']; ablation[1].update({'arbitration_triggered':arbitration['triggered'],'arbitration_completed':sum(x['arbitration_status']=='completed' for x in trigger_rows),'arbitration_failed':sum(x['arbitration_status']!='completed' for x in trigger_rows),'changed':arbitration['changed'],'extra_calls':arbitration['extra_calls'],'improved':sum(not x['initial_correct'] and x['final_correct'] for x in trigger_rows),'worsened':sum(x['initial_correct'] and not x['final_correct'] for x in trigger_rows),'kept_correct':sum(x['initial_correct'] and x['final_correct'] for x in trigger_rows),'kept_wrong':sum(not x['initial_correct'] and not x['final_correct'] for x in trigger_rows)})
    per_patient=[]
    for group in sorted(set(groups[c] for c in ids)):
        members=[c for c in ids if groups[c]==group]
        row={'patient_group':group,'n':len(members)}
        for arm,name in [('b0_common_single','b0'),('p_k_specialists','p_k'),('v3/p_k_specialists','v3')]:
            m=metrics(members,gold,results[arm],labels); row[name+'_correct']=m['correct']; row[name+'_accuracy']=m['accuracy']; row[name+'_completion_rate']=m['completion_rate']; row[name+'_failed']=m['failed']
        per_patient.append(row)
    per_case=[]
    for cid in ids:
        row={'case_id':cid,'patient_group':groups[cid],'gold':gold[cid]}
        for arm,name in [('b0_common_single','b0'),('p_k_specialists','p_k'),('v3/p_k_specialists','v3')]:
            rec=results[arm][cid]; row[name+'_prediction']=pred(rec); row[name+'_status']=completion(rec); row[name+'_cost']=cost(rec)
        per_case.append(row)
    write_csv(args.out/'mtb_holdout_main_table.csv',[table[0],table[2]])
    write_csv(args.out/'mtb_holdout_ablation.csv',ablation)
    write_csv(args.out/'mtb_holdout_paired.csv',paired)
    write_csv(args.out/'mtb_holdout_per_patient_private.csv',per_patient)
    write_csv(args.out/'mtb_holdout_per_case_private.csv',per_case)
    per_class=[]
    for arm in arms:
        for lab,stats in all_metrics[arm]['per_class'].items(): per_class.append({'arm':arm,'label':lab,**stats})
    write_csv(args.out/'mtb_holdout_per_class.csv',per_class)
    metrics_json={'n':len(ids),'patients':len(set(groups[c] for c in ids)),'labels':labels,'missing_results':absent,
      'majority_reference':{'label':Counter(gold[c] for c in ids).most_common(1)[0][0],'correct':max(Counter(gold[c] for c in ids).values()),'accuracy':max(Counter(gold[c] for c in ids).values())/len(ids)},
      'metrics':all_metrics,'paired':paired,'arbitration':{k:arbitration.get(k) for k in ['triggered','v0_cases_copied','changed','extra_calls','extra_input_tokens','extra_output_tokens','concurrency']}}
    (args.out/'mtb_holdout_metrics.json').write_text(json.dumps(metrics_json,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'n':len(ids),'main':table[0:3:2],'paired':paired,'arbitration':ablation[1]},ensure_ascii=False))
if __name__=='__main__': main()
