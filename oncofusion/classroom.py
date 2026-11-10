"""Classroom projection over vote-v1 records. Inference still uses the /v1 run API."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .schemas import CaseInput, RunConfig, RunRequest
from .schemas import FragmentCitation
from .evidence import fragment_documents, resolve_fragment_citations, visible_case
from .store import TERMINAL

MODEL_DISPLAY = "千问 3.6 35B-A3B"
ROLE_NAMES = {"literature": "文献", "timeline": "时间线", "genomics": "基因",
              "pathology": "病理与语境", "drug": "药物", "generalist": "单Agent"}


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def utc_time(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat() if timestamp else None


class ClassroomRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_alias: str = Field(pattern=r"^case-0[1-3]$")
    system: str = Field(pattern=r"^(B0|OncoFusion)$")


class Classroom:
    def __init__(self, store, provider, root=None):
        self.store, self.provider = store, provider
        self.root = Path(root or os.getenv("ONCOFUSION_CLASSROOM_ROOT", "runtime/classroom_web_v2"))

    def protocol(self):
        path = self.root / "protocol.json"
        if not path.is_file():
            raise HTTPException(503, "classroom data is not prepared; run prepare_classroom_v2.py")
        return json.loads(path.read_text())

    def annotations(self):
        path = self.root / "annotations.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def case(self, alias):
        info = next((c for c in self.protocol()["cases"] if c["alias"] == alias), None)
        if info is None:
            raise HTTPException(404, "classroom case not found")
        case = CaseInput.model_validate_json((self.root / "inputs" / (alias + ".json")).read_text())
        return info, case

    def request_key(self, alias, system):
        return f"classroom-v2-{self.protocol()['batch_id']}-{alias}-{system}"

    def new_id(self, alias, system):
        with self.store.connect() as connection:
            row = connection.execute("SELECT run_id FROM request_keys WHERE key=?",
                                     (self.request_key(alias, system),)).fetchone()
        return row[0] if row else None

    def input_view(self, alias, private=False):
        info, case = self.case(alias)
        notes = self.annotations().get("cases", {}).get(alias, {})
        documents = [doc.model_dump(mode="json") for doc in case.documents
                     if doc.available_stage <= case.stage
                     and (case.as_of_day is None or doc.event_day is None or doc.event_day <= case.as_of_day)]
        key_citations = json.loads((self.root / "history" / (alias + ".json")).read_text()).get("decision", {}).get("citations", [])
        unique = {(c["document_id"], c["start"], c["end"]): c for c in key_citations}
        excerpts = []
        for index, citation in enumerate(list(unique.values())[:3]):
            excerpts.append({"document_id": citation["document_id"], "start": citation["start"],
                             "end": citation["end"], "quote": citation["quote"] if private else None,
                             "summary_zh": notes.get("source_summaries", [])[index]
                             if index < len(notes.get("source_summaries", [])) else "原文保存在服务器；公开版省略。",
                             "redaction": None if private else "原文省略 · 病例资料再发布许可未确认"})
        return {"alias": alias, "title": info["title"], "question_original": case.question if private else None,
                "question_zh": notes.get("question_zh", info["question_zh"]), "options": case.options,
                "stage": case.stage if private else None, "cutoff_label": "与原始运行相同的信息截止点",
                "input_fingerprint": digest(case.model_dump(mode="json")), "excerpts": excerpts,
                "source_groups": [{"kind": kind, "documents": sum(d["kind"] == kind for d in documents),
                                   "characters": sum(len(d["text"]) for d in documents if d["kind"] == kind)}
                                  for kind in sorted({d["kind"] for d in documents})],
                "documents": documents if private else [], "private": private,
                "redaction": None if private else "原始问题和完整病史保存在服务器。下方中文为脱敏概述，不是原文。"}

    def record(self, record_id, private=False):
        historical = record_id.startswith("history-")
        protocol = self.protocol()
        if historical:
            alias = record_id.removeprefix("history-")
            self.case(alias)
            path = self.root / "history" / (alias + ".json")
            result = json.loads(path.read_text())
            status = "succeeded" if result["status"] == "completed" else "failed"
            system, created = "OncoFusion", protocol["history"][alias]["timestamp"]
            config, error = result["config"], None
            code_commit = protocol["history"][alias]["commit"]
        else:
            try:
                run = self.store.run(record_id)
            except KeyError:
                raise HTTPException(404, "run not found") from None
            match = [(c["alias"], system) for c in protocol["cases"] for system in ["B0", "OncoFusion"]
                     if self.new_id(c["alias"], system) == record_id]
            if not match:
                raise HTTPException(404, "run is not in this classroom batch")
            alias, system = match[0]
            result, status, config, error = run["result"], run["status"], run["config"], run["error"]
            created, code_commit = utc_time(run["created"]), protocol["code_commit"]
        ballot_rows = (result or {}).get("ballots", [])
        _, source_case = self.case(alias)
        visible = visible_case(source_case)
        query = " ".join(filter(None, [visible.question, *[str(v) for v in visible.entities.model_dump().values() if v]]))
        _, evidence_index, _ = fragment_documents(visible.documents, config["fragment_chars"],
            config["max_fragments_per_document"], query, config["fragment_budget"], role="decision")
        def citations(ids):
            values = [c.model_dump(mode="json") for c in resolve_fragment_citations(
                [FragmentCitation(evidence_id=eid) for eid in ids], evidence_index)]
            if not private:
                for citation in values:
                    citation["quote"] = None
                    citation["redaction"] = "原文省略 · 完整引用保存在服务器"
            return values
        note = self.annotations().get("records", {}).get(record_id, {})
        ballots = []
        for ballot in ballot_rows:
            summary = note.get("ballots", {}).get(ballot["role"], {})
            # Reviewed translations are attached to exactly one saved output, never reused by role alone.
            translated = summary.get("summary_zh") if summary.get("reason_sha256") == digest(ballot["brief_reason"]) else None
            ballots.append({**{k: ballot.get(k) for k in ["role", "label", "status", "confidence", "evidence_ids"]},
                            "brief_reason": ballot["brief_reason"] if private else None,
                            "summary_zh": translated, "findings": ballot.get("findings", []) if private else [],
                            "citations": citations(ballot.get("evidence_ids", [])),
                            "error": ballot.get("error", "") if private else None})
        vote = (result or {}).get("vote_result")
        arbitration_citations = citations((vote or {}).get("arbitration", {}).get("evidence_ids", []))
        if vote:
            vote = json.loads(json.dumps(vote))
            if not private:
                arb = vote["arbitration"]
                arb["explanation_original"] = None
                arb["explanation"] = note.get("arbitration_zh", "")
                arb["unresolved"] = []
                arb["error"] = "仲裁失败；保留初始票决，详见私密审计" if arb.get("error") else ""
        decision = (result or {}).get("decision")
        if decision:
            decision = json.loads(json.dumps(decision))
            if not private:
                decision["explanation"] = note.get("decision_zh", "最终标签由已记录票决与条件仲裁决定。")
                decision["unresolved"] = []
                for citation in decision["citations"]:
                    citation["quote"] = None
                    citation["redaction"] = "原文省略 · 完整引用保存在服务器"
        terminal = status in TERMINAL
        # Gold is joined only here, after inference is terminal. It never enters CaseInput or RunRequest.
        labels = json.loads((self.root / "labels.json").read_text()) if terminal else {}
        return {"id": record_id, "source": "historical" if historical else "new", "case_alias": alias,
                "system": system, "status": status, "created_at": created, "code_commit": code_commit,
                "model_display": MODEL_DISPLAY, "model_id": (result or {}).get("model", self.provider.model),
                "simulated": (result or {}).get("simulated", self.provider.simulated),
                "config": config, "input": self.input_view(alias, private), "ballots": ballots,
                "vote": vote, "decision": decision, "arbitration_citations": arbitration_citations,
                "usage": (result or {}).get("usage"),
                "seconds": (result or {}).get("duration_seconds"),
                "gold": labels.get(alias), "error": error,
                "fingerprint": (result or {}).get("fingerprint"), "private": private}


def install_classroom(router, store, provider, submit_run):
    classroom = Classroom(store, provider)

    @router.get("/classroom/catalog")
    def catalog():
        protocol = classroom.protocol()
        return {"model_display": MODEL_DISPLAY, "simulated": provider.simulated,
                "cases": protocol["cases"], "configs": protocol["configs"],
                "code_commit": protocol["code_commit"], "batch_id": protocol["batch_id"],
                "scope": "三例 × 两系统各一次；刷新与重复点击复用原任务",
                "records": [{"id": "history-" + c["alias"], "case_alias": c["alias"],
                             "source": "historical", "system": "OncoFusion",
                             "status": classroom.record("history-" + c["alias"])["status"]}
                            for c in protocol["cases"]]
                + [{"id": classroom.new_id(c["alias"], system), "case_alias": c["alias"],
                    "source": "new", "system": system,
                    "status": store.run(classroom.new_id(c["alias"], system))["status"]}
                   for c in protocol["cases"] for system in ["B0", "OncoFusion"]
                   if classroom.new_id(c["alias"], system)]}

    @router.get("/classroom/cases/{alias}")
    def case_view(alias: str, private: bool = False):
        return classroom.input_view(alias, private)

    @router.post("/classroom/runs", status_code=202)
    def start(request: ClassroomRequest):
        _, case = classroom.case(request.case_alias)
        config = RunConfig.model_validate(classroom.protocol()["configs"][request.system])
        return submit_run(RunRequest(case=case, config=config, allow_remote_processing=True),
                          idempotency_key=classroom.request_key(request.case_alias, request.system))

    @router.get("/classroom/records/{record_id}")
    def record(record_id: str, private: bool = False):
        return classroom.record(record_id, private)

    @router.get("/classroom/records/{record_id}/events")
    def events(record_id: str, after: int = Query(-1, ge=-1), private: bool = False):
        record = classroom.record(record_id, private)
        if record["source"] == "historical":
            raw = json.loads((classroom.root / "history" / (record["case_alias"] + ".json")).read_text())["trace"]
            rows = [e for e in raw if e["sequence"] > after][:500]
        else:
            rows = store.events(record_id, after, 500)
        if private:
            return rows
        result = []
        for event in rows:
            details = event["details"]
            safe = {key: details[key] for key in ["planned_roles", "simulated", "execution_model", "vote_pool",
                    "vote_rule", "input_tokens", "output_tokens", "seconds", "attempts", "evidence_fragments",
                    "initial_label", "final_label", "status", "triggered", "evidence_ids", "attempt"] if key in details}
            if "ballot" in details:
                safe["ballot"] = {key: details["ballot"].get(key) for key in
                                  ["role", "status", "label", "confidence", "evidence_ids"]}
            result.append({"sequence": event["sequence"], "kind": event["kind"],
                           "role": event["role"], "details": safe})
        return result

    return classroom
