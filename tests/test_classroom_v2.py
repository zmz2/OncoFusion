import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from oncofusion.api import create_app
from oncofusion.classroom import digest
from oncofusion.mock_routes import MockRouteProvider
from oncofusion.profiles import vote_v1_config
from oncofusion.schemas import CaseInput, Document
from oncofusion.vote_runner import VoteEngine


@pytest.fixture
def classroom(tmp_path, monkeypatch):
    case = CaseInput(id="synthetic-classroom", patient_id="synthetic-group", task="mcq",
                     question="Will the synthetic event occur?", options={"A": "Yes", "B": "No"},
                     data_class="synthetic", documents=[
                         Document(id="source-1", origin_id="origin-1", kind="clinical",
                                  text="A synthetic event was not observed.", event_day=0),
                         Document(id="source-2", origin_id="origin-2", kind="genomics",
                                  text="GENE: TEST; VARIANT: synthetic"),
                         Document(id="source-3", origin_id="origin-3", kind="pathology",
                                  text="CANCER_TYPE: synthetic disease")])
    config = vote_v1_config().model_copy(update={"vote_members": 4, "vote_rule": "v3", "max_calls": 15})
    provider = MockRouteProvider()
    provider.payloads = []
    complete = provider.complete
    def record(system, payload, *args):
        provider.payloads.append(payload)
        return complete(system, payload, *args)
    provider.complete = record
    result = VoteEngine(provider).run(case, config)
    (tmp_path / "inputs").mkdir()
    (tmp_path / "history").mkdir()
    specs = []
    for index in range(1, 4):
        alias = f"case-0{index}"
        (tmp_path / "inputs" / (alias + ".json")).write_text(case.model_dump_json())
        (tmp_path / "history" / (alias + ".json")).write_text(result.model_dump_json())
        specs.append({"alias": alias, "title": "合成资料", "question_zh": "检查合成事件", "input_fingerprint": digest(case.model_dump(mode="json"))})
    protocol = {"batch_id": "test", "code_commit": "test-sha", "cases": specs,
                "configs": {"B0": config.model_copy(update={"vote_pool": "generalist", "vote_members": 1, "vote_rule": "v0"}).model_dump(),
                            "OncoFusion": config.model_dump()},
                "history": {s["alias"]: {"timestamp": "historical", "commit": "old-sha"} for s in specs}}
    (tmp_path / "protocol.json").write_text(json.dumps(protocol))
    (tmp_path / "labels.json").write_text(json.dumps({s["alias"]: "A" for s in specs}))
    monkeypatch.setenv("ONCOFUSION_CLASSROOM_ROOT", str(tmp_path))
    with TestClient(create_app(tmp_path / "test.sqlite", provider=provider)) as client:
        yield client, provider, tmp_path


def test_classroom_public_view_does_not_disclose_source_text_or_unreviewed_reason(classroom):
    client, _, _ = classroom
    public = client.get("/v1/classroom/records/history-case-01").json()
    private = client.get("/v1/classroom/records/history-case-01?private=true").json()
    assert public["input"]["question_original"] is None
    assert public["input"]["documents"] == []
    assert all(b["brief_reason"] is None for b in public["ballots"])
    assert private["input"]["question_original"] == "Will the synthetic event occur?"
    assert len(public["ballots"]) == public["vote"]["planned_votes"]
    assert public["gold"] == "A"
    assert client.get("/v1/classroom/records/history-case-04").status_code == 404


def test_fixed_run_submission_is_idempotent_and_events_resume_without_recounting(classroom):
    client, provider, _ = classroom
    body = {"case_alias": "case-01", "system": "OncoFusion"}
    first = client.post("/v1/classroom/runs", json=body)
    second = client.post("/v1/classroom/runs", json=body)
    assert first.status_code == second.status_code == 202
    run_id = first.json()["run_id"]
    assert second.json()["run_id"] == run_id
    for _ in range(100):
        result = client.get("/v1/classroom/records/" + run_id).json()
        if result["status"] in {"succeeded", "failed", "budget_exhausted"}:
            break
        time.sleep(.01)
    assert result["status"] == "succeeded"
    all_events = client.get("/v1/classroom/records/" + run_id + "/events").json()
    midpoint = all_events[len(all_events) // 2]["sequence"]
    tail = client.get(f"/v1/classroom/records/{run_id}/events?after={midpoint}").json()
    assert all(e["sequence"] > midpoint for e in tail)
    assert len({e["sequence"] for e in all_events}) == len(all_events)
    assert client.get("/v1/classroom/records/" + run_id + "/events").json() == all_events
    assert "brief_reason" not in json.dumps(all_events)
    assert not any("gold" in payload or "label" in payload for payload in provider.payloads)
    assert result["simulated"] is True


def test_translation_is_bound_to_saved_reason_hash(classroom):
    client, _, root = classroom
    private = client.get("/v1/classroom/records/history-case-01?private=true").json()
    ballot = private["ballots"][0]
    annotations = {"records": {"history-case-01": {"ballots": {
        ballot["role"]: {"summary_zh": "错误关联的翻译", "reason_sha256": "wrong"}}}}}
    (root / "annotations.json").write_text(json.dumps(annotations))
    result = client.get("/v1/classroom/records/history-case-01").json()
    assert result["ballots"][0]["summary_zh"] is None
    annotations["records"]["history-case-01"]["ballots"][ballot["role"]]["reason_sha256"] = digest(ballot["brief_reason"])
    (root / "annotations.json").write_text(json.dumps(annotations))
    result = client.get("/v1/classroom/records/history-case-01").json()
    assert result["ballots"][0]["summary_zh"] == "错误关联的翻译"


def test_classroom_page_keeps_vote_and_real_events_visible(classroom):
    client, _, _ = classroom
    page = client.get("/classroom").text
    assert "千问 3.6 35B-A3B" in page
    assert "events=new Map()" in page
    assert "events.set(e.sequence,e)" in page
    assert "Decision没有额外模型调用" in page
    assert client.get("/app").status_code == 200


def test_catalog_uses_stored_status_and_citations_are_specific_to_the_recorded_role(classroom):
    client, _, root = classroom
    path = root / "history/case-01.json"
    result = json.loads(path.read_text())
    result["status"] = "failed"
    path.write_text(json.dumps(result))
    catalog = client.get("/v1/classroom/catalog").json()
    assert next(r for r in catalog["records"] if r["id"] == "history-case-01")["status"] == "failed"
    public = client.get("/v1/classroom/records/history-case-02").json()
    private = client.get("/v1/classroom/records/history-case-02?private=true").json()
    for left, right in zip(public["ballots"], private["ballots"]):
        assert len(left["citations"]) == len(left["evidence_ids"])
        assert all(c["quote"] is None for c in left["citations"])
        assert all(c["quote"] for c in right["citations"])
