"""Exhaust all 2^9 internal-feature combinations and perturbation/preset pairs."""
import itertools
import json
import time
from pathlib import Path
from oncofusion.config import presets
from oncofusion.engine import Engine
from oncofusion.evidence import check_citations, visible_case
from oncofusion.examples import examples
from oncofusion.experiments import PERTURBATIONS, perturb
from oncofusion.providers import MockProvider
from oncofusion.schemas import Ablations, RunConfig


def main():
    started = time.monotonic()
    engine = Engine(MockProvider())
    count, failures = 0, []
    def check(name, case, config):
        nonlocal count
        count += 1
        try:
            result = engine.run(case, config)
            assert result.status == "completed"
            assert result.decision is not None
            assert result.usage.calls <= config.max_calls
            assert result.usage.tool_calls <= config.max_tool_calls
            assert "FUTURE_CANARY" not in result.model_dump_json()
            check_citations(result.decision.citations, visible_case(case).documents)
            assert [e.sequence for e in result.trace] == list(range(len(result.trace)))
        except Exception as exc:
            failures.append({"case": case.id, "configuration": name, "error": type(exc).__name__, "message": str(exc)[:500]})
    fields = list(Ablations.model_fields)
    for switches in itertools.product([False, True], repeat=len(fields)):
        setting = dict(zip(fields, switches))
        config = RunConfig(ablations=Ablations(**setting))
        for case in examples().values():
            check(str(setting), case, config)
    exhaustive = count
    for name, config in presets().items():
        for kind in PERTURBATIONS:
            for seed in (0, 17):
                for case in examples().values():
                    check(name + ":" + kind + ":" + str(seed), perturb(case, kind, seed), config)
    report = {"status": "passed" if not failures else "failed", "simulated": True,
              "exhaustive_feature_cases": exhaustive, "perturbation_preset_cases": count - exhaustive,
              "case_executions": count, "failures": failures, "seconds": round(time.monotonic() - started, 3)}
    path = Path(__file__).resolve().parents[1] / "results" / "stress.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
