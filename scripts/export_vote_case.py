"""Export selected vote-v1 trajectories as a readable evidence case card."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from oncofusion.datasets import GoldRecord, read_jsonl
from oncofusion.schemas import CaseInput, RunResult


def result_for(run: Path, arm: str, case_id: str) -> RunResult | None:
    path = run / arm / "0" / (case_id + ".json")
    return (
        RunResult.model_validate_json(path.read_text(encoding="utf-8"))
        if path.exists() else None
    )


def short(text: str, limit: int = 320) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[:limit - 1] + "…"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--case-id", action="append", required=True)
    parser.add_argument(
        "--arms",
        nargs="+",
        default=["b0_common_single", "g_k4", "p_k_specialists"],
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    cases = {
        case.id: case
        for case in (
            CaseInput.model_validate(row)
            for row in read_jsonl(args.dataset / "inputs.jsonl")
        )
    }
    gold = {
        row.case_id: row
        for row in (
            GoldRecord.model_validate(item)
            for item in read_jsonl(
                args.dataset / "_gold" / "labels.jsonl")
        )
    }
    lines = ["# vote-v1 selected cases", ""]
    for case_id in args.case_id:
        case = cases[case_id]
        lines += [
            f"## `{case_id}`",
            "",
            f"- task: `{case.task}`",
            f"- patient/article group: `{gold[case_id].group_id}`",
            f"- gold: `{gold[case_id].label}`",
            f"- question: {short(case.question, 900)}",
            "",
            "| arm | status | label | valid/planned | calls | input+output tokens |",
            "|---|---|---|---:|---:|---:|",
        ]
        results = {}
        for arm in args.arms:
            result = result_for(args.run, arm, case_id)
            results[arm] = result
            if result is None:
                lines.append(f"| {arm} | missing | — | — | — | — |")
                continue
            vote = result.vote_result
            lines.append(
                f"| {arm} | {result.status} | "
                f"{result.decision.answer if result.decision else '—'} | "
                f"{vote.valid_votes}/{vote.planned_votes if vote else 0} | "
                f"{result.usage.calls} | "
                f"{result.usage.input_tokens + result.usage.output_tokens} |")
        lines.append("")
        for arm in args.arms:
            result = results[arm]
            if result is None:
                continue
            lines += [f"### {arm}", ""]
            if result.decision is not None:
                lines += [
                    "Decision: " + short(result.decision.explanation, 900),
                    "",
                ]
                if result.decision.unresolved:
                    lines += [
                        "Unresolved: " + " | ".join(
                            short(item, 240)
                            for item in result.decision.unresolved),
                        "",
                    ]
            if result.ballots:
                lines += [
                    "| member | seed | status | label | confidence | concise reason |",
                    "|---|---:|---|---|---:|---|",
                ]
                for ballot in result.ballots:
                    lines.append(
                        f"| {ballot.role} | {ballot.seed} | {ballot.status} | "
                        f"{ballot.label or '—'} | "
                        f"{ballot.confidence if ballot.confidence is not None else '—'} | "
                        f"{short(ballot.brief_reason, 500)} |")
                lines.append("")
                for ballot in result.ballots:
                    if not ballot.findings:
                        continue
                    lines.append(f"`{ballot.role}` findings:")
                    for finding in ballot.findings:
                        ids = ", ".join(sorted({
                            f"{citation.document_id}:{citation.start}-{citation.end}"
                            for citation in finding.citations
                        }))
                        lines.append(
                            f"- {short(finding.statement, 500)} "
                            f"(stance={finding.stance}; spans={ids or 'none'})")
                    lines.append("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "cases": len(args.case_id)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
