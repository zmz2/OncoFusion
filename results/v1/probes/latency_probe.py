"""Measure per-role latency and truncation behaviour against the real gateway."""
import json
import os
import time
from pathlib import Path

os.environ["ONCOFUSION_TIMEOUT"] = "600"

import httpx
from oncofusion.datasets import read_jsonl
from oncofusion.engine import Engine
from oncofusion.profiles import v1_config
from oncofusion.providers import provider_from_env
from oncofusion.schemas import CaseInput

KEY = Path(os.path.expanduser("~/连接/api-users/Jev/api-key")).read_text().strip()
BASE = "http://127.0.0.1:28180/v1"
MODEL = "hc-qwen38-27b-fp8"
ROOT = Path.home() / "BioOncoFusion"

calls = []
provider = provider_from_env()
original = provider.complete


def timed(system, payload, max_tokens, temperature, seed):
    t0 = time.time()
    err = None
    reply = None
    try:
        reply = original(system, payload, max_tokens, temperature, seed)
    except Exception as exc:  # noqa: BLE001
        err = type(exc).__name__ + ": " + str(exc)[:140]
    dt = time.time() - t0
    role = payload.get("role") if isinstance(payload, dict) else "?"
    calls.append({"role": role, "seconds": round(dt, 2),
                  "input_tokens": reply.input_tokens if reply else None,
                  "output_tokens": reply.output_tokens if reply else None,
                  "estimated": getattr(reply, "estimated", None) if reply else None,
                  "error": err})
    print("  role=%s %.1fs in=%s out=%s err=%s" % (
        role, dt, reply.input_tokens if reply else None,
        reply.output_tokens if reply else None, err), flush=True)
    return reply


provider.complete = timed

case = CaseInput.model_validate(read_jsonl(ROOT / "data/mtbbench/inputs.jsonl")[0])
print("case=%s docs=%d task=%s" % (case.id, len(case.documents), case.task), flush=True)
result = Engine(provider).run(case, v1_config())
usage = getattr(result, "usage", None)
print(json.dumps({"status": result.status, "calls": calls,
                  "usage": usage.model_dump() if usage is not None and hasattr(usage, "model_dump") else usage},
                 ensure_ascii=False, indent=2), flush=True)

print("\n== raw truncation / JSON-mode check", flush=True)
context = "Analyse the supplied oncology evidence and return strict JSON. " * 40
cases_payload = {"role": "literature", "question": "Summarise the evidence.",
                 "documents": [{"id": "d1", "text": "Patient shows stable disease after therapy."}]}
bodies = {
    "json_mode": {"model": MODEL, "messages": [
        {"role": "system", "content": "Return only JSON."},
        {"role": "user", "content": context + json.dumps(cases_payload, ensure_ascii=False)}],
        "max_tokens": 1500, "response_format": {"type": "json_object"}},
    "plain": {"model": MODEL, "messages": [
        {"role": "user", "content": context + 'Reply with {"answer": string} only.'}],
        "max_tokens": 1500},
}
for label, body in bodies.items():
    t0 = time.time()
    try:
        with httpx.Client(timeout=600) as c:
            r = c.post(BASE + "/chat/completions", json=body, headers={
                "Authorization": "Bearer " + KEY, "X-Request-ID": "probe-" + label,
                "X-HC-Workload": "batch"})
    except Exception as exc:  # noqa: BLE001
        print("  %s: transport error %s after %.1fs" % (label, type(exc).__name__, time.time() - t0), flush=True)
        continue
    dt = time.time() - t0
    if r.status_code != 200:
        print("  %s: http=%d %.1fs body=%s" % (label, r.status_code, dt, r.text[:180]), flush=True)
        continue
    d = r.json()
    choice = (d.get("choices") or [{}])[0]
    u = d.get("usage") or {}
    det = u.get("completion_tokens_details") or {}
    content = (choice.get("message") or {}).get("content") or ""
    try:
        json.loads(content)
        parsed = "ok"
    except Exception as exc:  # noqa: BLE001
        parsed = "fail:" + str(exc)[:70]
    print("  %s: %.1fs finish=%s completion=%s reasoning=%s chars=%d json=%s" % (
        label, dt, choice.get("finish_reason"), u.get("completion_tokens"),
        det.get("reasoning_tokens"), len(content), parsed), flush=True)
    print("     content_head=" + repr(content[:160]), flush=True)
