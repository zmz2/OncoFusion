import json
import sqlite3
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from oncofusion.api import MAX_BODY, create_app
from oncofusion.cli import main
from oncofusion.engine import Engine
from oncofusion.examples import examples
from oncofusion.providers import MockProvider, OpenAICompatibleProvider
from oncofusion.schemas import RunConfig, TraceEvent
from oncofusion.store import Store


def wait_for(client, rid):
    for _ in range(300):
        row = client.get("/v1/runs/" + rid).json()
        if row["status"] not in ("queued", "running"):
            return row
        time.sleep(.01)
    raise AssertionError("test job did not reach a terminal state")


def test_frontend_roundtrip(client, case):
    assert client.get("/healthz").json()["simulated"]
    assert len(client.get("/v1/examples").json()) == 4
    assert client.get("/v1/examples/synthetic-support").status_code == 200
    assert client.get("/v1/capabilities").json()["gpu_required"] is False
    assert client.get("/v1/schemas/case").json()["additionalProperties"] is False
    assert "full" in client.get("/v1/configs").json()
    created = client.post("/v1/cases", json=case.model_dump()).json()
    cid = created["case_id"]
    assert client.get("/v1/cases/" + cid).json()["id"] == case.id
    response = client.post("/v1/runs", json={"case_id": cid})
    assert response.status_code == 202
    rid = response.json()["run_id"]
    row = wait_for(client, rid)
    assert row["status"] == "succeeded" and row["result"]["decision"]["answer"] == "SUPPORTS"
    events = client.get(f"/v1/runs/{rid}/events").json()
    assert events[0]["kind"] == "run_started" and events[-1]["kind"] == "run_completed"
    assert "FUTURE_CANARY" not in json.dumps(events)
    tail = client.get(f"/v1/runs/{rid}/events", params={"after": 1, "limit": 3}).json()
    assert [e["sequence"] for e in tail] == [2, 3, 4]
    stream = client.get(f"/v1/runs/{rid}/stream", params={"after": 1})
    assert "text/event-stream" in stream.headers["content-type"] and "event: done" in stream.text
    graph = client.get(f"/v1/runs/{rid}/graph").json()
    nodes = {n["id"] for n in graph["nodes"]}
    assert all(e["source"] in nodes and e["target"] in nodes for e in graph["edges"])
    assert "source:future" not in nodes
    assert len(client.get("/v1/runs").json()) == 1
    assert client.delete("/v1/cases/" + cid).status_code == 204
    assert client.get("/v1/runs/" + rid).status_code == 404


@pytest.mark.parametrize("path", ["/v1/cases/missing", "/v1/runs/missing", "/v1/examples/missing",
                                  "/v1/runs/missing/graph", "/v1/runs/missing/events"])
def test_not_found(client, path):
    assert client.get(path).status_code == 404


def test_upload_json_and_jsonl(client, case):
    response = client.post("/v1/cases/upload", files={"file": ("../never-used-as-path.json", case.model_dump_json(), "application/json")})
    assert response.status_code == 201 and response.json()["count"] == 1
    second = case.model_copy(update={"id": "another"})
    response = client.post("/v1/cases/upload", files={"file": ("cases.jsonl", case.model_dump_json() + "\n" + second.model_dump_json())})
    assert response.status_code == 201 and response.json()["count"] == 2


@pytest.mark.parametrize("name,data,status", [("a.zip", b"zip", 415), ("a.json", b"bad", 422),
                                             ("a.json", b"\xff", 422), ("a.jsonl", b"", 422),
                                             ("a.json", b'{"answer":"secret"}', 422)])
def test_bad_uploads(client, name, data, status):
    assert client.post("/v1/cases/upload", files={"file": (name, data)}).status_code == status


def test_upload_atomic_validation(client, case):
    with client.app.state.store.connect() as conn:
        before = conn.execute("SELECT count(*) FROM cases").fetchone()[0]
    content = case.model_dump_json() + '\n{"invalid":1}'
    assert client.post("/v1/cases/upload", files={"file": ("a.jsonl", content)}).status_code == 422
    duplicate = case.model_dump_json() + "\n" + case.model_dump_json()
    assert client.post("/v1/cases/upload", files={"file": ("a.jsonl", duplicate)}).status_code == 422
    with client.app.state.store.connect() as conn:
        assert conn.execute("SELECT count(*) FROM cases").fetchone()[0] == before


def test_body_limit_and_validation(client, case):
    assert client.post("/v1/cases", content=b"x" * (MAX_BODY + 1), headers={"Content-Type": "application/json"}).status_code == 413
    assert client.post("/v1/runs", json={}).status_code == 422
    assert client.post("/v1/runs", json={"example_id": "synthetic-support", "api_key": "bad"}).status_code == 422
    assert client.get("/v1/runs", params={"limit": 9999}).status_code == 422
    assert client.get("/v1/runs", params={"offset": -1}).status_code == 422


def test_authentication_and_openapi(tmp_path):
    with TestClient(create_app(tmp_path / "auth.db", provider=MockProvider(), api_token="private-token")) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/v1/examples").status_code == 401
        assert client.get("/v1/examples", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert client.get("/v1/examples", headers={"Authorization": "Bearer private-token"}).status_code == 200
        schema = client.get("/openapi.json").json()
        assert schema["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
        assert "private-token" not in json.dumps(schema)


def test_cors_explicit_origin(tmp_path, monkeypatch):
    monkeypatch.setenv("ONCOFUSION_CORS_ORIGINS", "http://localhost:3000")
    with TestClient(create_app(tmp_path / "cors.db", provider=MockProvider())) as client:
        response = client.options("/v1/runs", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"})
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
        response = client.options("/v1/runs", headers={"Origin": "https://other.example", "Access-Control-Request-Method": "POST"})
        assert "access-control-allow-origin" not in response.headers


def test_mock_http_provider_entire_seven_role_run(tmp_path):
    calls = []
    simulator = MockProvider()
    def handler(request):
        wire = json.loads(request.content)
        calls.append(wire)
        reply = simulator.complete(wire["messages"][0]["content"], json.loads(wire["messages"][1]["content"]),
                                   wire["max_tokens"], wire["temperature"], wire["seed"])
        return httpx.Response(200, json={"choices": [{"message": {"content": reply.content}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": reply.input_tokens, "completion_tokens": reply.output_tokens}})
    provider = OpenAICompatibleProvider("https://mocked-wire.example/v1", "transport-fixture", "not-a-real-key",
                                        transport=httpx.MockTransport(handler), input_price=1, output_price=2)
    with TestClient(create_app(tmp_path / "wire.db", provider=provider)) as client:
        assert client.post("/v1/runs", json={"example_id": "synthetic-support"}).status_code == 422
        response = client.post("/v1/runs", json={"example_id": "synthetic-support", "allow_remote_processing": True})
        row = wait_for(client, response.json()["run_id"])
        assert row["status"] == "succeeded" and len(calls) == 7
        assert row["result"]["usage"]["cost_usd"] > 0
        assert not row["result"]["usage"]["estimated_tokens"]


def test_worker_exception_does_not_leak(tmp_path):
    class Broken(MockProvider):
        def complete(self, *args):
            raise RuntimeError("SECRET_API_KEY full patient record")
    with TestClient(create_app(tmp_path / "broken.db", provider=Broken())) as client:
        rid = client.post("/v1/runs", json={"example_id": "synthetic-support"}).json()["run_id"]
        row = wait_for(client, rid)
        assert row["status"] == "failed" and row["result"] is None
        assert row["error"] == "execution failed: RuntimeError"
        assert client.get(f"/v1/runs/{rid}/graph").status_code == 409
        assert client.post(f"/v1/runs/{rid}/cancel").status_code == 409


def test_queue_limit_cancel_and_active_delete(tmp_path):
    entered, release = threading.Event(), threading.Event()
    class Blocking(MockProvider):
        def complete(self, *args):
            entered.set()
            assert release.wait(5)
            return super().complete(*args)
    with TestClient(create_app(tmp_path / "queue.db", provider=Blocking(), max_workers=1, max_pending=2)) as client:
        try:
            first = client.post("/v1/runs", json={"example_id": "synthetic-support"}).json()
            assert entered.wait(2)
            second = client.post("/v1/runs", json={"example_id": "synthetic-refute"}).json()
            assert client.post("/v1/runs", json={"example_id": "synthetic-nei"}).status_code == 429
            assert client.delete("/v1/cases/" + first["case_id"]).status_code == 409
            assert client.post("/v1/runs/" + first["run_id"] + "/cancel").status_code == 409
            assert client.post("/v1/runs/" + second["run_id"] + "/cancel").status_code == 200
        finally:
            release.set()
        assert wait_for(client, first["run_id"])["status"] == "succeeded"
        assert wait_for(client, second["run_id"])["status"] == "cancelled"


def test_concurrent_jobs(client):
    ids = [client.post("/v1/runs", json={"example_id": name}).json()["run_id"]
           for name in list(examples()) * 3]
    rows = [wait_for(client, rid) for rid in ids]
    assert all(r["status"] == "succeeded" for r in rows)
    assert len({r["id"] for r in rows}) == 12
    for row in rows:
        events = client.get(f"/v1/runs/{row['id']}/events").json()
        assert [e["sequence"] for e in events] == list(range(len(events)))


def test_store_state_machine_and_restart(tmp_path, case):
    path = tmp_path / "store.db"
    store = Store(path)
    cid = store.save_cases([case])[0]
    rid = store.create_run(cid, RunConfig())
    assert store.claim_run(rid) and not store.claim_run(rid)
    event = TraceEvent(sequence=0, kind="test", role="genomics")
    store.append_event(rid, event)
    with pytest.raises(sqlite3.IntegrityError):
        store.append_event(rid, event)
    assert store.recover_interrupted() == 1
    assert store.run(rid)["status"] == "interrupted"
    with pytest.raises(RuntimeError):
        store.finish(rid, error="late")
    with pytest.raises(ValueError):
        store.finish(rid)
    another = store.create_run(cid, RunConfig())
    with TestClient(create_app(path, provider=MockProvider())):
        assert store.run(another)["status"] == "interrupted"
    done = store.create_run(cid, RunConfig())
    store.claim_run(done)
    store.finish(done, result=Engine(MockProvider()).run(case))
    assert store.run(done)["result"]["decision"]["answer"] == "SUPPORTS"
    assert len(store.list_runs(limit=1, offset=1)) == 1
    store.delete_case(cid)
    with pytest.raises(KeyError):
        store.case(cid)
    with pytest.raises(KeyError):
        store.delete_case(cid)


def test_cli_examples_demo_evaluate_matrix_schema(tmp_path):
    data, result = tmp_path / "data", tmp_path / "results"
    assert main(["examples", "--out", str(data)]) == 0
    assert main(["demo", "--out", str(result / "demo.json")]) == 0
    common = ["--inputs", str(data / "inputs.jsonl"), "--labels", str(data / "_gold/labels.jsonl")]
    assert main(["evaluate", *common, "--out", str(result / "eval")]) == 0
    assert main(["evaluate", *common, "--task", "mcq", "--out", str(result / "mcq")]) == 0
    assert main(["matrix", *common, "--presets", "full", "single_tools", "--repeats", "2", "--out", str(result / "matrix")]) == 0
    assert len(json.loads((result / "matrix/matrix.json").read_text())["results"]) == 4
    assert main(["openapi", "--out", str(result / "openapi.json")]) == 0
    assert "/v1/runs" in json.loads((result / "openapi.json").read_text())["paths"]


def test_cli_remote_and_nonloopback_requires_explicit_consent(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        main(["serve", "--host", "0.0.0.0"])
    monkeypatch.setenv("ONCOFUSION_PROVIDER", "openai_compatible")
    monkeypatch.setenv("ONCOFUSION_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("ONCOFUSION_MODEL", "m")
    monkeypatch.setenv("ONCOFUSION_API_KEY", "test")
    with pytest.raises(SystemExit):
        main(["demo", "--out", str(tmp_path / "demo.json")])


def test_cli_dataset_imports(tmp_path):
    row = {"id": "sample", "claim.flat": "claim", "evidence.flat": "evidence", "document.pmid": "123",
           "partition": "test", "gold_label_name": "SUPPORTS"}
    (tmp_path / "civic.jsonl").write_text(json.dumps(row))
    assert main(["import-civic", "--source", str(tmp_path / "civic.jsonl"), "--out", str(tmp_path / "civic")]) == 0
    records = {p: [{"context": "Visible history"}, {"question": "Q\nA) one\nB) two", "answer": "A"}] for p in ("p1", "p2")}
    (tmp_path / "mtb.json").write_text(json.dumps(records))
    (tmp_path / "map.json").write_text("{}")
    assert main(["import-mtb", "--source", str(tmp_path / "mtb.json"), "--root", str(tmp_path),
                 "--path-map", str(tmp_path / "map.json"), "--out", str(tmp_path / "mtb")]) == 0
