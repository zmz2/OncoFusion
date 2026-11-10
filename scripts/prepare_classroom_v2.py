"""Prepare three fixed classroom inputs privately; never copy source texts into Git."""
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from oncofusion.classroom import digest
from oncofusion.engine import implementation_digest
from oncofusion.evidence import fragment_documents, visible_case
from oncofusion.schemas import CaseInput


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--plan-out", type=Path)
    args = parser.parse_args()
    source = args.project
    run = source / "results/v1/vote_v1_mtb_dev43_20261110_sampling_run1"
    case_specs = [
        ("case-01", "mtb-P-0027883-q3", "疾病进展判断", "依据当前已知资料，判断未来12个月是否发生疾病进展。"),
        ("case-02", "mtb-P-0027883-q4", "生存结局判断", "依据当前已知资料，判断未来12个月是否仍存活。"),
        ("case-03", "mtb-P-0022916-q1", "分歧与选择性仲裁", "依据当前已知资料，判断未来12个月是否仍存活。"),
    ]
    inputs = {r["id"]: r for r in map(json.loads, (source / "data/mtbbench/inputs.jsonl").read_text().splitlines())}
    labels = {r["case_id"]: r["label"] for r in map(json.loads, (source / "data/mtbbench/_gold/labels.jsonl").read_text().splitlines())}
    audit = json.loads((run / "audit.json").read_text())
    configs, cases, history, selected_gold = {}, [], {}, {}
    (args.out / "inputs").mkdir(parents=True, exist_ok=True)
    (args.out / "history").mkdir(exist_ok=True)
    (args.out / "new").mkdir(exist_ok=True)
    for alias, case_id, title, question_zh in case_specs:
        record_path = run / "v3/p_k_specialists/0" / (case_id + ".json")
        result = json.loads(record_path.read_text())
        base = json.loads((run / "b0_common_single/0" / (case_id + ".json")).read_text())
        configs["B0"] = base["config"]
        configs["OncoFusion"] = {**result["config"], "max_calls": 15}
        visible = visible_case(CaseInput.model_validate(inputs[case_id]))
        query = " ".join(filter(None, [visible.question, *[str(v) for v in visible.entities.model_dump().values() if v]]))
        evidence, _, coverage = fragment_documents(visible.documents, configs["B0"]["fragment_chars"],
            configs["B0"]["max_fragments_per_document"], query, configs["B0"]["fragment_budget"], role="decision")
        cases.append({"alias": alias, "source_case_id": case_id, "title": title, "question_zh": question_zh,
                      "input_fingerprint": digest(inputs[case_id]), "evidence_fingerprint": digest(evidence),
                      "evidence_ids": [e["evidence_id"] for e in evidence],
                      "visible_characters": coverage["chars_total"], "selected_characters": coverage["chars_sent"]})
        (args.out / "inputs" / (alias + ".json")).write_text(json.dumps(inputs[case_id], ensure_ascii=False, indent=2))
        shutil.copyfile(record_path, args.out / "history" / (alias + ".json"))
        history[alias] = {"path": str(record_path), "result_sha256": hashlib.sha256(record_path.read_bytes()).hexdigest(),
                          "commit": audit["git_commit"], "implementation_digest": audit["implementation_digest"],
                          "timestamp": "2026-11-10 (original record has no per-case UTC timestamp)"}
        selected_gold[alias] = labels[case_id]
        if alias == "case-03":
            arb = result["vote_result"]["arbitration"]
            assert result["status"] == "completed" and arb["status"] == "completed"
            assert arb["initial_label"] != labels[case_id] and arb["final_label"] == labels[case_id]
    protocol = {"batch_id": "classroom-web-v2-20261110", "cases": cases, "configs": configs,
                "history": history, "source_code_commit": "e4711bada390b32a28795e5128f2ebb00e4a2a9e",
                "code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                "implementation_digest": implementation_digest(),
                "executions": 6, "max_calls": 54, "global_api_concurrency": 20,
                "purpose": "Classroom end-to-end verification only; never replace MTB43 results.",
                "source_original_publication": "not cleared; public view omits raw clinical texts"}
    (args.out / "protocol.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2))
    (args.out / "labels.json").write_text(json.dumps(selected_gold))
    if args.plan_out:
        args.plan_out.parent.mkdir(parents=True, exist_ok=True)
        args.plan_out.write_text(json.dumps({k: v for k, v in protocol.items()
            if k not in {"history", "code_commit", "implementation_digest"}}, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"prepared": str(args.out), "cases": len(cases), "executions": 6, "max_calls": 54}))


if __name__ == "__main__":
    main()
