from __future__ import annotations
import argparse, csv, json, random, sys
from collections import defaultdict
from pathlib import Path
from statistics import mean
sys.path.insert(0, str(Path(__file__).resolve().parent / 'scripts'))
import analyze_vote_extensions as a


def read_csv(path):
    with open(path, newline='', encoding='utf-8') as f: return list(csv.DictReader(f))
def ci_cluster(ids, values, groups, repeats=2000, seed=0):
    by=defaultdict(list)
    for cid in ids: by[groups[cid]].append(cid)
    keys=sorted(by); rng=random.Random(seed); out=[]
    for _ in range(repeats):
        picked=[rng.choice(keys) for _ in keys]
        sample=[cid for key in picked for cid in by[key]]
        out.append(mean(values[c] for c in sample) if sample else 0.0)
    out.sort()
    return [out[int(.025*(len(out)-1))],out[int(.975*(len(out)-1))]] if out else [None,None]
def macro_from_confusion(labels, matrix):
    f=[]
    for lab in labels:
        tp=matrix[lab].get(lab,0.0)
        fp=sum(matrix[y].get(lab,0.0) for y in labels if y!=lab)
        fn=sum(matrix[lab].values())-tp
        p=tp/(tp+fp) if tp+fp else 0.0; r=tp/(tp+fn) if tp+fn else 0.0
        f.append(2*p*r/(p+r) if p+r else 0.0)
    return mean(f) if f else None

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--mtb-data',type=Path,required=True); p.add_argument('--civic-data',type=Path,required=True)
    p.add_argument('--mtb-run',type=Path,required=True); p.add_argument('--civic-run',type=Path,required=True)
    p.add_argument('--tables',type=Path,required=True)
    x=p.parse_args(); tab=x.tables
    specs={'MTB':(x.mtb_data,x.mtb_run,('a',)),'CIViC':(x.civic_data,x.civic_run,('a',))}
    role_paired=[]; member_summary=[]; length_paired=[]; exclusive=[]
    for dataset,(data_path,run_path,_) in specs.items():
        cases,gold,groups=a.load_dataset(data_path)
        arms=('b0_common_single','g_k4','p_k_specialists','v3/p_k_specialists') if dataset=='MTB' else ('b0_common_single','p_k_specialists','v3/p_k_specialists')
        res=a.load_results(run_path,arms)
        ids=sorted(cid for cid in gold if cid in res['b0_common_single'])
        labs=('SUPPORTS','REVISIONS','NEI') if dataset=='CIViC' else sorted({lab for cid in ids for lab in a.case_labels(cases[cid])})
        pk=res['p_k_specialists']
        for role in a.ROLES:
            active=[cid for cid in ids if cid in pk and role in (pk[cid].get('vote_result') or {}).get('planned_roles',[])]
            if not active:
                role_paired.append({'dataset':dataset,'role':role,'status':'N/A','n':0}); continue
            for cid in ids:
                r=pk.get(cid)
                if not r:
                    pv=av=None; planned=[]
                else:
                    vr=r.get('vote_result') or {}; planned=list(vr.get('planned_roles',[])); pv=a.pred(r)
                    if role in planned:
                        kept=[b for b in r.get('ballots',[]) if b.get('role')!=role]
                        new_planned=[z for z in planned if z!=role]
                        if not new_planned: av=None
                        else:
                            vv=a.reaggregate(cid,cases[cid],kept,new_planned); av=vv.label if vv.completion_status!='failed' else None
                    else: av=pv
                role_paired.append({'dataset':dataset,'case_id':cid,'group_id':groups[cid],'role':role,'applicable':int(role in planned),'gold':gold[cid],'full_prediction':pv,'ablated_prediction':av,'full_status':a.completion(r),'ablated_status':'not_applicable_no_members' if r and role in planned and len(planned)==1 else ('failed' if av is None else 'valid'),'full_correct':int(pv==gold[cid]),'ablated_correct':int(av==gold[cid]),'changed_to_correct':int(pv!=gold[cid] and av==gold[cid]),'changed_to_wrong':int(pv==gold[cid] and av!=gold[cid])})
        # Input-length paired metrics; length thirds are frozen before label scoring.
        length_map={q['case_id']:q['length_group'] for q in read_csv(tab/'length_groups.csv') if q['dataset']==dataset}
        for lg in ('short','medium','long'):
            cohort=[cid for cid in ids if length_map.get(cid)==lg]
            for arm in ('p_k_specialists','v3/p_k_specialists'):
                if arm not in res: continue
                pair=[cid for cid in cohort if a.pred(res['b0_common_single'].get(cid)) is not None and a.pred(res[arm].get(cid)) is not None]
                vals={cid:float(a.pred(res[arm].get(cid))==gold[cid])-float(a.pred(res['b0_common_single'].get(cid))==gold[cid]) for cid in cohort}
                length_paired.append({'dataset':dataset,'length_group':lg,'candidate':arm,'n':len(cohort),'candidate_correct':sum(a.pred(res[arm].get(c))==gold[c] for c in cohort),'b0_correct':sum(a.pred(res['b0_common_single'].get(c))==gold[c] for c in cohort),'candidate_accuracy':a.metrics(cohort,gold,res[arm],labs)['accuracy'],'b0_accuracy':a.metrics(cohort,gold,res['b0_common_single'],labs)['accuracy'],'accuracy_diff':a.metrics(cohort,gold,res[arm],labs)['accuracy']-a.metrics(cohort,gold,res['b0_common_single'],labs)['accuracy'],'both_valid_n':len(pair),'both_valid_candidate_accuracy':a.metrics(pair,gold,res[arm],labs)['accuracy'],'both_valid_b0_accuracy':a.metrics(pair,gold,res['b0_common_single'],labs)['accuracy'],'changed_to_correct':sum(a.pred(res['b0_common_single'].get(c))!=gold[c] and a.pred(res[arm].get(c))==gold[c] for c in pair),'changed_to_wrong':sum(a.pred(res['b0_common_single'].get(c))==gold[c] and a.pred(res[arm].get(c))!=gold[c] for c in pair),'group_bootstrap_95ci_accuracy_diff':ci_cluster(cohort,vals,groups)})
        # Expected per-case subset performance; cases, not role combinations, carry equal weight.
        mc=read_csv(tab/'member_count_per_case.csv'); subsets=read_csv(tab/'member_subsets.csv')
        cm=[r for r in mc if r['dataset']==dataset]; ss=[r for r in subsets if r['dataset']==dataset]
        for mode in ('common_K4','all_K_ge_k'):
            for k in range(1,5):
                cohort=[r['case_id'] for r in cm if int(r['k'])==k and ((int(r['original_k'])==4) if mode=='common_K4' else int(r['original_k'])>=k)]
                cohort=sorted(set(cohort))
                if not cohort: continue
                bycase=defaultdict(list)
                for r in ss:
                    if r['case_id'] in cohort and int(r['k'])==k: bycase[r['case_id']].append(r)
                case_acc={cid:mean(float(rr['correct']) for rr in bycase[cid]) for cid in cohort}
                case_cov={cid:mean(float(rr['prediction'] not in ('','None')) for rr in bycase[cid]) for cid in cohort}
                matrix={y:defaultdict(float) for y in labs}; confusion_weight=0
                for cid in cohort:
                    rows=bycase[cid]; weight=1/len(rows)
                    for rr in rows:
                        y=gold[cid]; z=rr['prediction'] or 'NO_VALID_ANSWER'; matrix[y][z]+=weight; confusion_weight+=weight
                count=sum(case_acc.values()); b0=a.metrics(cohort,gold,res['b0_common_single'],labs)
                member_summary.append({'dataset':dataset,'cohort':mode,'k':k,'n_cases':len(cohort),'mean_case_expected_accuracy':mean(case_acc.values()),'macro_f1_expected_confusion':macro_from_confusion(labs,matrix),'mean_case_expected_completion':mean(case_cov.values()),'mean_combination_count':mean(len(bycase[c]) for c in cohort),'b0_accuracy_same_cases':b0['accuracy'],'accuracy_diff_vs_b0':mean(case_acc.values())-b0['accuracy'],'group_bootstrap_95ci_accuracy_diff':ci_cluster(cohort,{c:case_acc[c]-float(a.pred(res['b0_common_single'].get(c))==gold[c]) for c in cohort},groups),'confusion_expected':dict(matrix),'trigger_rate_topshare_lt_075_or_margin_lt_025':None})
        # Strict exclusivity for each expert: all other planned voters valid and wrong.
        for role in sorted({r for cid in ids if cid in pk for r in (pk[cid].get('vote_result') or {}).get('planned_roles',[])}):
            planned_ids=[cid for cid in ids if cid in pk and role in (pk[cid].get('vote_result') or {}).get('planned_roles',[])]
            strict=0
            for cid in planned_ids:
                ballots=pk[cid].get('ballots',[]); target=next((b for b in ballots if b.get('role')==role),{})
                others=[b for b in ballots if b.get('role')!=role and b.get('role') in (pk[cid].get('vote_result') or {}).get('planned_roles',[])]
                if target.get('status')=='vote' and target.get('label')==gold[cid] and len(others)==len((pk[cid].get('vote_result') or {}).get('planned_roles',[]))-1 and all(b.get('status')=='vote' and b.get('label')!=gold[cid] for b in others): strict+=1
            exclusive.append({'dataset':dataset,'role':role,'planned_n':len(planned_ids),'strict_exclusive_correct_n':strict})
    a.write_csv(tab/'role_ablation_paired.csv',role_paired)
    a.write_csv(tab/'length_paired.csv',length_paired)
    a.write_csv(tab/'member_count.csv',member_summary)
    a.write_csv(tab/'expert_strict_exclusive.csv',exclusive)
    print(json.dumps({'role_paired_rows':len(role_paired),'length_paired_rows':len(length_paired),'member_count_rows':len(member_summary),'strict_exclusive_rows':len(exclusive)}))
if __name__=='__main__': main()
