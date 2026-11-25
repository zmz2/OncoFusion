from __future__ import annotations
import argparse, csv, hashlib, itertools, json, math, random
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

from oncofusion.evidence import fragment_documents, visible_case
from oncofusion.schemas import Ballot, CaseInput, RunConfig
from oncofusion.voting import aggregate_ballots

ARMS = ("b0_common_single", "g_k4", "p_k_specialists", "v3/p_k_specialists")
ROLES = ("literature", "timeline", "genomics", "pathology", "drug")


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]

def load_dataset(path):
    cases = {x["id"]: CaseInput.model_validate(x) for x in read_jsonl(Path(path)/"inputs.jsonl")}
    gold = {x["case_id"]: x["label"] for x in read_jsonl(Path(path)/"_gold/labels.jsonl")}
    groups = {x["case_id"]: str(x.get("group_id") or x.get("patient_id") or x["case_id"]) for x in read_jsonl(Path(path)/"_gold/labels.jsonl")}
    return cases, gold, groups

def result_path(run, arm, cid):
    p = Path(run)/arm/"0"/(cid+".json")
    if p.exists(): return p
    p = Path(run)/arm/"0"/(cid+".failed.json")
    return p if p.exists() else None

def load_results(run, arms):
    out = {arm:{} for arm in arms}
    for arm in arms:
        d = Path(run)/arm/"0"
        if not d.exists(): continue
        for p in d.glob("*.json"):
            if p.name == "summary.json" or p.name.endswith(".failed.json"): continue
            rec = json.loads(p.read_text(encoding="utf-8"))
            out[arm][rec["case_id"]] = rec
        for p in d.glob("*.failed.json"):
            rec = json.loads(p.read_text(encoding="utf-8"))
            out[arm][rec["case_id"]] = rec
    return out

def pred(rec):
    if not rec: return None
    vr = rec.get("vote_result") or {}
    if vr.get("completion_status") == "failed": return None
    label = vr.get("label")
    return label if label not in (None, "") else None

def completion(rec):
    if not rec: return "missing"
    status = (rec.get("vote_result") or {}).get("completion_status")
    return status if status in {"full", "degraded", "failed"} else "failed"

def metrics(case_ids, gold, predictions, labels):
    n=len(case_ids); matrix={g:{p:0 for p in [*labels,"NO_VALID_ANSWER"]} for g in labels}
    correct=0; valid=0; full=degraded=failed=0
    for cid in case_ids:
        y=gold[cid]; rec=predictions.get(cid); p=pred(rec)
        if completion(rec)=="full": full+=1
        elif completion(rec)=="degraded": degraded+=1
        else: failed+=1
        if p is not None:
            valid+=1; matrix[y][p]+=1
            correct += int(p==y)
        else:
            matrix[y]["NO_VALID_ANSWER"]+=1
    per={}; f1s=[]
    for lab in labels:
        tp=matrix[lab][lab]
        fp=sum(matrix[g][lab] for g in labels if g!=lab)
        fn=sum(matrix[lab][p] for p in matrix[lab] if p!=lab)
        precision=tp/(tp+fp) if tp+fp else 0.0
        recall=tp/(tp+fn) if tp+fn else 0.0
        f1=2*precision*recall/(precision+recall) if precision+recall else 0.0
        per[lab]={"precision":precision,"recall":recall,"f1":f1,"support":sum(matrix[lab].values())}
        f1s.append(f1)
    return {"n":n,"correct":correct,"accuracy":correct/n if n else None,"macro_f1":mean(f1s) if f1s else None,
            "completion_rate":valid/n if n else None,"full":full,"degraded":degraded,"failed":failed,
            "per_class":per,"confusion":matrix}

def write_csv(path, rows):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    if not rows: path.write_text("",encoding="utf-8"); return
    fields=[]
    for row in rows:
        for key in row:
            if key not in fields: fields.append(key)
    with path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for row in rows:
            w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict,tuple)) else v for k,v in row.items()})

def cluster_bootstrap(case_ids, gold, preds_a, preds_b, groups, repeats=2000, seed=0):
    by_group=defaultdict(list)
    for cid in case_ids: by_group[groups[cid]].append(cid)
    keys=sorted(by_group); rng=random.Random(seed); values=[]
    for _ in range(repeats):
        picked=[rng.choice(keys) for _ in keys]
        sample=[cid for g in picked for cid in by_group[g]]
        if not sample: continue
        da=sum(pred(preds_b.get(cid))==gold[cid] for cid in sample)/len(sample)
        db=sum(pred(preds_a.get(cid))==gold[cid] for cid in sample)/len(sample)
        values.append(db-da)
    values.sort()
    if not values: return [None,None]
    return [values[int(.025*(len(values)-1))],values[int(.975*(len(values)-1))]]

def case_labels(case):
    return list(case.verification_labels) if case.task=="verification" else sorted(case.options)

def reaggregate(cid, case, ballots, planned_roles):
    pool="specialist"
    result=aggregate_ballots(case_id=cid,ballots=[Ballot.model_validate(x) for x in ballots],labels=case_labels(case),
        planned_roles=planned_roles,pool=pool,rule="v0",tie_seed=0)
    return result

def extract_lengths(case, rec):
    event = next((x for x in rec.get("trace",[]) if x.get("kind")=="agent_started"), None)
    details = (event or {}).get("details", {})
    coverage = details.get("evidence_coverage", {})
    docs = coverage.get("documents", {}) if isinstance(coverage,dict) else {}
    ids = list(details.get("evidence_ids", []))
    if docs and ids:
        return sum(int(x.get("chars_sent",0)) for x in docs.values()), ids
    config=RunConfig.model_validate(rec["config"])
    visible=visible_case(case)
    query=" ".join(filter(None,[visible.question,*[str(v) for v in visible.entities.model_dump().values() if v]]))
    evidence,index,_=fragment_documents(visible.documents,config.fragment_chars,config.max_fragments_per_document,query,config.fragment_budget,role="decision")
    return sum(len(x.get("text", "")) for x in evidence),[x["evidence_id"] for x in evidence]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--mtb-data",type=Path,required=True); ap.add_argument("--civic-data",type=Path,required=True)
    ap.add_argument("--mtb-run",type=Path,required=True); ap.add_argument("--civic-run",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args(); out=args.out; out.mkdir(parents=True,exist_ok=True)
    datasets={"MTB":(args.mtb_data,args.mtb_run,("b0_common_single","g_k4","p_k_specialists","v3/p_k_specialists")),
              "CIViC":(args.civic_data,args.civic_run,("b0_common_single","p_k_specialists","v3/p_k_specialists"))}
    all_metrics={}; all_pair=[]; all_per=[]; role_rows=[]; member_rows=[]; subset_rows=[]; length_rows=[]; expert_rows=[]; pair_rows=[]; disagreements=[]; citation_rows=[]
    for dname,(data_path,run_path,arms) in datasets.items():
        cases,gold,groups=load_dataset(data_path); results=load_results(run_path,arms)
        ids=sorted(gold)
        case_labels_union=sorted({lab for c in cases.values() for lab in case_labels(c)})
        labels=("SUPPORTS","REVISIONS","NEI") if dname=="CIViC" else case_labels_union
        run_ids=sorted(set(ids)&set(results["b0_common_single"]))
        if dname=="MTB" and len(run_ids)!=43: raise ValueError(f"MTB43 roster mismatch: {len(run_ids)}")
        if dname=="CIViC" and len(run_ids)!=117: raise ValueError(f"CIViC117 roster mismatch: {len(run_ids)}")
        all_metrics[dname]={}
        majority=max(Counter(gold[c] for c in run_ids).values())
        all_metrics[dname]["majority_reference"]={"n":len(run_ids),"correct":majority,"accuracy":majority/len(run_ids)}
        for arm in arms:
            mm=metrics(run_ids,gold,results[arm],labels); all_metrics[dname][arm]=mm
            all_metrics[dname][arm]["run_cases_present"]=len(results[arm])
            all_metrics[dname][arm]["case_ids"]=None
            for lab in labels: all_per.append({"dataset":dname,"arm":arm,"label":lab,**mm["per_class"][lab]})
        for arm in arms:
            if arm=="b0_common_single": continue
            both=[]; changed_to_right=changed_to_wrong=recovered=lost=0
            for cid in run_ids:
                a=results["b0_common_single"].get(cid); b=results[arm].get(cid); pa,pb=pred(a),pred(b)
                va,vb=pa is not None,pb is not None
                ca,cb=pa==gold[cid],pb==gold[cid]
                if va and vb:
                    both.append(cid); changed_to_right+=int(not ca and cb); changed_to_wrong+=int(ca and not cb)
                recovered+=int(not va and vb and cb); lost+=int(va and ca and not vb)
            ci=cluster_bootstrap(run_ids,gold,results["b0_common_single"],results[arm],groups)
            comp_a=metrics(both,gold,results["b0_common_single"],labels); comp_b=metrics(both,gold,results[arm],labels)
            all_pair.append({"dataset":dname,"candidate":arm,"n":len(run_ids),"b0_accuracy":all_metrics[dname]["b0_common_single"]["accuracy"],"candidate_accuracy":all_metrics[dname][arm]["accuracy"],"accuracy_diff":all_metrics[dname][arm]["accuracy"]-all_metrics[dname]["b0_common_single"]["accuracy"],"group_bootstrap_95ci":ci,"both_valid_n":len(both),"both_valid_b0_accuracy":comp_a["accuracy"],"both_valid_candidate_accuracy":comp_b["accuracy"],"both_valid_changed_to_correct":changed_to_right,"both_valid_changed_to_wrong":changed_to_wrong,"b0_failure_candidate_correct":recovered,"b0_correct_candidate_failure":lost})
        # E01 role deletion and deterministic aggregation replay.
        pk=results["p_k_specialists"]
        for role in ROLES:
            participated=sum(role in (pk[cid].get("vote_result") or {}).get("planned_roles",[]) for cid in run_ids if cid in pk)
            if participated==0:
                role_rows.append({"dataset":dname,"role":role,"status":"N/A","planned_n":0}); continue
            ablated={}
            for cid in run_ids:
                rec=pk.get(cid)
                if not rec:
                    ablated[cid]=None; continue
                vr=rec.get("vote_result") or {}; planned=list(vr.get("planned_roles",[])); ballots=rec.get("ballots",[])
                replay=reaggregate(cid,cases[cid],ballots,planned)
                if replay.label!=vr.get("label") or replay.completion_status!=vr.get("completion_status"):
                    raise ValueError(f"saved P-K aggregation does not replay: {dname}/{cid}")
                if role not in planned:
                    ablated[cid]=rec; continue
                remain=[r for r in planned if r!=role]
                kept=[b for b in ballots if b.get("role")!=role]
                vote=reaggregate(cid,cases[cid],kept,remain)
                ablated[cid]={"vote_result":{"label":vote.label,"completion_status":vote.completion_status}}
            full=metrics(run_ids,gold,pk,labels); drop=metrics(run_ids,gold,ablated,labels)
            active=[cid for cid in run_ids if cid in pk and role in (pk[cid].get("vote_result") or {}).get("planned_roles",[])]
            full_active=metrics(active,gold,pk,labels); drop_active=metrics(active,gold,ablated,labels)
            both=[cid for cid in run_ids if pred(pk.get(cid)) is not None and pred(ablated.get(cid)) is not None]
            ma=metrics(both,gold,pk,labels); mb=metrics(both,gold,ablated,labels)
            role_rows.append({"dataset":dname,"role":role,"status":"applicable","planned_n":participated,"all_n":len(run_ids),"full_accuracy":full["accuracy"],"leave_one_out_accuracy":drop["accuracy"],"accuracy_diff":drop["accuracy"]-full["accuracy"],"full_macro_f1":full["macro_f1"],"leave_one_out_macro_f1":drop["macro_f1"],"active_n":len(active),"active_full_accuracy":full_active["accuracy"],"active_ablated_accuracy":drop_active["accuracy"],"both_valid_n":len(both),"both_valid_accuracy_full":ma["accuracy"],"both_valid_accuracy_ablated":mb["accuracy"],"both_valid_changed_to_correct":sum(pred(pk.get(c))!=gold[c] and pred(ablated.get(c))==gold[c] for c in both),"both_valid_changed_to_wrong":sum(pred(pk.get(c))==gold[c] and pred(ablated.get(c))!=gold[c] for c in both)})
        # E03: enumerate all role subsets, average combinations within case, never choose best.
        for cid in run_ids:
            rec=pk.get(cid)
            if not rec: continue
            planned=list((rec.get("vote_result") or {}).get("planned_roles",[])); ballots=rec.get("ballots",[]); k=len(planned)
            if not k: continue
            for size in range(1,k+1):
                combos=list(itertools.combinations(planned,size)); per_case=[]
                for combo in combos:
                    bs=[b for b in ballots if b.get("role") in combo]
                    v=reaggregate(cid,cases[cid],bs,list(combo))
                    pr=v.label if v.completion_status!="failed" else None
                    ok=pr==gold[cid]
                    per_case.append((pr,ok,v.completion_status))
                    subset_rows.append({"dataset":dname,"case_id":cid,"group_id":groups[cid],"original_k":k,"k":size,"subset_roles":list(combo),"prediction":pr,"gold":gold[cid],"correct":int(ok),"status":v.completion_status})
                member_rows.append({"dataset":dname,"case_id":cid,"group_id":groups[cid],"original_k":k,"k":size,"combination_count":len(combos),"expected_accuracy":sum(x[1] for x in per_case)/len(per_case),"expected_completion_rate":sum(x[0] is not None for x in per_case)/len(per_case),"roles":planned})
        # E06 expert complements and per-case disagreement.
        applicable=sorted({r for cid in run_ids if cid in pk for r in (pk[cid].get("vote_result") or {}).get("planned_roles",[])})
        for role in applicable:
            planned_ids=[cid for cid in run_ids if cid in pk and role in (pk[cid].get("vote_result") or {}).get("planned_roles",[])]
            valid_ids=[cid for cid in planned_ids if next((b for b in pk[cid].get("ballots",[]) if b.get("role")==role),{}).get("status")=="vote"]
            correct=sum(next((b for b in pk[cid].get("ballots",[]) if b.get("role")==role),{}).get("label")==gold[cid] for cid in valid_ids)
            exclusive=0
            for cid in valid_ids:
                b=next(b for b in pk[cid].get("ballots",[]) if b.get("role")==role)
                if b.get("label")==gold[cid] and all((bb.get("status")!="vote" or bb.get("label")!=gold[cid]) for bb in pk[cid].get("ballots",[]) if bb.get("role")!=role): exclusive+=1
            expert_rows.append({"dataset":dname,"role":role,"planned_n":len(planned_ids),"valid_n":len(valid_ids),"failed_or_abstain_n":len(planned_ids)-len(valid_ids),"all_planned_vote_accuracy":correct/len(planned_ids) if planned_ids else None,"valid_vote_accuracy":correct/len(valid_ids) if valid_ids else None,"exclusive_correct_n":exclusive,"vote_agreement_with_full_aggregate":sum(next((b for b in pk[c].get("ballots",[]) if b.get("role")==role),{}).get("label")==pred(pk[c]) for c in valid_ids)/len(valid_ids) if valid_ids else None})
        for ra,rb in itertools.combinations(applicable,2):
            both=[]
            for cid in run_ids:
                if cid not in pk: continue
                bs={b.get("role"):b for b in pk[cid].get("ballots",[])}
                planned=(pk[cid].get("vote_result") or {}).get("planned_roles",[])
                if ra in planned and rb in planned and bs.get(ra,{}).get("status")=="vote" and bs.get(rb,{}).get("status")=="vote": both.append((cid,bs[ra],bs[rb]))
            n=len(both)
            both_wrong=sum(a.get("label")!=gold[c] and b.get("label")!=gold[c] for c,a,b in both)
            both_right=sum(a.get("label")==gold[c] and b.get("label")==gold[c] for c,a,b in both)
            only_a=sum(a.get("label")==gold[c] and b.get("label")!=gold[c] for c,a,b in both)
            only_b=sum(a.get("label")!=gold[c] and b.get("label")==gold[c] for c,a,b in both)
            disagree=sum(a.get("label")!=b.get("label") for c,a,b in both)
            pair_rows.append({"dataset":dname,"role_a":ra,"role_b":rb,"joint_valid_n":n,"both_wrong_n":both_wrong,"both_wrong_rate":both_wrong/n if n else None,"both_correct_n":both_right,"both_correct_rate":both_right/n if n else None,"only_a_correct_n":only_a,"only_b_correct_n":only_b,"prediction_disagreement_n":disagree,"prediction_disagreement_rate":disagree/n if n else None})
        for cid in run_ids:
            rec=pk.get(cid)
            if not rec: continue
            ballots=rec.get("ballots",[]); planned=(rec.get("vote_result") or {}).get("planned_roles",[])
            valid=[b for b in ballots if b.get("status")=="vote" and b.get("label") is not None]
            labels_now={b["label"] for b in valid}
            disagreements.append({"dataset":dname,"case_id":cid,"group_id":groups[cid],"planned_votes":len(planned),"valid_votes":len(valid),"distinct_valid_labels":len(labels_now),"all_planned_valid":len(valid)==len(planned),"unanimous_valid":len(labels_now)<=1,"top_share":(rec.get("vote_result") or {}).get("top_share"),"any_expert_correct":int(any(b.get("label")==gold[cid] for b in valid)),"gold":gold[cid],"p_k_label":pred(rec)})
        # E02a: reconstruct exact evidence snapshot and fixed length thirds.
        b0=results["b0_common_single"]; pk_results=results["p_k_specialists"]; v3=results.get("v3/p_k_specialists",{})
        lens=[]
        for cid in run_ids:
            rec=b0.get(cid) or pk_results.get(cid)
            if not rec: continue
            chars,eids=extract_lengths(cases[cid],rec)
            for other in (pk_results.get(cid),v3.get(cid)):
                if other:
                    _,other_ids=extract_lengths(cases[cid],other)
                    if other_ids!=eids: raise ValueError(f"evidence differs across arms {dname}/{cid}")
            lens.append({"case_id":cid,"group_id":groups[cid],"evidence_chars":chars,"original_text_chars":sum(len(d.text) for d in visible_case(cases[cid]).documents),"evidence_ids":eids})
        lens.sort(key=lambda x:(x["evidence_chars"],x["case_id"]))
        n=len(lens)
        for i,row in enumerate(lens): row["length_group"]=("short","medium","long")[min(2,(i*3)//n)]
        for row in lens:
            length_rows.append({"dataset":dname,**row})
        for lg in ("short","medium","long"):
            cids=[r["case_id"] for r in lens if r["length_group"]==lg]
            if not cids: continue
            for arm in ("b0_common_single","p_k_specialists","v3/p_k_specialists"):
                if arm not in results: continue
                mm=metrics(cids,gold,results[arm],labels)
                all_metrics[dname].setdefault("length_groups",{}).setdefault(lg,{})[arm]=mm
        # E08 fixed 12 per dataset, selected by group-aware hash order, no correctness conditioning.
        by_group=defaultdict(list)
        for cid in run_ids: by_group[groups[cid]].append(cid)
        ranked_groups=sorted(by_group,key=lambda g:hashlib.sha256(("0:"+g).encode()).hexdigest())
        chosen=[]
        for group in ranked_groups:
            if len(chosen)>=12: break
            chosen.append(min(by_group[group],key=lambda c:hashlib.sha256(("0:"+c).encode()).hexdigest()))
        if len(chosen)<12:
            rest=sorted(set(run_ids)-set(chosen),key=lambda c:hashlib.sha256(("0:"+c).encode()).hexdigest())
            chosen.extend(rest[:12-len(chosen)])
        for cid in chosen:
            for arm in ("b0_common_single","v3/p_k_specialists"):
                rec=results.get(arm,{}).get(cid)
                if not rec: citation_rows.append({"dataset":dname,"case_id":cid,"group_id":groups[cid],"arm":arm,"status":"missing_result"}); continue
                visible=visible_case(cases[cid]); docs={d.id:d.text for d in visible.documents}
                citations=(rec.get("decision") or {}).get("citations",[])
                for idx,c in enumerate(citations):
                    doc=c.get("document_id"); start=c.get("start"); end=c.get("end"); quote=c.get("quote","")
                    valid=False; reason="unsupported citation shape"
                    if doc in docs and isinstance(start,int) and isinstance(end,int):
                        valid=0<=start<=end<=len(docs[doc]) and docs[doc][start:end]==quote
                        reason="exact quote match" if valid else "offset or quote mismatch"
                    citation_rows.append({"dataset":dname,"case_id":cid,"group_id":groups[cid],"arm":arm,"citation_index":idx,"document_id":doc,"citation_shape":list(c),"mechanical_valid":valid,"mechanical_reason":reason,"semantic_status":"pending AI-assisted review"})
                if not citations: citation_rows.append({"dataset":dname,"case_id":cid,"group_id":groups[cid],"arm":arm,"status":"no_final_citations","semantic_status":"N/A"})
    write_csv(out/"historical_recheck.csv",[{"dataset":d,"arm":a,**{k:v for k,v in m.items() if k not in {"per_class","confusion","case_ids","length_groups"}}} for d,ms in all_metrics.items() for a,m in ms.items() if a in ARMS and isinstance(m,dict)])
    write_csv(out/"historical_per_class.csv",all_per); write_csv(out/"historical_paired.csv",all_pair)
    write_csv(out/"role_ablation.csv",role_rows); write_csv(out/"member_subsets.csv",subset_rows); write_csv(out/"member_count_per_case.csv",member_rows)
    write_csv(out/"length_groups.csv",length_rows); write_csv(out/"expert_metrics.csv",expert_rows); write_csv(out/"pairwise_error_overlap.csv",pair_rows); write_csv(out/"expert_disagreement_cases.csv",disagreements); write_csv(out/"citation_audit.csv",citation_rows)
    (out/"metrics.json").write_text(json.dumps(all_metrics,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"datasets":{d:{a:{"n":m.get("n"),"correct":m.get("correct"),"accuracy":m.get("accuracy"),"macro_f1":m.get("macro_f1"),"completion_rate":m.get("completion_rate")} for a,m in v.items() if a in ARMS and isinstance(m,dict)} for d,v in all_metrics.items()},"role_rows":len(role_rows),"member_rows":len(member_rows),"length_rows":len(length_rows),"pair_rows":len(pair_rows),"citation_rows":len(citation_rows)},ensure_ascii=False))

if __name__=="__main__": main()
