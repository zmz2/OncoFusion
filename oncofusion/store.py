"""SQLite snapshots and append-only run events for a single backend process."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from .schemas import CaseInput, RunConfig, RunResult, TraceEvent

TERMINAL = {"succeeded", "failed", "interrupted", "cancelled", "budget_exhausted"}


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS cases (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id),
                    config TEXT NOT NULL, status TEXT NOT NULL, result TEXT, error TEXT,
                    created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(run_id, sequence));
            """)
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def save_cases(self, cases: list[CaseInput]) -> list[str]:
        ids = ["case-" + uuid.uuid4().hex for _ in cases]
        with self.connect() as conn:
            conn.executemany("INSERT INTO cases VALUES (?, ?, ?)",
                             [(cid, case.model_dump_json(), time.time()) for cid, case in zip(ids, cases)])
        return ids

    def case(self, case_id: str) -> CaseInput:
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM cases WHERE id=?", (case_id,)).fetchone()
        if row is None:
            raise KeyError(case_id)
        return CaseInput.model_validate_json(row["payload"])

    def create_run(self, case_id: str, config: RunConfig) -> str:
        rid, now = "run-" + uuid.uuid4().hex, time.time()
        with self.connect() as conn:
            conn.execute("INSERT INTO runs VALUES (?, ?, ?, 'queued', NULL, NULL, ?, ?)",
                         (rid, case_id, config.model_dump_json(), now, now))
        return rid

    def claim_run(self, run_id: str) -> bool:
        with self.connect() as conn:
            return conn.execute("UPDATE runs SET status='running', updated=? WHERE id=? AND status='queued'",
                                (time.time(), run_id)).rowcount == 1

    def append_event(self, run_id: str, event: TraceEvent) -> None:
        with self.connect() as conn:
            conn.execute("INSERT INTO events VALUES (?, ?, ?)", (run_id, event.sequence, event.model_dump_json()))

    def finish(self, run_id: str, result: RunResult | None = None, error: str | None = None):
        if (result is None) == (error is None):
            raise ValueError("finish requires exactly one of result or error")
        with self.connect() as conn:
            count = conn.execute("UPDATE runs SET status=?, result=?, error=?, updated=? WHERE id=? AND status='running'",
                                 ("failed" if error else ("succeeded" if result.status == "completed" else "budget_exhausted"), result.model_dump_json() if result else None,
                                  error, time.time(), run_id)).rowcount
        if count != 1:
            raise RuntimeError("only a running job can finish")

    def run(self, run_id: str) -> dict:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        item = dict(row)
        item["config"] = json.loads(item["config"])
        item["result"] = json.loads(item["result"]) if item["result"] else None
        return item

    def events(self, run_id: str, after: int = -1, limit: int = 200) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT payload FROM events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT ?",
                                (run_id, after, limit)).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def list_runs(self, limit: int = 50, offset: int = 0) -> list[dict]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT id, case_id, status, error, created, updated FROM runs ORDER BY created DESC LIMIT ? OFFSET ?",
                (limit, offset))]

    def recover_interrupted(self) -> int:
        with self.connect() as conn:
            return conn.execute("UPDATE runs SET status='interrupted', error='backend restarted; resubmit explicitly', updated=? WHERE status IN ('queued','running')",
                                (time.time(),)).rowcount

    def cancel(self, run_id: str) -> bool:
        with self.connect() as conn:
            return conn.execute("UPDATE runs SET status='cancelled', updated=? WHERE id=? AND status='queued'",
                                (time.time(), run_id)).rowcount == 1

    def delete_case(self, case_id: str) -> None:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT 1 FROM runs WHERE case_id=? AND status IN ('queued','running')", (case_id,)).fetchone()
            if row:
                raise ValueError("case has active runs")
            conn.execute("DELETE FROM runs WHERE case_id=?", (case_id,))
            if conn.execute("DELETE FROM cases WHERE id=?", (case_id,)).rowcount != 1:
                raise KeyError(case_id)

    def list_cases(self, limit: int = 50, offset: int = 0) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT id, payload, created FROM cases ORDER BY created DESC LIMIT ? OFFSET ?",
                                (limit, offset)).fetchall()
        return [{"case_id": r["id"], "input_id": json.loads(r["payload"])["id"],
                 "task": json.loads(r["payload"])["task"], "created": r["created"]} for r in rows]
