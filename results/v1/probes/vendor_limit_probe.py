"""Replay the failed real cases at the vendor's own output ceiling, no self-imposed thinking cap."""
import json
import os
import time
from pathlib import Path

import httpx

KEY = Path(os.path.expanduser("~/连接/api-users/Jev/api-key")).read_text().strip()
BASE = "http://127.0.0.1:28180/v1"
MODEL = "hc-qwen38-27b-fp8"
rec = json.loads(Path(os.path.expanduser("~/BioOncoFusion/results/v1/probes/role1_request.json")).read_text())
system, payload = rec["system"], rec["payload"]

for label, mt, extra in [("vendor_5000", 5000, {}), ("vendor_5000_batch", 5000, {}),
                         ("over_limit_5001", 5001, {})]:
    body = {"model": MODEL, "messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            "max_tokens": mt, "response_format": {"type": "json_object"}}
    headers = {"Authorization": "Bearer " + KEY, "X-Request-ID": "vl-" + label}
    if "batch" in label:
        headers["X-HC-Workload"] = "batch"
    t0 = time.time()
    with httpx.Client(timeout=900) as c:
        r = c.post(BASE + "/chat/completions", json=body, headers=headers)
    dt = time.time() - t0
    if r.status_code != 200:
        print(f"{label}: http={r.status_code} {dt:.1f}s body={r.text[:170]}", flush=True)
        continue
    d = r.json()
    u = d.get("usage") or {}
    det = u.get("completion_tokens_details") or {}
    ch = (d.get("choices") or [{}])[0]
    content = (ch.get("message") or {}).get("content") or ""
    try:
        parsed = json.loads(content)
        shape = "json_ok keys=" + str(list(parsed)[:6]) if isinstance(parsed, dict) else "json_ok list"
    except Exception as exc:  # noqa: BLE001
        shape = "json_fail:" + str(exc)[:50]
    print(f"{label}: {dt:.1f}s finish={ch.get('finish_reason')} prompt={u.get('prompt_tokens')} "
          f"completion={u.get('completion_tokens')} reasoning={det.get('reasoning_tokens')} "
          f"chars={len(content)} {shape} pool={r.headers.get('x-hc-route-pool')}", flush=True)
