"""Pairwise comparison of two study arms on identical cases (real or simulated, kept separate)."""
import argparse
import json
import statistics
from pathlib import Path



def load_arm(study_dir: Path) -> dict:
    rows = {}
    for path in sorted(study_dir.glob("*/*/*.json")):
        if path.name == "summary.json" or path.name.endswith(".failed.json"):
            continue
        data = json.loads(path.read_text())
        rows[data["case_id"]] = {
            "status": data["status"], "answer": data["decision"]["answer"] if data["decision"] else None,
            "usage": data["usage"], "seconds": data["duration_seconds"], "simulated": data["simulated"]}
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True, help="first arm study directory")
    parser.add_argument("--candidate", type=Path, required=True, help="second arm study directory")
    parser.add_argument("--gold", type=Path, required=True, help="_gold/labels.jsonl of the dataset")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    from oncofusion.datasets import GoldRecord
    gold = {g["case_id"]: g for g in (json.loads(line) for line in args.gold.read_text().splitlines())}
    ref = load_arm(args.reference)
    cand = load_arm(args.candidate)
    common = sorted(set(ref) & set(cand))
    if not common:
        raise SystemExit("no shared case ids between arms")
    if len(ref) != len(common) or len(cand) != len(common):
        print(f"note: pairing covers {len(common)} shared cases "
              f"(reference {len(ref)}, candidate {len(cand)})")

    scores = {"reference": {}, "candidate": {}}
    per_case = []
    for case_id in common:
        label = gold[case_id]["label"]
        group = gold[case_id]["group_id"]
        r, c = ref[case_id], cand[case_id]
        rr = int(r["status"] == "completed" and r["answer"] == label)
        cc = int(c["status"] == "completed" and c["answer"] == label)
        scores["reference"][case_id] = rr
        scores["candidate"][case_id] = cc
        per_case.append({"case_id": case_id, "group_id": group, "reference_correct": rr,
                         "candidate_correct": cc,
                         "reference_status": r["status"], "candidate_status": c["status"],
                         "reference_seconds": round(r["seconds"], 1), "candidate_seconds": round(c["seconds"], 1),
                         "reference_calls": r["usage"]["calls"], "candidate_calls": c["usage"]["calls"],
                         "reference_tokens": r["usage"]["input_tokens"] + r["usage"]["output_tokens"],
                         "candidate_tokens": c["usage"]["input_tokens"] + c["usage"]["output_tokens"],
                         "simulated": r["simulated"] or c["simulated"]})

    from oncofusion.evaluation import paired_cluster_bootstrap
    groups = [gold[c]["group_id"] for c in common]
    boot = paired_cluster_bootstrap(groups, [scores["candidate"][c] for c in common],
                                    [scores["reference"][c] for c in common], repeats=2000)
    report = {
        "paired_cases": len(common),
        "groups": len(set(groups)),
        "simulated": bool(per_case[0]["simulated"]),
        "reference_dir": str(args.reference), "candidate_dir": str(args.candidate),
        "accuracy": {"reference": round(statistics.mean(scores["reference"].values()), 4),
                     "candidate": round(statistics.mean(scores["candidate"].values()), 4)},
        "delta_candidate_minus_reference": round(statistics.mean(scores["candidate"].values())
                                                 - statistics.mean(scores["reference"].values()), 4),
        "paired_bootstrap": boot,
        "discordant": {"candidate_only": sum(1 for c in common if scores["candidate"][c] and not scores["reference"][c]),
                       "reference_only": sum(1 for c in common if scores["reference"][c] and not scores["candidate"][c])},
        "statuses": {"reference": {}, "candidate": {}},
        "cost": {},
    }
    for arm, table in (("reference", ref), ("candidate", cand)):
        statuses = {}
        for case_id in common:
            statuses[table[case_id]["status"]] = statuses.get(table[case_id]["status"], 0) + 1
        report["statuses"][arm] = statuses
        report["cost"][arm] = {
            "calls_per_case": round(statistics.mean([table[c]["usage"]["calls"] for c in common]), 2),
            "tokens_per_case": round(statistics.mean([table[c]["usage"]["input_tokens"]
                                                      + table[c]["usage"]["output_tokens"] for c in common])),
            "seconds_p50": round(statistics.median([table[c]["seconds"] for c in common]), 1),
            "seconds_p95": round(sorted([table[c]["seconds"] for c in common])[
                int(0.95 * (len(common) - 1))], 1),
            "http_attempts_per_case": round(statistics.mean([table[c]["usage"]["http_attempts"] for c in common]), 2),
            "estimated_usage_cases": sum(1 for c in common if table[c]["usage"]["estimated_tokens"])}
    report["per_case"] = per_case
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "per_case"}, ensure_ascii=False, indent=2))


main()
