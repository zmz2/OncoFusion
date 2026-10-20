"""Capture the real first-role request, then replay it at different output limits."""
import json
import os
import time
from pathlib import Path

import httpx
from oncofusion.datasets import read_jsonl
from oncofusion.engine import Engine
from oncofusion.profiles import v1_config
from oncofusion.providers import ProviderError
from oncofusion.schemas import CaseInput

KEY = Path(os.path.expanduser("~/连接/api-users/Jev/api-key")).read_text().strip()
BASE = "http://127.0.0.1:28180/v1"
MODEL = "hc-qwen38-27b-fp8"
ROOT = Path.home() / "BioOncoFusion"
captured = []


class Capture:
    name = "capture"
    model = MODEL
    simulated = True

    def complete(self, system, payload, max_tokens, temperature, seed):
        captured.append({"system": system, "payload": payload, "max_tokens": max_tokens,
                         "temperature": temperature, "seed": seed})
        raise ProviderError("capture stop")


case = CaseInput.model_validate(read_jsonl(ROOT / "data/mtbbench/inputs.jsonl")[0])
try:
    Engine(Capture()).run(case, v1_config())
except ProviderError:
    pass
rec = captured[0]
system, payload = rec["system"], rec["payload"]
body_bytes = len(system.encode()) + len(json.dumps(payload, ensure_ascii=False).encode())
print("role=%s system_bytes=%d payload_bytes=%d total_bytes=%d est_tokens=%d max_tokens=%d" % (
    payload.get("role"), len(system.encode()), len(json.dumps(payload, ensure_ascii=False).encode()),
    body_bytes, body_bytes // 4, rec["max_tokens"]), flush=True)
print("system_head=" + repr(system[:220]), flush=True)
Path(ROOT / "results/v1/probes/role1_request.json").write_text(json.dumps(rec, ensure_ascii=False))

for label, mt, workload, extra in [("mt1500_auto", 1500, None, {}), ("mt1500_latency", 1500, "latency", {}),
                                   ("mt400_latency", 400, "latency", {}),
                                   ("mt1500_think300", 1500, "latency", {"thinking_token_budget": 300})]:
    body = {"model": MODEL, "messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            "max_tokens": mt, "response_format": {"type": "json_object"}}
    body.update(extra)
    headers = {"Authorization": "Bearer " + KEY, "X-Request-ID": "cap-" + label,
               "X-Session-ID": "oncofusion:probe:role1"}
    if workload:
        headers["X-HC-Workload"] = workload
    t0 = time.time()
    try:
        with httpx.Client(timeout=600) as c:
            r = c.post(BASE + "/chat/completions", json=body, headers=headers)
    except Exception as exc:  # noqa: BLE001
        print("%s: transport %s after %.1fs" % (label, type(exc).__name__, time.time() - t0), flush=True)
        continue
    dt = time.time() - t0
    if r.status_code != 200:
        print("%s: http=%d %.1fs body=%s" % (label, r.status_code, dt, r.text[:200]), flush=True)
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
        parsed = "json_fail:" + str(exc)[:50]
    print("%s: %.1fs finish=%s prompt=%s completion=%s reasoning=%s chars=%d %s pool=%s applied=%s" % (
        label, dt, ch.get("finish_reason"), u.get("prompt_tokens"), u.get("completion_tokens"),
        det.get("reasoning_tokens"), len(content), parsed, r.headers.get("x-hc-route-pool"),
        r.headers.get("x-hc-workload-applied")), flush=True)
