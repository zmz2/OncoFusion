"""The verification ledger is an input to the decision, not a note attached to the run.

A scripted provider makes the collaboration record explicit: the only thing that differs between
the paired runs below is the verifier's verdict, and the decision's payload must show it.
"""
import json

import pytest

from oncofusion.engine import Engine
from oncofusion.profiles import v1_class_config
from oncofusion.providers import ModelReply, ProviderError
from oncofusion.schemas import CaseInput, Document, Entities

CASE = CaseInput(
    schema_version="1.0", id="synth-ledger", patient_id="P1", task="synthesis",
    question="Does the record support KRAS p.G12V sensitivity to the recorded agent?",
    entities=Entities(gene="KRAS", variant="p.G12V", disease="lung adenocarcinoma"),
    documents=[Document(id="d1", origin_id="d1", kind="genomics",
                        text="SAMPLE: P1-T01\nAGE: 54.2, genomics > mutation --> GENE: KRAS, "
                             "MUTATION: p.G12V, SOMATIC: Yes, \nAGE: 54.2, treatment --> "
                             "AGENT: Sotorasib, SUBTYPE: Targeted, \n")],
    data_class="synthetic")


class ScriptedProvider:
    """Returns a fixed collaboration record; the verdict is the one parameter under test."""
    name, model = "scripted", "scripted-v1"
    simulated = False
    input_price = output_price = None

    def __init__(self, verdict="confirmed", decision_both=False):
        self.verdict = verdict
        self.decision_both = decision_both
        self.payloads = []
        self.calls = []

    def complete(self, system, payload, max_tokens, temperature, seed):
        role = payload["role"]
        self.calls.append(role)
        self.payloads.append((role, payload))
        ids = payload.get("evidence_ids") or []
        roster = payload.get("claim_roster") or []
        if role == "decision":
            adopt = [entry["claim_id"] for entry in roster]
            reject = []
            # The first attempt conflicts on purpose; a repaired attempt drops the exclusion.
            if self.decision_both and self.calls.count("decision") == 1 and roster:
                reject = [roster[0]["claim_id"]]
            body = {"answer": "NEI", "explanation": "Scripted decision for the ledger contract.",
                    "citations": [], "unresolved": [], "confidence": None,
                    "adopted_claim_ids": adopt, "rejected_claim_ids": reject}
        elif role == "verifier":
            body = {"findings": [], "unresolved": [], "requery": "",
                    "verdicts": [{"target_claim_id": entry["claim_id"], "verdict": self.verdict,
                                  "note": "scripted " + self.verdict,
                                  "citations": [{"evidence_id": ids[0]}] if ids else []}
                                 for entry in roster if entry["author_role"] != "verifier"]}
        elif role == "genomics":
            body = {"findings": [{"statement": "KRAS p.G12V is recorded in the sample.",
                                  "relation": "NEI",
                                  "citations": [{"evidence_id": ids[0]}] if ids else [],
                                  "scope": "molecular", "evidence_level": "measured",
                                  "material_status": "present",
                                  "used_claim_ids": ["timeline-01"]}],
                    # A specialist may review an earlier claim; that is role feedback, not the
                    # verifier's final check, and the ledger has to keep them apart.
                    "verdicts": [{"target_claim_id": "timeline-01", "verdict": "confirmed",
                                  "note": "role feedback from genomics",
                                  "citations": [{"evidence_id": ids[0]}] if ids else []}],
                    "unresolved": [], "requery": ""}
        elif role == "timeline":
            body = {"findings": [{"statement": "The only dated record is age 54.2.",
                                  "relation": "NEI",
                                  "citations": [{"evidence_id": ids[0]}] if ids else [],
                                  "scope": "temporal", "evidence_level": "measured",
                                  "material_status": "present"}],
                    "unresolved": [], "requery": ""}
        else:
            scope = {"pathology": "pathologic", "drug": "exposure", "literature": "source"}[role]
            body = {"findings": [{"statement": "No further %s layer finding." % scope,
                                  "relation": "NEI",
                                  "citations": [{"evidence_id": ids[0]}] if ids else [],
                                  "scope": scope, "evidence_level": "measured",
                                  "material_status": "present"}],
                    "unresolved": [], "requery": ""}
        content = json.dumps(body, ensure_ascii=False)
        return ModelReply(content, max(1, len(json.dumps(payload)) // 4), max(1, len(content) // 4),
                          estimated=True)


def run(provider, retries=0):
    config = v1_class_config("native").model_copy(update={"schema_retries": retries,
                                                          "ablations": v1_class_config("native").ablations.model_copy(
                                                              update={"targeted_requery": False})})
    return Engine(provider).run(CASE, config)


def decision_payload(provider):
    return next(payload for role, payload in provider.payloads if role == "decision")


def test_only_the_verdict_changes_what_the_decision_receives():
    confirmed, rejected = ScriptedProvider("confirmed"), ScriptedProvider("rejected")
    first, second = run(confirmed), run(rejected)
    assert first.status == second.status == "completed"
    confirmed_ledger = decision_payload(confirmed)["verification_ledger"]
    rejected_ledger = decision_payload(rejected)["verification_ledger"]
    assert confirmed_ledger and rejected_ledger
    assert {row["verdict"] for row in confirmed_ledger if row["final"]} == {"confirmed"}
    assert {row["verdict"] for row in rejected_ledger if row["final"]} == {"rejected"}
    roster_state = {entry["claim_id"]: entry["verifier_verdict"]
                    for entry in decision_payload(rejected)["claim_roster"]}
    assert set(roster_state.values()) == {"rejected"}
    # The ledger changed as a whole, and the answer was not forced to flip with it.
    assert confirmed_ledger != rejected_ledger
    assert first.decision.answer == second.decision.answer == "NEI"


def test_ledger_rows_name_reviewer_verdict_reason_and_citations():
    provider = ScriptedProvider("confirmed")
    result = run(provider)
    ledger = decision_payload(provider)["verification_ledger"]
    assert {row["reviewer"] for row in ledger} == {"genomics", "verifier"}
    for row in ledger:
        assert row["target_claim_id"] and row["verdict"]
        assert row["reason"], "every verdict carries the reason it was given"
        assert row["citations"] and "evidence_id" in row["citations"][0]
        assert row["final"] == (row["reviewer"] == "verifier")
    feedback = [row for row in ledger if not row["final"]]
    assert [row["reviewer"] for row in feedback] == ["genomics"]
    # One model call per role: two reviewers are two roles, not the verifier running twice.
    assert provider.calls.count("verifier") == 1
    event = next(e for e in result.trace if e.kind == "verification_ledger")
    assert event.details["entries"] == ledger
    assert event.details["claims_reviewed"] == len({row["target_claim_id"] for row in ledger})


def test_adopted_and_rejected_are_mutually_exclusive():
    provider = ScriptedProvider("confirmed", decision_both=True)
    with pytest.raises(ProviderError, match="schema or source-integrity"):
        run(provider, retries=0)
    # And with one repair available, the run asks for a corrected decision instead of storing both.
    provider = ScriptedProvider("confirmed", decision_both=True)
    result = run(provider, retries=1)
    assert provider.calls.count("decision") == 2
    assert result.status == "completed"
    assert not set(result.decision.adopted_claim_ids) & set(result.decision.rejected_claim_ids)
