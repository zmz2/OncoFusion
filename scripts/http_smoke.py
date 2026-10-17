"""Real loopback HTTP integration: Uvicorn -> compatible model emulator -> SQLite.

Uses real sockets/processes but a simulated model. Never needs internet or credentials.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from oncofusion.config import presets
from oncofusion.examples import examples
from oncofusion.providers import MockProvider
from oncofusion.schemas import RunConfig
from oncofusion.store import Store

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ModelHandler(BaseHTTPRequestHandler):
    count = 0
    lock = threading.Lock()

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        with self.lock:
            type(self).count += 1
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert self.headers["Authorization"] == "Bearer LOCAL_TEST_CREDENTIAL"
        payload = json.loads(body["messages"][1]["content"])
        reply = MockProvider().complete(body["messages"][0]["content"], payload,
                                       body.get("max_tokens", body.get("max_completion_tokens")),
                                       body.get("temperature", 0), body.get("seed", 0))
        raw = json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": reply.content}}],
                          "usage": {"prompt_tokens": reply.input_tokens, "completion_tokens": reply.output_tokens}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


def main():
    ModelHandler.count = 0
    started = time.monotonic()
    with TemporaryDirectory(prefix="oncofusion-http-") as td:
        td = Path(td)
        model = ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler)
        thread = threading.Thread(target=model.serve_forever, daemon=True)
        thread.start()
        port = free_port()
        database = td / "jobs.sqlite"
        # Persist an interrupted job before launch; startup must mark it explicitly.
        store = Store(database)
        cid = store.save_cases([examples()["synthetic-support"]])[0]
        interrupted = store.create_run(cid, RunConfig())
        store.claim_run(interrupted)
        env = {**os.environ, "ONCOFUSION_PROVIDER": "openai_compatible", "ONCOFUSION_BASE_URL": f"http://127.0.0.1:{model.server_port}/v1",
               "ONCOFUSION_MODEL": "LOCAL_SIMULATOR", "ONCOFUSION_API_KEY": "LOCAL_TEST_CREDENTIAL",
               "ONCOFUSION_API_TOKEN": "LOCAL_BACKEND_TOKEN", "ONCOFUSION_TIMEOUT": "10", "ONCOFUSION_RETRIES": "0",
               "ONCOFUSION_JSON_MODE": "true", "ONCOFUSION_SEND_TEMPERATURE": "true", "ONCOFUSION_SEND_SEED": "true"}
        logs = (td / "server.log").open("w+")
        process = subprocess.Popen([sys.executable, "-m", "oncofusion", "serve", "--port", str(port), "--db", str(database)],
                                   cwd=ROOT, env=env, stdout=logs, stderr=logs)
        base = f"http://127.0.0.1:{port}"
        checks = []
        try:
            with httpx.Client(base_url=base, timeout=15, trust_env=False) as client:
                deadline = time.monotonic() + 15
                while True:
                    try:
                        if client.get("/healthz").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    if time.monotonic() > deadline or process.poll() is not None:
                        raise RuntimeError("backend did not become ready")
                    time.sleep(.1)
                assert client.get("/v1/examples").status_code == 401
                client.headers["Authorization"] = "Bearer LOCAL_BACKEND_TOKEN"
                assert client.get(f"/v1/runs/{interrupted}").json()["status"] == "interrupted"
                checks += ["startup_recovery", "authentication"]
                upload = client.post("/v1/cases/upload", files={"file": ("cases.jsonl", "\n".join(c.model_dump_json() for c in examples().values()), "application/jsonl")})
                assert upload.status_code == 201 and upload.json()["count"] == 4
                checks.append("multipart_upload")
                def submit(item):
                    name, config = item
                    response = client.post("/v1/runs", json={"example_id": "synthetic-support", "config": config.model_dump(), "allow_remote_processing": True})
                    response.raise_for_status()
                    return name, response.json()["run_id"]
                with ThreadPoolExecutor(max_workers=8) as pool:
                    runs = dict(pool.map(submit, presets().items()))
                deadline = time.monotonic() + 50
                pending = dict(runs)
                while pending:
                    for name, rid in list(pending.items()):
                        row = client.get("/v1/runs/" + rid).json()
                        if row["status"] == "succeeded":
                            assert row["result"]["decision"] is not None
                            assert "FUTURE_CANARY" not in json.dumps(row)
                            del pending[name]
                        elif row["status"] in ("failed", "interrupted", "cancelled", "budget_exhausted"):
                            raise AssertionError(f"{name}: {row['status']}: {row['error']}")
                    if time.monotonic() > deadline:
                        raise TimeoutError("jobs did not finish")
                    time.sleep(.02)
                checks += ["concurrent_all_presets", "model_http_roundtrip", "future_information_boundary"]
                rid = runs["full"]
                events = client.get(f"/v1/runs/{rid}/events").json()
                assert [e["sequence"] for e in events] == list(range(len(events)))
                assert client.get(f"/v1/runs/{rid}/graph").json()["edges"]
                stream = client.get(f"/v1/runs/{rid}/stream").text
                assert "event: done" in stream and "event: agent_completed" in stream
                checks += ["ordered_events", "evidence_graph", "sse_completion"]
                assert client.post("/v1/cases", content=b"x" * 2_000_001).status_code == 413
                assert client.post("/v1/runs", json={"example_id": "synthetic-support"}).status_code == 422
                checks += ["body_limit", "remote_processing_consent"]
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            model.shutdown()
            model.server_close()
            logs.close()
    report = {"status": "passed", "transport": "real loopback TCP/HTTP", "model": "simulated lexical model",
              "external_api_tested": False, "presets_completed": len(runs), "model_http_requests": ModelHandler.count,
              "checks": checks, "seconds": round(time.monotonic() - started, 3)}
    out = ROOT / "results" / "http_smoke.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
