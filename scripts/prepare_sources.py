"""Build an immutable local source snapshot with the actual ToolUniverse SDK."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from oncofusion.schemas import CaseInput
from oncofusion.upstream_tools import SourcePlan, ToolUniverseSources, attach_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--case", type=Path)
    parser.add_argument("--allow-remote", action="store_true")
    args = parser.parse_args()
    if not args.allow_remote:
        parser.error("review the public queries and add --allow-remote")
    plan = SourcePlan.model_validate_json(args.plan.read_text())
    case = CaseInput.model_validate_json(args.case.read_text()) if args.case else None
    if case is not None and (case.task != "synthesis" or case.stage != 0 or case.as_of_day is not None
                             or case.data_class == "unreviewed"):
        parser.error("case must be reviewed contemporary synthesis; benchmark enrichment is separate")
    args.out.mkdir(parents=True, exist_ok=False)
    try:
        snapshot = ToolUniverseSources.installed().collect(plan)
        (args.out / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
        if case is not None:
            result = attach_snapshot(case, snapshot)
            (args.out / "case.json").write_text(result.model_dump_json(indent=2))
    except Exception as exc:
        (args.out / "failure.json").write_text(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        raise
    print(json.dumps({"status": "prepared", "tool_calls": snapshot["tool_calls"], "llm_calls": 0,
                      "out": str(args.out)}))


if __name__ == "__main__":
    main()
