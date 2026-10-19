"""Versioned backend API. Run with one process; local thread workers handle jobs."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError

from . import __version__, library
from .agent_design import catalog as agent_catalog
from .workflow import specification, dependency_identity
from .profiles import (profile_catalog, inspect_case, integration_example, v1_class_config, v1_config,
                     v1_fast_config)
from .config import presets
from .engine import Engine
from .evidence import evidence_graph, visible_case
from .examples import examples
from .providers import Provider, ProviderError, provider_from_env, provider_identity
from .schemas import AgentReport, CaseInput, RunRequest, RunConfig, DecisionOutput
from .store import Store, TERMINAL

MAX_BODY = 2_000_000


def create_app(db_path: str | Path | None = None, provider: Provider | None = None,
               api_token: str | None = None, max_workers: int = 2, max_pending: int = 32) -> FastAPI:
    if not 1 <= max_workers <= 32 or not max_workers <= max_pending <= 1024:
        raise ValueError("require 1 <= max_workers <= max_pending <= 1024 (workers <= 32)")
    provider = provider or provider_from_env()
    if provider.simulated and os.getenv("ONCOFUSION_DEMO_REQUIRE_REAL") == "1":
        # The demo page labels runs "真实 API" from provider and result.simulated. Refusing to boot
        # on a simulated backend is what keeps a mis-configured restart from passing off mock runs.
        raise RuntimeError("ONCOFUSION_DEMO_REQUIRE_REAL=1 but the configured provider is simulated; "
                          "load the real API environment before serving the demo")
    store = Store(db_path or os.getenv("ONCOFUSION_DB", "runtime/oncofusion.sqlite3"))
    token = api_token if api_token is not None else os.getenv("ONCOFUSION_API_TOKEN", "")
    slots = threading.BoundedSemaphore(max_pending)
    submission_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(app):
        store.recover_interrupted()
        app.state.pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="oncofusion")
        yield
        app.state.pool.shutdown(wait=True)

    app = FastAPI(title="OncoFusion research API", version=__version__, lifespan=lifespan)
    app.state.store = store
    app.state.provider = provider
    origins = [s.strip() for s in os.getenv("ONCOFUSION_CORS_ORIGINS", "").split(",") if s.strip()]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins,
                           allow_methods=["GET", "POST", "DELETE"], allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "Last-Event-ID"],
                           expose_headers=["Idempotency-Replayed"])

    @app.middleware("http")
    async def bounded_body(request: Request, call_next):
        if request.method == "POST":
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_BODY:
                    return JSONResponse(status_code=413, content={"detail": "request exceeds 2 MB"})
                chunks.append(chunk)
            request._body = b"".join(chunks)
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Pydantic errors contain raw input by default. Return only locations and types.
        return JSONResponse(status_code=422, content={"detail": [
            {"loc": list(error["loc"]), "type": error["type"], "msg": error["msg"]}
            for error in exc.errors()]})

    security = HTTPBearer(auto_error=False)

    def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
        if token and (credentials is None or not hmac.compare_digest(credentials.credentials.encode(), token.encode())):
            raise HTTPException(401, "invalid bearer token", headers={"WWW-Authenticate": "Bearer"})

    router = APIRouter(prefix="/v1", dependencies=[Depends(authorize)])

    @app.get("/healthz")
    def health():
        return {"status": "ok", "version": __version__, "provider": provider.name, "simulated": provider.simulated}

    @app.get("/app", include_in_schema=False)
    def demo_page():
        page = Path(__file__).resolve().parent / "web" / "index.html"
        if not page.is_file():
            raise HTTPException(503, "demo page is not installed")
        return HTMLResponse(page.read_text(encoding="utf-8"))

    @router.get("/configs/demo")
    def demo_config():
        """The configuration the demo must submit, so callers never fall back to legacy presets."""
        return {"name": "v1_class", "config": v1_class_config().model_dump(),
                "workflow_backend": v1_class_config().workflow_backend,
                "graph_installed": library.graph_installed(),
                "note": "seven roles in the fixed order, evidence-fragment handles resolved by the "
                        "server, vendor output ceiling, one schema repair for every system, and the "
                        "claims-v1 collaboration protocol (claim ids, per-claim verdicts, adopted and "
                        "excluded claims)"}

    @router.get("/library")
    def library_list(include_failed: bool = False):
        """Replayable rows come from allowlisted study directories only, and ids stay opaque.

        Failed rows are counted but hidden by default: they belong in the statistics denominator,
        while the replay list should not offer a card that has no result to show.
        """
        rows = library.list_items()
        failed = sum(1 for row in rows if row["status"] not in ("completed", "succeeded"))
        items = rows if include_failed else [row for row in rows if row["status"] in ("completed", "succeeded")]
        return {"items": items, "failed_rows": failed,
                "note": "only the allowlisted study sets are reachable; ids are opaque; "
                        "pass include_failed=true to list runs that failed or exhausted the budget"}

    @router.get("/library/item")
    def library_item(item_id: str = Query(min_length=1, max_length=200)):
        detail = library.get_item(item_id)
        if detail is None:
            raise HTTPException(404, "library item not found")
        return detail

    @router.get("/datasets/summary")
    def datasets_summary():
        return library.dataset_summary()

    @router.get("/capabilities")
    def capabilities():
        return {"schema_version": "1.0", "provider": provider.name, "model": provider.model,
                "simulated": provider.simulated, "auth_enabled": bool(token), "research_only": True,
                "upload_formats": ["json", "jsonl"], "max_body_bytes": MAX_BODY,
                "job_execution": "single-process thread pool", "gpu_required": False,
                "idempotency_header": "Idempotency-Key", "sse_resume_header": "Last-Event-ID"}

    @router.get("/profiles")
    def profiles():
        return profile_catalog()

    @router.get("/profiles/v1/example", response_model=CaseInput)
    def research_example():
        return integration_example()

    @router.post("/cases/inspect")
    def inspect_input(case: CaseInput):
        return inspect_case(case)

    @router.get("/schemas/case")
    def case_schema():
        return CaseInput.model_json_schema()

    @router.get("/agents")
    def agents():
        return agent_catalog()

    @router.get("/workflows")
    def workflows():
        return {
            "legacy": specification(RunConfig()),
            "evidence_first": specification(RunConfig(workflow_backend="langgraph", evidence_first=True)),
            "recommended_config": v1_config().model_dump(),
            "optional_install": "pip install -e '.[graph]'",
            "external_tools": "Reviewed ToolUniverse snapshots for custom synthesis; closed-corpus benchmarks stay isolated.",
        }

    @router.get("/configs")
    def configurations():
        return {k: v.model_dump() for k, v in presets().items()}

    @router.get("/examples")
    def list_examples():
        return [{"id": c.id, "question": c.question, "task": c.task, "synthetic": True} for c in examples().values()]

    @router.get("/examples/{example_id}", response_model=CaseInput)
    def get_example(example_id: str):
        try:
            return examples()[example_id]
        except KeyError:
            raise HTTPException(404, "example not found") from None

    @router.post("/cases", status_code=201)
    def save_case(case: CaseInput):
        return {"case_id": store.save_cases([case])[0], "input_id": case.id}

    @router.post("/cases/upload", status_code=201)
    async def upload_cases(file: UploadFile = File(...)):
        try:
            raw = await file.read(MAX_BODY + 1)
            suffix = Path(file.filename or "").suffix.lower()
            if suffix not in (".json", ".jsonl"):
                raise HTTPException(415, "upload a UTF-8 .json or .jsonl case file")
            text = raw.decode("utf-8-sig")
            rows = [json.loads(line) for line in text.splitlines() if line.strip()] if suffix == ".jsonl" else [json.loads(text)]
            if not 1 <= len(rows) <= 100:
                raise HTTPException(422, "upload between 1 and 100 cases")
            cases = [CaseInput.model_validate(row) for row in rows]
            if len({c.id for c in cases}) != len(cases):
                raise HTTPException(422, "duplicate input case IDs")
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, RecursionError) as exc:
            raise HTTPException(422, "invalid case file: " + type(exc).__name__) from None
        finally:
            await file.close()
        ids = store.save_cases(cases)
        return {"case_ids": ids, "count": len(ids)}

    @router.get("/cases")
    def list_cases(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
        return store.list_cases(limit, offset)

    @router.get("/cases/{case_id}", response_model=CaseInput)
    def get_case(case_id: str):
        try:
            return store.case(case_id)
        except KeyError:
            raise HTTPException(404, "case not found") from None

    @router.delete("/cases/{case_id}", status_code=204)
    def delete_case(case_id: str):
        try:
            with submission_lock:
                store.delete_case(case_id)
        except KeyError:
            raise HTTPException(404, "case not found") from None
        except ValueError:
            raise HTTPException(409, "case has active runs") from None

    def work(run_id, case, config):
        try:
            if store.claim_run(run_id):
                try:
                    result = Engine(provider).run(case, config, lambda event: store.append_event(run_id, event))
                    store.finish(run_id, result=result)
                except Exception as exc:
                    # Worker boundary: always persist terminal failure; never return a fake answer.
                    message = str(exc) if isinstance(exc, ProviderError) else "execution failed: " + type(exc).__name__
                    store.finish(run_id, error=message)
        finally:
            slots.release()

    @router.post("/runs", status_code=202)
    def submit_run(request: RunRequest, idempotency_key: str | None = Header(
            default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")):
        if not provider.simulated and not request.allow_remote_processing:
            raise HTTPException(422, "real API runs require allow_remote_processing=true after data review")
        fingerprint = hashlib.sha256(json.dumps({
            "request": request.model_dump(mode="json"), "provider": provider_identity(provider)
        }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        # Serialize only submission, not inference. The API intentionally runs in one process.
        with submission_lock:
            if idempotency_key:
                try:
                    previous = store.request_run(idempotency_key, fingerprint)
                except ValueError as exc:
                    raise HTTPException(409, str(exc)) from None
                if previous:
                    saved = store.run(previous)
                    return accepted(previous, saved["case_id"], saved["status"], replayed=True)
            if request.case_id:
                case, cid = get_case(request.case_id), request.case_id
            elif request.example_id:
                case, cid = get_example(request.example_id), None
            else:
                case, cid = request.case, None
            if not provider.simulated and case.data_class == "unreviewed":
                raise HTTPException(422, "review/deidentify the case and set data_class before remote processing")
            try:
                dependency_identity(request.config)
            except RuntimeError as exc:
                raise HTTPException(503, str(exc)) from None
            if not slots.acquire(blocking=False):
                raise HTTPException(429, "run queue is full")
            try:
                if cid is None:
                    cid = store.save_cases([case])[0]
                run_id = store.create_run(cid, request.config)
                if idempotency_key:
                    store.remember_request(idempotency_key, fingerprint, run_id)
                app.state.pool.submit(work, run_id, case, request.config)
            except Exception:
                if "run_id" in locals():
                    store.cancel(run_id)
                slots.release()
                raise
            return accepted(run_id, cid, "queued", replayed=False)

    def accepted(run_id, case_id, status, *, replayed):
        return JSONResponse(status_code=202, headers={"Idempotency-Replayed": str(replayed).lower()}, content={
            "run_id": run_id, "case_id": case_id, "status": status,
            "status_url": "/v1/runs/" + run_id, "events_url": "/v1/runs/" + run_id + "/events"})

    @router.get("/runs")
    def list_runs(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
        return store.list_runs(limit, offset)

    @router.get("/runs/{run_id}")
    def get_run(run_id: str):
        try:
            return store.run(run_id)
        except KeyError:
            raise HTTPException(404, "run not found") from None

    @router.post("/runs/{run_id}/cancel")
    def cancel_run(run_id: str):
        get_run(run_id)
        if not store.cancel(run_id):
            raise HTTPException(409, "only queued runs can be cancelled")
        return {"run_id": run_id, "status": "cancelled"}

    @router.get("/runs/{run_id}/events")
    def get_events(run_id: str, after: int = Query(-1, ge=-1, le=2**63-1), limit: int = Query(200, ge=1, le=500)):
        get_run(run_id)
        return store.events(run_id, after, limit)

    @router.get("/runs/{run_id}/stream")
    async def stream_events(run_id: str, after: int = Query(-1, ge=-1, le=2**63-1),
                            last_event_id: int | None = Header(default=None, ge=-1, le=2**63-1)):
        get_run(run_id)

        async def stream():
            cursor = max(after, last_event_id if last_event_id is not None else -1)
            idle = 0
            while True:
                events = store.events(run_id, cursor)
                for event in events:
                    cursor = event["sequence"]
                    yield f"id: {cursor}\nevent: {event['kind']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                if not events and store.run(run_id)["status"] in TERMINAL:
                    yield "event: done\ndata: {}\n\n"
                    break
                if not events:
                    # A role can run for minutes without emitting a frame; comment frames keep
                    # intermediates from treating that silence as a dead connection.
                    idle += 1
                    if idle % 150 == 0:
                        yield ": ping\n\n"
                await asyncio.sleep(.1)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.get("/runs/{run_id}/graph")
    def get_graph(run_id: str):
        run = get_run(run_id)
        if run["result"] is None:
            raise HTTPException(409, "run has no result yet")
        case = visible_case(store.case(run["case_id"]))
        reports = [AgentReport.model_validate(r) for r in run["result"]["reports"]]
        decision = run["result"]["decision"]
        return evidence_graph(reports, case.documents, DecisionOutput.model_validate(decision) if decision else None)

    app.include_router(router)
    return app
