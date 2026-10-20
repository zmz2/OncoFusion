"""The /app demo surface: self-contained page, verified demo config, replay library, live role events."""
import json
import os
import shutil
import subprocess
import tempfile
import pytest
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
            "trace": [{"kind": "model_usage", "role": "literature", "sequence": 1,
                       "details": {"input_tokens": 10, "output_tokens": 3, "attempts": 1,
                                   "estimated": False, "seconds": 1.5, "evidence_fragments": 2}},
                      {"kind": "agent_started", "role": "literature", "sequence": 2,
                       "details": {"evidence_ids": ["d1:f01", "d1:f02"],
                                   "evidence_coverage": {"candidates": 9, "sent": 2, "chars_total": 900,
                                                         "chars_sent": 200, "tail_dropped": True,
                                                         "documents_without_evidence": []},
                                   "board_findings": 0, "unresolved_items": 0, "source_ids": ["d1"]}},
                      {"kind": "verification_ledger", "role": "decision", "sequence": 3,
                       "details": {"entries": [{"target_claim_id": "literature-01",
                                                 "claim_author": "literature", "reviewer": "verifier",
                                                 "verdict": "confirmed", "reason": "checked",
                                                 "final": True,
                                                 "citations": [{"evidence_id": "d1:f01"}]}],
                                   "reviews": 1, "claims_reviewed": 1}}],
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


def test_demo_page_script_parses_as_javascript(client):
    """A single unescaped quote silently kills the whole inline script: parse it for real."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this environment")
    script = client.get("/app").text.split("<script>", 1)[1].split("</script>", 1)[0]
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(script)
        path = handle.name
    try:
        check = subprocess.run([node, "--check", path], capture_output=True, text=True)
    finally:
        os.unlink(path)
    assert check.returncode == 0, check.stderr[:600]


def test_usage_is_one_reduction_for_live_finish_and_replay(client):
    """Synthetic 100+10+2s and 200+20+3s must read 300/30/5s over 2 calls, however it arrives."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this environment")
    script = client.get("/app").text.split("<script>", 1)[1].split("</script>", 1)[0]
    harness = r'''
const fs = require("fs"), vm = require("vm");
const source = fs.readFileSync(process.argv[2], "utf8");
function el() {
  return { value: "", textContent: "", innerHTML: "", className: "", style: {}, dataset: {},
    children: { length: 0 }, lastChild: null, classList: { add() {}, remove() {} },
    insertAdjacentHTML() {}, removeChild() {}, appendChild() {}, setAttribute() {},
    getAttribute() { return null; }, addEventListener() {}, onclick: null,
    querySelector: () => el(), querySelectorAll: () => [] };
}
const els = {};
const context = {
  console, setTimeout, clearTimeout,
  document: { getElementById: (id) => (els[id] = els[id] || el()),
              querySelectorAll: () => [], addEventListener() {} },
  localStorage: { getItem: () => "", setItem() {}, removeItem() {} },
  window: {}, location: { search: "" },
  fetch: () => new Promise(() => {}),
};
context.document.__els = els;
vm.createContext(context);
vm.runInContext(source, context);
const run = (code) => vm.runInContext(code, context);
let failed = 0;
function check(name, got, want) {
  const a = JSON.stringify(got), b = JSON.stringify(want);
  if (a !== b) { failed += 1; console.error("FAIL " + name + ": got " + a + ", want " + b); }
}
const first = { sequence: 1, kind: "model_usage", role: "timeline",
  details: { input_tokens: 100, output_tokens: 10, seconds: 2, attempts: 1 } };
const second = { sequence: 2, kind: "model_usage", role: "decision",
  details: { input_tokens: 200, output_tokens: 20, seconds: 3, attempts: 1 } };
const finished = { status: "completed", error: null, result: {
  trace: [first, second, { sequence: 3, kind: "agent_reported", role: "literature", details: { output: { findings: [] } } }],
  reports: [], decision: { answer: "NEI", explanation: "synthetic", citations: [], unresolved: [], confidence: null },
  usage: { calls: 2, input_tokens: 300, output_tokens: 30 }, duration_seconds: 5.0 } };
const flat = [first, second].map((e) => Object.assign({ kind: e.kind, role: e.role, sequence: e.sequence }, e.details));
(async () => {
  run("resetState();");
  run("applyEvent('model_usage', " + JSON.stringify(first) + ", 'r');");
  run("applyEvent('model_usage', " + JSON.stringify(second) + ", 'r');");
  run("applyEvent('model_usage', " + JSON.stringify(second) + ", 'r');");
  check("live totals ignore a duplicate frame", run("usageTotals()"), { in: 300, out: 30, sec: 5, calls: 2 });
  check("one event is not added twice", run("STATE.decision.in"), 200);
  run("api = async () => (" + JSON.stringify(finished) + "); loadQueue = async () => {};");
  await run("finish('r')");
  check("finish over frames already applied", run("usageTotals()"), { in: 300, out: 30, sec: 5, calls: 2 });
  check("finish keeps the per-role split", run("[STATE.timeline.in, STATE.decision.in]"), [100, 200]);
  check("answer panel shows the run total", /2 次 · 300 \+ 30 · 5s/.test(run("document.__els.answer.innerHTML")), true);
  run("applyEvent('model_usage', " + JSON.stringify(second) + ", 'r');");
  check("reconnect replaying a frame changes nothing", run("usageTotals()"), { in: 300, out: 30, sec: 5, calls: 2 });
  run("resetState(); applyUsageEvents(" + JSON.stringify(flat) + "); S.result = " + JSON.stringify(finished.result) + ";");
  check("replay totals", run("usageTotals()"), { in: 300, out: 30, sec: 5, calls: 2 });
  run("resetState(); applyUsageEvents(" + JSON.stringify(flat) + ");");
  check("replay without a stored usage row falls back to the trace", run("usageTotals()"), { in: 300, out: 30, sec: 5, calls: 2 });
  const repair = Object.assign({}, first, { sequence: 9,
    details: { input_tokens: 50, output_tokens: 5, seconds: 1, attempts: 2 } });
  run("resetState(); STATE.decision.output = { answer: 'NEI', explanation: 'synthetic' };");
  run("applyEvent('model_usage', " + JSON.stringify(first) + ", 'r');");
  run("applyEvent('model_usage', " + JSON.stringify(repair) + ", 'r');");
  check("two calls inside one role are two calls", run("usageTotals().calls"), 2);
  check("per-role totals include the repair", run("[STATE.timeline.calls, STATE.timeline.in]"), [2, 150]);
  check("answer panel counts calls, not roles", /2 次 · 150 \+ 15 · 3s/.test(run("document.__els.answer.innerHTML")), true);
  if (failed) process.exit(1);
})();
'''
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(script)
        script_path = handle.name
    with tempfile.NamedTemporaryFile("w", suffix=".test.js", delete=False, encoding="utf-8") as handle:
        handle.write(harness)
        harness_path = handle.name
    try:
        check = subprocess.run([node, harness_path, script_path], capture_output=True, text=True)
    finally:
        os.unlink(script_path)
        os.unlink(harness_path)
    assert check.returncode == 0, (check.stdout + check.stderr)[-2000:]


def test_claims_table_separates_verifier_final_from_role_feedback(client):
    """A specialist's verdict on an earlier claim is feedback, not a second verifier run."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this environment")
    script = client.get("/app").text.split("<script>", 1)[1].split("</script>", 1)[0]
    harness = r'''
const fs = require("fs"), vm = require("vm");
const source = fs.readFileSync(process.argv[2], "utf8");
function el() {
  return { value: "", textContent: "", innerHTML: "", className: "", style: {}, dataset: {},
    children: { length: 0 }, lastChild: null, classList: { add() {}, remove() {} },
    insertAdjacentHTML() {}, removeChild() {}, appendChild() {}, setAttribute() {},
    getAttribute() { return null; }, addEventListener() {}, onclick: null,
    querySelector: () => el(), querySelectorAll: () => [] };
}
const els = {};
const context = {
  console, setTimeout, clearTimeout,
  document: { getElementById: (id) => (els[id] = els[id] || el()),
              querySelectorAll: () => [], addEventListener() {} },
  localStorage: { getItem: () => "", setItem() {}, removeItem() {} },
  window: {}, location: { search: "" },
  fetch: () => new Promise(() => {}),
};
context.document.__els = els;
vm.createContext(context);
vm.runInContext(source, context);
const run = (code) => vm.runInContext(code, context);
let failed = 0;
function check(name, got, want) {
  const a = JSON.stringify(got), b = JSON.stringify(want);
  if (a !== b) { failed += 1; console.error("FAIL " + name + ": got " + a + ", want " + b); }
}
run(`STATE.literature = { output: { findings: [{ claim_id: "literature-01", author_role: "literature",
  statement: "unknown: the source does not measure this claim", scope: "source",
  evidence_level: "curated", material_status: "unknown",
  material_basis: "selection_not_covered", used_claim_ids: [] }] } };
STATE.pathology = { output: { verdicts: [{ target_claim_id: "literature-01",
  reviewer_role: "pathology", verdict: "insufficient", note: "role feedback" }] } };
STATE.verifier = { output: { verdicts: [{ target_claim_id: "literature-01",
  reviewer_role: "verifier", verdict: "confirmed", note: "final check" }] } };
STATE.decision = { output: { adopted_claim_ids: ["literature-01"], rejected_claim_ids: [] } };`);
run("renderClaims()");
const html = run("document.__els.claims.innerHTML");
check("verifier final verdict is shown", /已确认/.test(html), true);
check("specialist feedback is shown as feedback", /反馈：病理与癌种语境「证据不足」/.test(html), true);
check("missing material says why it is missing", /缺失来源：选集未覆盖/.test(html), true);
check("feedback is not the verifier final cell", /warn">证据不足/.test(html), false);
check("table warns that rows are not reruns",
  /一张表出现多行 verdict 不代表 Verifier 运行了多次/.test(html), true);
const feedbackBlock = run(`outputBlock({ verdicts: [{ target_claim_id: "literature-01",
  verdict: "insufficient", note: "role feedback" }] }, "pathology")`);
check("specialist card labels its verdicts as feedback", feedbackBlock.indexOf("不是最终核验") >= 0, true);
const finalBlock = run(`outputBlock({ verdicts: [{ target_claim_id: "literature-01",
  verdict: "confirmed", note: "final check" }] }, "verifier")`);
check("verifier card labels its verdicts as final", finalBlock.indexOf("不是最终核验") < 0, true);
const basisBlock = run(`outputBlock({ findings: [{ statement: "unknown: no exposure record",
  relation: "NEI", scope: "exposure", evidence_level: "absent", material_status: "unknown",
  material_basis: "not_recorded", citations: [] }] }, "drug")`);
check("role card carries the missing-material basis", basisBlock.indexOf("原文未记录") >= 0, true);
run(`S.ledger = [
  { target_claim_id: "literature-01", claim_author: "literature", reviewer: "pathology",
    verdict: "insufficient", reason: "role feedback", final: false,
    citations: [{ evidence_id: "pmid-1:f01" }] },
  { target_claim_id: "literature-01", claim_author: "literature", reviewer: "verifier",
    verdict: "confirmed", reason: "checked against the source", final: true,
    citations: [{ evidence_id: "pmid-1:f01" }] } ];`);
const ledger = run("ledgerBlock()");
check("ledger names the reviewer", /病理与癌种语境/.test(ledger), true);
check("ledger keeps the reason and citation count", /checked against the source/.test(ledger)
  && /<td>1<\/td>/.test(ledger), true);
check("ledger separates final from feedback",
  /最终判定 1 条，专业角色反馈 1 条/.test(ledger), true);
if (failed) process.exit(1);
'''
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(script)
        script_path = handle.name
    with tempfile.NamedTemporaryFile("w", suffix=".test.js", delete=False, encoding="utf-8") as handle:
        handle.write(harness)
        harness_path = handle.name
    try:
        check = subprocess.run([node, harness_path, script_path], capture_output=True, text=True)
    finally:
        os.unlink(script_path)
        os.unlink(harness_path)
    assert check.returncode == 0, (check.stdout + check.stderr)[-2000:]


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


def test_dataset_summary_p50_is_the_median(client, tmp_path, monkeypatch):
    """Even sample count: p50 averages the two middle values, same as compare_arms/real_metrics."""
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "results" / "v1"
    folder = root / "real_class6c_mtb" / "v1_class" / "0"
    folder.mkdir(parents=True)
    for index, seconds in enumerate((10.0, 20.0, 30.0, 40.0)):
        data = build_case_file("mtb-X-q%d" % index)
        data["duration_seconds"] = seconds
        (folder / ("mtb-X-q%d.json" % index)).write_text(json.dumps(data))
    (folder / "summary.json").write_text("{}")
    monkeypatch.setenv("ONCOFUSION_RESULTS_DIR", str(root))
    arms = client.get("/v1/datasets/summary").json()["arms"]
    row = next(a for a in arms if a["study"] == "real_class6c_mtb")
    assert row["seconds_p50"] == 25.0, "p50 must be the median, not the upper middle sample"


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
    assert detail["trace"][0]["sequence"] == 1, "replay deduplicates usage by trace sequence"
    started = next(t for t in detail["trace"] if t["kind"] == "agent_started")
    assert started["evidence_ids"] == ["d1:f01", "d1:f02"], "the page draws each node's sent spans from here"
    assert started["evidence_coverage"]["candidates"] == 9
    assert started["evidence_coverage"]["sent"] == 2 and started["evidence_coverage"]["tail_dropped"]
    ledger = next(t for t in detail["trace"] if t["kind"] == "verification_ledger")
    assert ledger["ledger"][0]["reviewer"] == "verifier"
    assert ledger["ledger"][0]["reason"] == "checked", "the replay keeps the ledger, not just a count"
    node = next(r for r in detail["roles"] if r["role"] == "literature")
    assert node["evidence_coverage"]["chars_sent"] == 200 and node["source_ids"] == ["d1"]
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
