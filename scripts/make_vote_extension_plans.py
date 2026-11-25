from __future__ import annotations
import argparse,copy,hashlib,json,re
from collections import Counter,defaultdict
from pathlib import Path

from oncofusion.datasets import read_jsonl
from oncofusion.evidence import fragment_documents,visible_case
from oncofusion.schemas import CaseInput
from oncofusion.voting import eligible_vote_roles

STOP={"what","which","when","where","does","did","has","have","had","the","and","with","from","that","this","these","those","patient","case","evidence","support","claim","show","shown","reported","study","about","based","among","into","were","was","are","is","for","after","before","between","their","there","they","them","into","than","then","more","less","not","any","all","does","using"}
def digest(s): return hashlib.sha256(s.encode()).hexdigest()
def rank(seed,kind,value): return digest(f"{seed}:{kind}:{value}")
def read_plan(p): return json.loads(Path(p).read_text())
def query_for(v): return " ".join(filter(None,[v.question,*[str(x) for x in v.entities.model_dump().values() if x]]))
def evidence_for(case):
 v=visible_case(case); q=query_for(v)
 ev,idx,cov=fragment_documents(v.documents,600,8,q,12000,role="decision")
 return v,ev,idx,cov
def group_key(name,cid,case,gold): return str(case.patient_id or gold.get(cid,{}).get("group_id") or cid)
def hash_sample(items,n,seed=0): return sorted(items,key=lambda x:rank(seed,"case",x))[:n]
def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--worktree",type=Path,required=True); ap.add_argument("--mtb-data",type=Path,required=True); ap.add_argument("--civic-data",type=Path,required=True); ap.add_argument("--out",type=Path,required=True); args=ap.parse_args()
 work=args.worktree; out=args.out; out.mkdir(parents=True,exist_ok=True)
 mtb_template=read_plan(work/"experiments/vote_v1_mtb_dev43_20261109.json"); civic_template=read_plan(work/"experiments/vote_v1_civic_dev60_20261109.json")
 def load(data):
  cases={x["id"]:CaseInput.model_validate(x) for x in read_jsonl(data/"inputs.jsonl")}
  gold={x["case_id"]:x for x in read_jsonl(data/"_gold/labels.jsonl")}
  return cases,gold
 mtb_cases,mtb_gold=load(args.mtb_data); civ_cases,civ_gold=load(args.civic_data)
 # Development sampling uses only input lengths and patient coverage for MTB; CIViC labels are used only for stratification.
 mtb_ids=list(mtb_template["case_ids"]); length={}
 mtb_groups={c:group_key("MTB",c,mtb_cases[c],mtb_gold) for c in mtb_ids}
 for cid in mtb_ids:
  v,ev,_,_=evidence_for(mtb_cases[cid]); length[cid]=sum(len(x["text"]) for x in ev)
 ordered=sorted(mtb_ids,key=lambda c:(length[c],c)); tiers=[ordered[i*len(ordered)//3:(i+1)*len(ordered)//3] for i in range(3)]
 mtb_selected=[]; per_tier=[]
 for tier in tiers:
  chosen=[]
  while len(chosen)<min(10,len(tier)):
   unused=[c for c in tier if c not in chosen]
   uncovered={mtb_groups[c] for c in unused}-{mtb_groups[c] for c in mtb_selected}
   pool=[c for c in unused if mtb_groups[c] in uncovered] or unused
   pick=min(pool,key=lambda c:rank(0,"mtb-tier",c)); chosen.append(pick); mtb_selected.append(pick)
  per_tier.append(chosen)
 if len(mtb_selected)!=30: raise ValueError(f"expected 30 MTB dev cases, got {len(mtb_selected)}")
 civ_ids=list(civic_template["case_ids"]); by_label=defaultdict(list)
 for cid in civ_ids: by_label[civ_gold[cid]["label"]].append(cid)
 civ_selected=[]
 def make_plan(template,name,ids):
  d=copy.deepcopy(template); chosen=set(ids); d["name"]=name; d["case_ids"]=[c for c in template["case_ids"] if c in chosen]; d["split"]="dev"; d["reference"]="b0_common_single"; d["bootstrap_repeats"]=2000; return d
 exp=work/"experiments/vote_extensions_20261125"
 mtb_plan=make_plan(mtb_template,"vote_extensions_mtb_dev30_20261125",mtb_selected)
 civ_plan=make_plan(civic_template,"vote_extensions_civic_dev30_20261125",civ_selected)
 (exp/"mtb_dev30.json").write_text(json.dumps(mtb_plan,ensure_ascii=False,indent=2)+"\n")
 (exp/"civic_dev30.json").write_text(json.dumps(civ_plan,ensure_ascii=False,indent=2)+"\n")
 # E02b anchor selection: require >=3 visible fragments and positive lexical overlap with the question.
 def anchors(name,cases,ids,group_lookup=None):
  candidates=[]
  for cid in ids:
   v,ev,_,_=evidence_for(cases[cid])
   if len(ev)<3: continue
   words={w.lower() for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9+_.-]{2,}",query_for(v)) if w.lower() not in STOP}
   ranked=[]
   for i,item in enumerate(ev):
    text=item.get("text",""); words_in={w.lower() for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9+_.-]{2,}",text)}
    overlap=words & words_in
    if not overlap: continue
    score=len(overlap)/(len(words)**0.5)
    ranked.append((score,i,item,sorted(overlap)))
   if not ranked: continue
   score,i,item,terms=max(ranked,key=lambda x:(x[0],-x[1]))
   candidates.append({"dataset":name,"case_id":cid,"group_id":str((group_lookup or {}).get(cid) or cases[cid].patient_id or cid),"anchor_evidence_id":item["evidence_id"],"anchor_document_id":item["document_id"],"original_evidence_index":i,"evidence_count":len(ev),"evidence_ids":[e["evidence_id"] for e in ev],"anchor_text_sha256":digest(item["text"]),"anchor_chars":len(item["text"]),"lexical_overlap_terms":terms,"selection_note":"Highest question/entity lexical-overlap fragment in the fixed visible evidence packet; selected without prediction or gold."})
  candidates.sort(key=lambda x:(rank(0,"anchor",x["case_id"]),x["case_id"]))
  result=[]; groups=set()
  for x in candidates:
   if x["group_id"] not in groups and len(result)<12: result.append(x); groups.add(x["group_id"])
  for x in candidates:
   if len(result)>=12: break
   if x not in result: result.append(x)
  return result
 mtb_groups_lookup={cid:mtb_groups[cid] for cid in mtb_selected}
 mtb_anchors=anchors("MTB",mtb_cases,mtb_selected,mtb_groups_lookup)
 civ_groups_lookup={cid:str(civ_gold[cid].get("group_id") or cid) for cid in civ_ids}
 civ_all_anchors=anchors("CIViC",civ_cases,civ_ids,civ_groups_lookup)
 anchor_ids={x["case_id"] for x in civ_all_anchors}
 for lab in ("SUPPORTS","REVISIONS","NEI"):
  eligible=[cid for cid in by_label[lab] if cid in anchor_ids]
  picks=eligible[:10]
  remaining=[cid for cid in by_label[lab] if cid not in picks]
  picks.extend(hash_sample(remaining,10-len(picks)))
  if len(picks)!=10: raise ValueError(f"CIViC dev label {lab} has fewer than 10 cases")
  civ_selected.extend(picks)
 civ_anchors=[x for x in civ_all_anchors if x["case_id"] in set(civ_selected)]
 civ_plan=make_plan(civic_template,"vote_extensions_civic_dev30_20261125",civ_selected)
 (exp/"civic_dev30.json").write_text(json.dumps(civ_plan,ensure_ascii=False,indent=2)+"\n")
 # E04 eligible MTB inputs contain molecule and pathology records plus multiple clinical blocks.
 def categories(case):
  kinds=set(); events=0
  for d in visible_case(case).documents:
   origin=(d.origin_id or "").lower(); kind=str(d.kind).lower()
   is_mol=kind=="genomics" or any(x in origin for x in ("cna","mutation","gene","variant","genom"))
   is_path=kind=="pathology" or "patholog" in origin or "histolog" in origin
   if is_mol: kinds.add("molecular")
   if is_path: kinds.add("pathology")
   if kind=="clinical": events+=len([x for x in re.split(r"\n+",d.text) if x.strip()])
  return kinds,events
 eligible=[]
 for cid in mtb_selected:
  cats,events=categories(mtb_cases[cid])
  if {"molecular","pathology"}.issubset(cats) and events>=2: eligible.append({"case_id":cid,"group_id":mtb_groups[cid],"event_blocks":events,"categories":sorted(cats),"evidence_chars":length[cid]})
 eligible.sort(key=lambda x:(rank(0,"missing",x["case_id"]),x["case_id"]))
 e04=eligible[:20]
 # E05b target at most 15 eligible cases per specialist role, independent of outcomes.
 prompt_cases={r:[] for r in ("literature","timeline","genomics","pathology","drug")}
 all_cases={**mtb_cases,**civ_cases}; all_ids={"MTB":mtb_selected,"CIViC":civ_selected}; all_gold={**mtb_gold,**civ_gold}
 for role in prompt_cases:
  candidates=[]
  for name,ids in all_ids.items():
   for cid in ids:
    vis=visible_case(all_cases[cid])
    if role in eligible_vote_roles(vis,4): candidates.append((name,cid))
  candidates=sorted(candidates,key=lambda x:(rank(0,"prompt:"+role,x[1]),x[1]))
  prompt_cases[role]=[{"dataset":n,"case_id":cid} for n,cid in candidates[:15]]
 manifest={"seed":0,"mtb_dev":{"n":30,"case_ids":mtb_plan["case_ids"],"group_count":len({mtb_groups[x] for x in mtb_plan["case_ids"]}),"length_chars_by_case":{x:length[x] for x in mtb_plan["case_ids"]},"per_length_tertile":[[x for x in bucket if x in mtb_plan["case_ids"]] for bucket in per_tier]},"civic_dev":{"n":30,"case_ids":civ_plan["case_ids"],"labels":dict(Counter(civ_gold[x]["label"] for x in civ_plan["case_ids"])),"group_count":len({civ_gold[x].get("group_id",x) for x in civ_plan["case_ids"]})},"e02b_anchor_candidates":{"MTB":mtb_anchors,"CIViC":civ_anchors},"e04_mtb_cases":e04,"e05b_role_case_ids":prompt_cases}
 (out/"development_selection_private.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
 public={"seed":0,"mtb_cases":30,"mtb_groups":manifest["mtb_dev"]["group_count"],"civic_cases":30,"civic_labels":manifest["civic_dev"]["labels"],"civic_groups":manifest["civic_dev"]["group_count"],"mtb_evidence_position_eligible":len(mtb_anchors),"civic_evidence_position_eligible":len(civ_anchors),"mtb_robustness_eligible":len(e04),"prompt_targets_per_role":{r:len(v) for r,v in prompt_cases.items()},"gold_use":"CIViC labels used only for stratified sample selection and evaluation; never in model payload."}
 (work/"artifacts/vote_extensions_20261125/DEVELOPMENT_SELECTION.json").write_text(json.dumps(public,ensure_ascii=False,indent=2)+"\n")
 print(json.dumps(public,ensure_ascii=False))
if __name__=="__main__": main()
