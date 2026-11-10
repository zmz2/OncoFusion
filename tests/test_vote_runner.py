import json

from oncofusion.examples import examples
from oncofusion.mock_routes import MockRouteProvider
from oncofusion.profiles import vote_v1_config
from oncofusion.providers import (
    OpenAICompatibleProvider,
    ProviderError,
    provider_identity,
)
from oncofusion.scheduling import ProviderScheduler, ScheduledProvider
from oncofusion.vote_runner import VoteEngine


class CaptureVoteProvider(MockRouteProvider):
    def __init__(self):
        super().__init__()
        self.payloads = []

    def complete(self, system, payload, max_tokens, temperature, seed):
        if '"title": "VoteBallotOutput"' in system:
            self.payloads.append((system, payload))
        return super().complete(system, payload, max_tokens, temperature, seed)


class FailOneVoter(MockRouteProvider):
    def complete(self, system, payload, max_tokens, temperature, seed):
        if ('"title": "VoteBallotOutput"' in system
                and payload.get("role") == "genomics"):
            raise ProviderError("synthetic member failure")
        return super().complete(system, payload, max_tokens, temperature, seed)


class RepairOnceVoter(CaptureVoteProvider):
    def complete(self, system, payload, max_tokens, temperature, seed):
        if ('"title": "VoteBallotOutput"' in system
                and payload.get("role") == "literature"
                and "repair" not in payload):
            self.payloads.append((system, payload))
            invalid = json.dumps({
                "status": "vote",
                "label": "SUPPORTS",
                "confidence": .8,
                "brief_reason": "Invalid citation for repair test.",
                "evidence_ids": [{"evidence_id": "not-visible"}],
                "findings": [{
                    "statement": "Invalid local finding.",
                    "stance": "supports",
                    "evidence_ids": [{"evidence_id": "not-visible"}],
                }],
            })
            return self._reply(invalid, payload)
        return super().complete(
            system, payload, max_tokens, temperature, seed)

    @staticmethod
    def _reply(content, payload):
        from oncofusion.providers import ModelReply
        return ModelReply(
            content,
            max(1, len(json.dumps(payload)) // 4),
            max(1, len(content) // 4),
            estimated=True,
        )


class SplitAndAdjudicate(MockRouteProvider):
    def __init__(self):
        super().__init__()
        self.arbiter_calls = 0

    def complete(self, system, payload, max_tokens, temperature, seed):
        ids = [entry["evidence_id"] for entry in payload.get("evidence", [])]
        if '"title": "VoteBallotOutput"' in system:
            labels = {
                "literature": "SUPPORTS",
                "genomics": "SUPPORTS",
                "pathology": "REFUTES",
                "drug": "REFUTES",
            }
            body = {
                "status": "vote",
                "label": labels[payload["role"]],
                "confidence": .6,
                "brief_reason": "Synthetic split ballot.",
                "evidence_ids": [{"evidence_id": ids[0]}] if ids else [],
                "findings": [{
                    "statement": "Synthetic local finding.",
                    "stance": "supports",
                    "evidence_ids": [{"evidence_id": ids[0]}] if ids else [],
                }] if ids else [],
            }
            content = json.dumps(body)
            return self._reply(content, payload)
        if '"title": "VoteAdjudicationOutput"' in system:
            self.arbiter_calls += 1
            body = {
                "label": "NEI",
                "explanation": "Synthetic arbitration.",
                "evidence_ids": [{"evidence_id": ids[0]}] if ids else [],
                "unresolved": ["Synthetic unresolved issue."],
            }
            return self._reply(json.dumps(body), payload)
        return super().complete(system, payload, max_tokens, temperature, seed)

    @staticmethod
    def _reply(content, payload):
        from oncofusion.providers import ModelReply
        return ModelReply(
            content,
            max(1, len(json.dumps(payload)) // 4),
            max(1, len(content) // 4),
            estimated=True,
        )


def test_vote_engine_shares_one_evidence_packet_and_never_treats_decision_as_voter():
    provider = CaptureVoteProvider()
    result = VoteEngine(provider).run(
        examples()["synthetic-support"], vote_v1_config("native"))
    assert result.status == "completed"
    assert result.vote_result.valid_votes == 4
    assert len(result.ballots) == 4
    assert result.usage.calls == 4
    assert {payload["role"] for _, payload in provider.payloads} == {
        "literature", "genomics", "pathology", "drug"}
    evidence = {
        json.dumps(payload["evidence"], sort_keys=True)
        for _, payload in provider.payloads
    }
    sources = {
        json.dumps(payload["sources"], sort_keys=True)
        for _, payload in provider.payloads
    }
    assert len(evidence) == 1
    assert len(sources) == 1
    assert all(ballot.input_fingerprint for ballot in result.ballots)
    assert all(ballot.case_id == result.case_id for ballot in result.ballots)
    assert result.decision.answer == "SUPPORTS"
    started = next(
        event for event in result.trace if event.kind == "run_started")
    assert not started.details["role_applicability"]["timeline"]["applicable"]


def test_one_member_failure_does_not_cancel_other_ballots():
    result = VoteEngine(FailOneVoter()).run(
        examples()["synthetic-support"], vote_v1_config("native"))
    assert result.status == "completed"
    assert result.vote_result.completion_status == "degraded"
    assert result.vote_result.failed_votes == 1
    assert result.vote_result.valid_votes == 3
    assert any(ballot.status == "failed" for ballot in result.ballots)


def test_invalid_visible_id_requests_one_bounded_repair_with_legal_ids():
    provider = RepairOnceVoter()
    result = VoteEngine(provider).run(
        examples()["synthetic-support"], vote_v1_config("native"))
    literature = next(
        ballot for ballot in result.ballots if ballot.role == "literature")
    assert literature.status == "vote"
    assert literature.usage.calls == 2
    repair = next(
        payload["repair"]
        for _, payload in provider.payloads
        if payload.get("role") == "literature" and "repair" in payload)
    assert repair["previous_output"]
    assert repair["valid_evidence_ids"]
    assert "not visible" in repair["validation_errors"][0]["msg"]
    assert [event.kind for event in result.trace].count(
        "vote_repair_requested") == 1


def test_generalist_pool_uses_same_number_of_members_as_professional_pool():
    config = vote_v1_config("native").model_copy(
        update={"vote_pool": "generalist"})
    result = VoteEngine(MockRouteProvider()).run(
        examples()["synthetic-support"], config)
    assert result.vote_result.pool == "generalist"
    assert result.vote_result.planned_votes == 4
    assert [ballot.role for ballot in result.ballots] == ["generalist"] * 4
    assert [ballot.seed for ballot in result.ballots] == [0, 1, 2, 3]
    assert result.reports == []


def test_generalist_single_is_the_common_evidence_b0():
    config = vote_v1_config("native").model_copy(update={
        "vote_pool": "generalist",
        "vote_members": 1,
        "vote_workers": 1,
        "max_calls": 3,
        "temperature": 0.0,
    })
    result = VoteEngine(MockRouteProvider()).run(
        examples()["synthetic-support"], config)
    assert result.vote_result.planned_votes == 1
    assert result.vote_result.valid_votes == 1
    assert result.usage.calls == 1


def test_v3_calls_one_anonymized_arbiter_after_low_consistency():
    provider = SplitAndAdjudicate()
    config = vote_v1_config("native").model_copy(update={
        "vote_rule": "v3",
        "vote_arbitration_min_share": .75,
        "vote_arbitration_margin": .25,
        "max_calls": 8,
    })
    result = VoteEngine(provider).run(
        examples()["synthetic-support"], config)
    assert result.vote_result.tied
    assert result.vote_result.arbitration.triggered
    assert result.vote_result.arbitration.status == "completed"
    assert result.vote_result.arbitration.initial_label in {"SUPPORTS", "REFUTES"}
    assert result.decision.answer == "NEI"
    assert "Synthetic unresolved issue." in result.decision.unresolved
    assert "Synthetic arbitration." in result.decision.explanation
    assert provider.arbiter_calls == 1
    assert result.usage.calls == 5


def test_vote_execution_requires_vote_protocol():
    import pytest
    from oncofusion.schemas import RunConfig

    with pytest.raises(ValueError, match="vote-v1"):
        RunConfig(execution_model="vote")


def test_scheduled_provider_identity_includes_sampling_and_capacity():
    inner = OpenAICompatibleProvider(
        "http://127.0.0.1:28180/v1",
        "test-model",
        "not-a-real-key",
        send_temperature=True,
        send_seed=True,
    )
    provider = ScheduledProvider(inner, ProviderScheduler(20))
    identity = provider_identity(provider)
    assert identity["send_temperature"] is True
    assert identity["send_seed"] is True
    assert identity["scheduler_capacity"] == 20
