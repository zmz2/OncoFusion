"""The /app demo surface: self-contained page, verified demo config, replay library, live role events."""
import json
import time

from oncofusion.api import create_app
from oncofusion.providers import MockProvider
from fastapi.testclient import TestClient

TERMINAL = {"succeeded", "failed", "interrupted", "cancelled", "budget_exhausted"}


def wait(client, run_id, polls=60):
    for _ in range(polls):
        row = client.get("/v1/runs/" + run_id).json()
        if row["status"] in TERMINAL:
            return row
        time.sleep(.05)
    raise AssertionError("run did not reach a terminal status")


def build_case_file(case_id="mtb-X-q0"):
    citation = {"document_id": "d1", "quote": "q", "start": 0, "end": 1}
    return {"schema_version": "1.0", "case_id": case_id, "patient_id": "P1", "status": "completed",
            "provider": "openai_compatible", "model": "hc-qwen38-27b-fp8", "simulated": False,
            "fingerprint": "f" * 64, "config": {"mode": "multi"},
            "decision": {"answer": "A", "explanation": "because", "citations": [citation],
                         "unresolved": [], "confidence": None},
            "reports": [{"role": "literature", "executor": "literature",
                         "output": {"findings": [{"statement": "s", "relation": "NEI", "citations": [citation]}],
                                    "unresolved": ["missing follow-up"], "requery": ""}}],
            "usage": {"calls": 7, "http_attempts": 7, "tool_calls": 1, "input_tokens": 100,
                      "output_tokens": 20, "estimated_tokens": False, "cost_usd": None},
            "trace": [{"kind": "model_usage", "role": "literature",
                       "details": {"input_tokens": 10, "output_tokens": 3, "attempts": 1,
                                   "estimated": False, "seconds": 1.5, "evidence_fragments": 2}}],
            "visible_document_ids": ["d1"], "duration_seconds": 12.5}


def write_study(root, study="real_fast2_mtb", treatment="v1_fast", case_id="mtb-X-q0"):
    folder = root / study / treatment / "0"
    folder.mkdir(parents=True)
    (folder / (case_id + ".json")).write_text(json.dumps(build_case_file(case_id)))
    (folder / "summary.json").write_text("{}")
    (folder / (case_id + ".failed.json")).write_text(json.dumps({"error": "kept out of the index"}))
    return root


def test_library_item_id_cannot_escape_the_allowlist(client, tmp_path, monkeypatch):
    """Regression for the (study, treatment) whitelist: only an allowlisted pair may resolve."""
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "results" / "v1"
    write_study(root)
    (root / "unapproved").mkdir()
    (root / "unapproved" / "v1_fast").mkdir(parents=True)
    (root / "unapproved" / "v1_fast" / "0").mkdir()
    (root / "unapproved" / "v1_fast" / "0" / "secret-case.json").write_text('{"case_id": "secret-case"}')
    monkeypatch.setenv("ONCOFUSION_RESULTS_DIR", str(root))
    for item_id in ("real_fast2_mtb:../../unapproved/v1_fast:secret-case",
                    "real_fast2_mtb:unapproved/v1_fast:secret-case",
                    "real_fast2_mtb:v1_fast:../unapproved/v1_fast/0/secret-case",
                    "real_fast2_mtb:v1_fast:secret case",
                    "nope:v1_fast:mtb-X-q0"):
        assert client.get("/v1/library/item", params={"item_id": item_id}).status_code == 404, item_id
    assert "secret-case" not in client.get("/v1/library").json()["items"][0]["id"]


def test_demo_page_is_self_contained(client):
    page = client.get("/app")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    body = page.text
    for role in ("文献证据", "病例时间线", "基因与通路", "病理与癌种语境", "药物关系", "主张核验", "综合决策"):
        assert role in body
    assert "<script src" not in body and "cdn." not in body
    assert "历史真实结果回放" in body and "输入检查" in body


def test_demo_page_script_is_syntactically_balanced(client):
    """Template-literal mistakes silently kill the whole page script; catch them without a JS runtime."""
    body = client.get("/app").text
    script = body.split("<script>", 1)[1].split("</script>", 1)[0]
    assert script.count("`") % 2 == 0, "unbalanced template literal in the demo page"
    for symbol in ("function boot", "async function api", "async function openLibraryItem", "const PINS"):
        assert symbol in script
    assert "await boot()" in script or "boot();" in script


def test_demo_config_is_the_verified_fast_profile(client):
    demo = client.get("/v1/configs/demo").json()
    assert demo["name"] == "v1_class"
    config = demo["config"]
    assert config["citation_mode"] == "fragment" and config["max_output_tokens"] == 5000
    assert config["schema_retries"] == 1 and config["findings_limit"] == 3
    assert config["ablations"]["targeted_requery"] is False
    assert config["interaction_protocol"] == "claims-v1"
    from importlib.util import find_spec
    expected = "langgraph" if find_spec("langgraph") is not None else "native"
    assert config["workflow_backend"] == expected == demo["workflow_backend"]


def test_run_events_report_every_role_output(client, case):
    config = client.get("/v1/configs/demo").json()["config"]
    run = client.post("/v1/runs", json={"case": case.model_dump(), "config": config,
                                        "allow_remote_processing": True})
    assert run.status_code == 202
    run_id = run.json()["run_id"]
    row = wait(client, run_id)
    assert row["status"] == "succeeded"
    events = client.get(f"/v1/runs/{run_id}/events", params={"limit": 500}).json()
    reported = [e for e in events if e["kind"] == "agent_reported"]
    assert [e["role"] for e in reported] == ["literature", "timeline", "genomics", "pathology", "drug",
                                             "verifier", "decision"]
    assert all(e["details"].get("output") for e in reported)
    # claims-v1 must be visible in the event log, not only in the final answer
    outputs = {e["role"]: e["details"]["output"] for e in reported}
    assert [f["claim_id"] for f in outputs["literature"]["findings"]]
    assert all(f["author_role"] == "timeline" for f in outputs["timeline"]["findings"])
    assert outputs["verifier"]["verdicts"], "the verifier must answer claims individually"
    assert {v["target_claim_id"] for v in outputs["verifier"]["verdicts"]} <= {
        f["claim_id"] for r in outputs.values() for f in r.get("findings", []) if "claim_id" in f}
    assert set(outputs["decision"]["adopted_claim_ids"]) <= {
        f["claim_id"] for role, out in outputs.items() if role != "decision"
        for f in out["findings"]}
    usage = [e for e in events if e["kind"] == "model_usage"]
    assert all(isinstance(e["details"].get("seconds"), (int, float)) for e in usage)
    stream = client.get(f"/v1/runs/{run_id}/stream", params={"after": events[-1]["sequence"]})
    assert "event: done" in stream.text


def test_library_replay_is_allowlisted(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "results" / "v1"
    write_study(root)
    monkeypatch.setenv("ONCOFUSION_RESULTS_DIR", str(root))
    done = next((root / "real_fast2_mtb").rglob("mtb-X-q0.json"))
    (done.parent / "mtb-X-q1.failed.json").write_text(json.dumps({"error": "model transport failed"}))
    items = client.get("/v1/library").json()["items"]
    assert len(items) == 1 and items[0]["case_id"] == "mtb-X-q0"
    listed = client.get("/v1/library", params={"include_failed": "true"}).json()
    assert len(listed["items"]) == 3 and listed["failed_rows"] == 2, "both failed rows are counted"
    assert items[0]["simulated"] is False and items[0]["calls"] == 7
    detail = client.get("/v1/library/item", params={"item_id": items[0]["id"]}).json()
    assert detail["reports"][0]["role"] == "literature"
    assert detail["trace"][0]["seconds"] == 1.5
    summary = client.get("/v1/datasets/summary").json()
    assert summary["arms"][0]["cases"] == 3, "failed runs must stay in the denominator"
    assert summary["arms"][0]["completion_rate"] == round(1 / 3, 3)


def test_library_rejects_path_like_ids(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "results" / "v1"
    write_study(root)
    monkeypatch.setenv("ONCOFUSION_RESULTS_DIR", str(root))
    for bad in ("../../etc:passwd:x", "unlisted:v1_fast:mtb-X-q0", "real_fast2_mtb:v1_fast:../../x"):
        assert client.get("/v1/library/item", params={"item_id": bad}).status_code == 404
