"""Answer stability per arm across seeds and across independent runs (same protocol shape)."""
import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path


def load(study_dir: Path, treatment: str, seed: str) -> dict:
    rows = {}
    for path in sorted((study_dir / treatment / seed).glob("*.json")):
        if path.name == "summary.json" or path.name.endswith(".failed.json"):
            continue
        data = json.loads(path.read_text())
        rows[data["case_id"]] = {"status": data["status"],
                                 "answer": data["decision"]["answer"] if data["decision"] else None}
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--replicate", action="append", required=True, type=Path,
                        help="study directory containing the arm runs")
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--arms", nargs="+", default=["v1_fast", "single_tools"])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    gold = {g["case_id"]: g for g in (json.loads(l) for l in args.gold.read_text().splitlines())}
    samples = defaultdict(list)  # arm -> list of (label, {case_id: answer})
    for study in args.replicate:
        if not study.is_dir():
            continue
        for arm in args.arms:
            seeds = sorted(p.name for p in study.glob(f"{arm}/*") if p.is_dir())
            for seed in seeds:
                rows = load(study, arm, seed)
                if not rows:
                    continue
                label = f"{study.name}/{seed}"
                samples[arm].append((label, {c: r["answer"] if r["status"] == "completed" else None
                                             for c, r in rows.items()}))

    report = {}
    for arm, entries in samples.items():
        cases = sorted(set.intersection(*[set(a) for _, a in entries])) if entries else []
        per_case = {}
        for case_id in cases:
            answers = [a[case_id] for _, a in entries]
            per_case[case_id] = {"answers": answers, "distinct": len(set(answers)),
                                 "modal": Counter(answers).most_common(1)[0][0],
                                 "stable": len(set(answers)) == 1,
                                 "gold": gold[case_id]["label"]}
        accs = [sum(1 for c in cases if a[c] == gold[c]["label"]) / len(cases) for _, a in entries] if cases else []
        report[arm] = {
            "replicates": [label for label, _ in entries], "cases": len(cases),
            "accuracy_per_replicate": [round(x, 4) for x in accs],
            "accuracy_mean": round(statistics.mean(accs), 4) if accs else None,
            "accuracy_stdev": round(statistics.stdev(accs), 4) if len(accs) > 1 else 0.0,
            "accuracy_range": [round(min(accs), 4), round(max(accs), 4)] if accs else None,
            "cases_stable_across_replicates": sum(1 for v in per_case.values() if v["stable"]),
            "unstable_case_ids": sorted(cid for cid, v in per_case.items() if not v["stable"]),
            "per_case": per_case}

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    for arm, data in report.items():
        print("%-14s replicates=%d cases=%d accuracy=%s mean=%.4f sd=%.4f stable=%d/%d unstable=%s" % (
            arm, len(data["replicates"]), data["cases"], data["accuracy_per_replicate"],
            data["accuracy_mean"] or 0, data["accuracy_stdev"], data["cases_stable_across_replicates"],
            data["cases"], data["unstable_case_ids"][:6]))


main()
