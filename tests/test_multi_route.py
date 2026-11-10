import json
import threading
import time

import pytest

from oncofusion.examples import examples
from oncofusion.mock_routes import MockRouteProvider
from oncofusion.multi_route import ROUTE_NAMES, RouteEngine
from oncofusion.scheduling import ProviderScheduler, ScheduledProvider
from oncofusion.providers import ModelReply, ProviderError
from oncofusion.schemas import RunConfig


class ConcurrentProvider(MockRouteProvider):
    def __init__(self):
        super().__init__()
        self.current = 0
        self.peak = 0
        self.lock = threading.Lock()
        self.delay = 0.0

    def complete(self, *args):
        with self.lock:
            self.current += 1
            self.peak = max(self.peak, self.current)
        try:
            time.sleep(self.delay)
            return super().complete(*args)
        finally:
            with self.lock:
                self.current -= 1


def test_route_control_flows_are_distinct():
    case = examples()["synthetic-support"]
    calls = {}
    for route in ROUTE_NAMES:
        config = RunConfig(
            execution_model="route", route=route, route_rounds=1,
            max_calls=30, max_total_tokens=260000, citation_mode="fragment",
            fragment_budget=12000, interaction_protocol="claims-v1")
        result = RouteEngine(MockRouteProvider()).run(case, config)
        assert result.status == "completed"
        calls[route] = result.usage.calls
    assert calls["b0_single"] == 1
    assert len(set(calls.values())) >= 7


def test_scheduler_enforces_one_global_capacity():
    inner = ConcurrentProvider()
    inner.delay = 0.02
    scheduler = ProviderScheduler(2)
    provider = ScheduledProvider(inner, scheduler)
    threads = [
        threading.Thread(
            target=provider.complete,
            args=("system", {
                "role": "literature", "task": "verification",
                "question": "x", "sources": [], "signals": {},
                "options": {}, "verification_labels": ["SUPPORTS", "REVISIONS", "NEI"],
                "entities": {}, "stage": 0, "as_of_day": None, "board": [],
                "unresolved": [],
            }, 64, 0, 0),
        )
        for _ in range(12)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert inner.peak == 2
    assert scheduler.snapshot()["peak_in_flight"] == 2
    assert scheduler.snapshot()["completed_total"] == 12


def test_route_config_requires_a_route():
    with pytest.raises(ValueError, match="route"):
        RunConfig(execution_model="route")


class RepairProvider(MockRouteProvider):
    """Malformed first decision, then a valid repaired decision, with real usage fields."""

    def __init__(self):
        super().__init__()
        self.calls = 0

    def complete(self, system, payload, max_tokens, temperature, seed):
        self.calls += 1
        if self.calls == 1:
            return ModelReply('{"answer":"NOT_A_LABEL","explanation":"bad"}', 11, 3)
        return super().complete(system, payload, max_tokens, temperature, seed)


def test_route_repair_is_bounded_and_receives_valid_ids_and_errors():
    case = examples()["synthetic-support"]
    provider = RepairProvider()
    config = RunConfig(execution_model="route", route="b0_single",
                       schema_retries=1, max_calls=3, citation_mode="fragment",
                       fragment_budget=12000, interaction_protocol="claims-v1")
    result = RouteEngine(provider).run(case, config)
    assert result.status == "completed"
    assert result.usage.calls == 2
    invalid = [e for e in result.trace if e.kind == "route_invalid_output"]
    repairs = [e for e in result.trace if e.kind == "route_repair_requested"]
    assert len(invalid) == 1 and len(repairs) == 1
    assert invalid[0].details["valid_claim_ids"] == []
    assert invalid[0].details["validation_errors"]


def test_concurrent_route_token_reservation_cannot_overrun_budget():
    case = examples()["synthetic-support"]
    config = RunConfig(execution_model="route", route="a1_medagents",
                       route_workers=5, max_calls=15, max_total_tokens=100000,
                       citation_mode="fragment", fragment_budget=12000,
                       interaction_protocol="claims-v1")
    result = RouteEngine(MockRouteProvider()).run(case, config)
    assert result.usage.input_tokens + result.usage.output_tokens <= 100000
    assert result.usage.calls <= 15


def test_a4_uses_one_latest_claim_per_role_on_final_board():
    case = examples()["synthetic-support"]
    config = RunConfig(execution_model="route", route="a4_mdteamgpt",
                       route_rounds=2, max_calls=30, citation_mode="fragment",
                       fragment_budget=12000, interaction_protocol="claims-v1")
    result = RouteEngine(MockRouteProvider()).run(case, config)
    roles = [report.role for report in result.reports]
    assert len(roles) == len(set(roles))
    decision_call = next(e for e in reversed(result.trace) if e.kind == "route_node_started" and e.role == "decision")
    assert decision_call.details["evidence_ids"]


def test_b0_and_b2_are_engine_controls_in_frozen_plans():
    from pathlib import Path
    plan = json.loads(Path("experiments/civic_multi_route_dev60_20261109.json").read_text())
    by_name = {t["name"]: t for t in plan["treatments"]}
    assert by_name["b0_single"]["overrides"]["execution_model"] == "engine"
    assert by_name["b0_single"]["preset"] == "single_tools"
    assert by_name["b2_revision_gate"]["overrides"]["execution_model"] == "engine"
    assert by_name["b1_iterative"]["overrides"]["execution_model"] == "route"
    assert all(t["overrides"]["route_node_output_tokens"] <= 1500
               for t in plan["treatments"])
    assert len(plan["case_ids"]) == 60

def test_parallel_specialist_claim_registration_handles_empty_and_repeated_reports():
    case = examples()["synthetic-support"]
    config = RunConfig(execution_model="route", route="a1_medagents",
                       route_workers=5, route_rounds=1, max_calls=30,
                       citation_mode="fragment", fragment_budget=12000,
                       interaction_protocol="claims-v1")
    result = RouteEngine(MockRouteProvider()).run(case, config)
    assert result.status == "completed"
    claims = [finding.claim_id for report in result.reports for finding in report.output.findings]
    assert claims
    assert len(claims) == len(set(claims))

def test_evidence_plan_roles_cannot_escape_fixed_specialist_vocabulary():
    from oncofusion.multi_route import EvidenceNeed
    import pydantic
    import pytest
    with pytest.raises(pydantic.ValidationError):
        EvidenceNeed(question="Who?", roles=["Oncologist"])

class StrayVerifierProvider(MockRouteProvider):
    def __init__(self):
        super().__init__()
        self.verifier_calls = 0

    def complete(self, system, payload, max_tokens, temperature, seed):
        if payload.get("role") == "verifier" and "claim_roster" in payload:
            self.verifier_calls += 1
            if self.verifier_calls == 1:
                return ModelReply(json.dumps({"verdicts": [{
                    "target_claim_id": "invented-99", "verdict": "confirmed",
                    "note": "bad", "citations": []}], "unresolved": []}), 12, 4)
        return super().complete(system, payload, max_tokens, temperature, seed)


def test_verifier_unregistered_claim_enters_bounded_repair():
    case = examples()["synthetic-support"]
    provider = StrayVerifierProvider()
    config = RunConfig(execution_model="route", route="a1_medagents",
                       schema_retries=1, max_calls=30, citation_mode="fragment",
                       fragment_budget=12000, interaction_protocol="claims-v1")
    result = RouteEngine(provider).run(case, config)
    assert result.status == "completed"
    invalid = [e for e in result.trace if e.kind == "route_invalid_output"
               and e.role == "verifier"]
    assert invalid and "unregistered claim ids" in invalid[0].details["validation_errors"][0]["msg"]


class PartialVerifierProvider(MockRouteProvider):
    def complete(self, system, payload, max_tokens, temperature, seed):
        if ('"title": "ClaimVerificationOutput"' in system
                and payload.get("claim_roster")):
            roster = payload["claim_roster"][:-1]
            ids = [entry["evidence_id"] for entry in payload.get("evidence", [])]
            return ModelReply(json.dumps({
                "verdicts": [{
                    "target_claim_id": entry["claim_id"],
                    "verdict": "confirmed",
                    "note": "synthetic partial verifier",
                    "citations": [{"evidence_id": ids[0]}] if ids else [],
                } for entry in roster],
                "unresolved": [],
                "requery": "",
            }), 10, 10)
        return super().complete(system, payload, max_tokens, temperature, seed)


def test_verifier_must_cover_every_registered_route_claim():
    case = examples()["synthetic-support"]
    config = RunConfig(
        execution_model="route", route="a1_medagents",
        schema_retries=0, max_calls=30, citation_mode="fragment",
        fragment_budget=12000, interaction_protocol="claims-v1")
    with pytest.raises(ProviderError, match="schema or source-integrity"):
        RouteEngine(PartialVerifierProvider()).run(case, config)


def test_budget_exhaustion_without_decision_returns_run_result():
    case = examples()["synthetic-support"]
    config = RunConfig(execution_model="route", route="a1_medagents",
                       max_calls=1, citation_mode="fragment", fragment_budget=12000,
                       interaction_protocol="claims-v1")
    result = RouteEngine(MockRouteProvider()).run(case, config)
    assert result.status == "budget_exhausted"
    assert result.decision is None
