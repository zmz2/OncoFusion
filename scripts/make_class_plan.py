"""Build a classroom study plan whose config IS the live profile, never a hand-copied snapshot.

The 6b plans carried an `overrides` dict copied from an earlier profile, so they ran with
findings_limit=5, fragment_budget=24000 and max_total_tokens=200000 while the demo served
v1_class (3 / 12000 / 260000): the study measured a protocol nobody could replay in the UI, and
two MTB cases died at the token preflight. This writes the whole profile dump into `overrides`
and asserts the resolved plan config equals profiles.v1_class_config() before saving.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from oncofusion.experiments import StudyPlan, Treatment
from oncofusion.profiles import available_backend, v1_class_config

TASK = {"mtb": "mcq", "civic": "verification"}
DATASET = {"mtb": "data/mtbbench", "civic": "data/civicfact-pmidids"}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--family", required=True, choices=sorted(TASK))
    p.add_argument("--name", required=True, help="plan name and experiments/<name>.json")
    p.add_argument("--cases", nargs="+", required=True)
    args = p.parse_args()

    profile = v1_class_config("langgraph" if available_backend() == "langgraph" else None)
    dump = json.loads(profile.model_dump_json())
    treatment = Treatment(name="v1_class", preset="full", overrides=dump, perturbation="none")
    plan = StudyPlan(name=args.name, task=TASK[args.family], split="dev", group_limit=3,
                     seeds=[0], reference="v1_class", bootstrap_repeats=2000,
                     case_ids=args.cases, treatments=[treatment])
    resolved = plan.treatments[0].config(0)
    if resolved.model_dump() != profile.model_dump():
        diff = {k: (resolved.model_dump()[k], profile.model_dump()[k])
                for k in profile.model_dump() if resolved.model_dump()[k] != profile.model_dump()[k]}
        raise SystemExit(f"plan config drifted from the profile: {json.dumps(diff)}")
    out = Path("experiments") / f"{args.name}.json"
    out.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"written": str(out), "dataset": DATASET[args.family],
                      "cases": len(args.cases),
                      "config": {k: dump[k] for k in ("findings_limit", "fragment_budget",
                                                      "max_total_tokens", "max_output_tokens",
                                                      "interaction_protocol", "citation_mode",
                                                      "workflow_backend", "schema_retries")},
                      "max_model_calls": resolved.max_calls * len(args.cases)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
