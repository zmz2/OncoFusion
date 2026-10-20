"""Compare latency/finish_reason with and without an explicit thinking budget."""
import json
import os
import time
from pathlib import Path

import httpx

KEY = Path(os.path.expanduser("~/连接/api-users/Jev/api-key")).read_text().strip()
BASE = "http://127.0.0.1:28180/v1"
MODEL = "hc-qwen38-27b-fp8"

SYSTEM = ("Return strict JSON matching the requested schema. Cite source ids exactly. " * 3)
PAYLOAD = {"role": "literature", "question": "Summarise visible evidence for the claim.",
           "documents": [{"id": "doc-1", "text": "The patient had stable disease on follow-up imaging."}]}
body = {"model": MODEL, "messages": [{"role": "system", "content": SYSTEM},
                                     {"role": "user", "content": json.dumps(PAYLOAD, ensure_ascii=False)}],
        "max_tokens": 1500, "response_format": {"type": "json_object"}}

for label, extra in [("default_thinking", {}), ("thinking_200", {"thinking_token_budget": 200})]:
    req = dict(body)
    req.update(extra)
    t0 = time.time()
    try:
        with httpx.Client(timeout=600) as c:
            r = c.post(BASE + "/chat/completions", json=req, headers={
                "Authorization": "Bearer " + KEY, "X-Request-ID": "think-" + label,
                "X-HC-Workload": "batch", "X-Session-ID": "oncofusion:probe"})
    except Exception as exc:  # noqa: BLE001
        print(f"{label}: transport {type(exc).__name__} after {time.time()-t0:.1f}s", flush=True)
        continue
    dt = time.time() - t0
    if r.status_code != 200:
        print(f"{label}: http={r.status_code} {dt:.1f}s body={r.text[:200]}", flush=True)
        continue
    d = r.json()
    u = d.get("usage") or {}
    det = u.get("completion_tokens_details") or {}
    ch = (d.get("choices") or [{}])[0]
    content = (ch.get("message") or {}).get("content") or ""
    try:
        json.loads(content)
        parsed = "json_ok"
    except Exception as exc:  # noqa: BLE001
        parsed = "json_fail:" + str(exc)[:60]
    print(f"{label}: {dt:.1f}s finish={ch.get('finish_reason')} completion={u.get('completion_tokens')} "
          f"reasoning={det.get('reasoning_tokens')} chars={len(content)} {parsed} "
          f"pool={r.headers.get('x-hc-route-pool')}", flush=True)
    print(f"  head={content[:200]!r}", flush=True)
