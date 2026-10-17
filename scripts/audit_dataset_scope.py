"""Audit task fit and modality coverage before spending a model budget."""
import argparse
import json
from collections import Counter
from pathlib import Path

from oncofusion.evaluation import load_evaluation
from oncofusion.datasets import validate_patient_groups, validate_splits
from oncofusion.specialists import coverage

p = argparse.ArgumentParser()
p.add_argument("--dataset", type=Path, required=True)
p.add_argument("--out", type=Path, required=True)
p.add_argument("--require-heterogeneous", action="store_true")
a = p.parse_args()
cases, gold = load_evaluation(a.dataset / "inputs.jsonl", a.dataset / "_gold/labels.jsonl")
validate_splits(gold)
validate_patient_groups(cases, gold)
scopes = [coverage(c) for c in cases]
report = {"cases": len(cases), "patients_or_article_groups": len({c.patient_id for c in cases}),
          "tasks": dict(Counter(c.task for c in cases)),
          "splits": dict(Counter(g.split for g in gold)),
          "heterogeneous_cases": sum(c["heterogeneous_input"] for c in scopes),
          "document_kind_case_counts": dict(Counter(k for c in scopes for k in c["document_kinds"])),
          "applicable_cases_by_role": {r: sum(c["roles"][r]["applicable"] for c in scopes)
                                       for r in scopes[0]["roles"]},
          "interpretation": "Input coverage only. Treatment superiority and semantic agent benefit require separate labels and real evaluation."}
a.out.parent.mkdir(parents=True, exist_ok=True)
a.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report))
if a.require_heterogeneous and not report["heterogeneous_cases"]:
    raise SystemExit("no heterogeneous cases: use this corpus only for component evaluation")
