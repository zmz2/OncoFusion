#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
RUN_NAME="${CIVIC_VOTE_RUN_NAME:-civic_vote_confirm_20261110}"
RUN="$ROOT/results/v1/$RUN_NAME"
DATASET="$ROOT/data/civicfact-pmidids"
PLAN="$ROOT/experiments/civic_vote_confirm_20261110.json"

if [[ ! -f "$HOME/.config/oncofusion/real-api.env" ]]; then
  echo "Missing private real API environment file" >&2
  exit 1
fi
if [[ -e "$RUN" ]]; then
  echo "Refusing to overwrite existing result directory: $RUN" >&2
  exit 1
fi
if [[ ! -f "$DATASET/inputs.jsonl" || ! -f "$DATASET/_gold/labels.jsonl" ]]; then
  echo "CIViC dataset is not mounted at $DATASET" >&2
  exit 1
fi

set -a
. "$HOME/.config/oncofusion/real-api.env"
set +a
export ONCOFUSION_API_CONCURRENCY=20

mkdir -p "$RUN"
printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$RUN/started_at_utc.txt"

.venv/bin/python - <<'PY' > "$RUN/provider_settings.json"
import json, urllib.request
from oncofusion.providers import provider_from_env, provider_identity
p = provider_from_env()
inner = getattr(p, "inner", p)
identity = provider_identity(p)
if identity.get("simulated") or identity.get("model") != "hc-qwen38-27b-fp8":
    raise SystemExit("provider is not the frozen real CIViC model")
if identity.get("scheduler_capacity") != 20:
    raise SystemExit("global API scheduler is not configured for 20 calls")
request = urllib.request.Request(
    inner.base_url.rstrip("/") + "/models",
    headers={"Authorization": "Bearer " + inner.api_key})
with urllib.request.urlopen(request, timeout=15) as response:
    models = [item.get("id") for item in json.load(response).get("data", [])]
if models != ["hc-qwen38-27b-fp8"]:
    raise SystemExit("provider model listing differs from the frozen model")
print(json.dumps(identity, ensure_ascii=False, indent=2))
PY

.venv/bin/python - <<'PY' > "$RUN/frozen_runtime.json"
import hashlib, importlib.metadata, json, platform, subprocess
from pathlib import Path
def digest(name):
    return hashlib.sha256(Path(name).read_bytes()).hexdigest()
code_files = [
    "oncofusion/vote_runner.py", "oncofusion/voting.py", "oncofusion/evidence.py",
    "oncofusion/agent_design.py", "oncofusion/profiles.py", "oncofusion/schemas.py",
    "oncofusion/providers.py", "oncofusion/experiments.py", "scripts/run_study.py",
    "scripts/run_vote_arbitration.py",
]
payload = {
    "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "plan_sha256": digest("experiments/civic_vote_confirm_20261110.json"),
    "source_register_sha256": digest("experiments/civic_vote_confirm_source_register_20261110.json"),
    "inputs_sha256": digest("data/civicfact-pmidids/inputs.jsonl"),
    "gold_sha256": digest("data/civicfact-pmidids/_gold/labels.jsonl"),
    "inference_sources_sha256": {name: digest(name) for name in code_files},
    "started_at_utc": Path("results/v1/civic_vote_confirm_20261110/started_at_utc.txt").read_text().strip(),
    "python": platform.python_version(),
    "packages": {},
    "private_runtime_path": "results/v1/civic_vote_confirm_20261110",
}
for name in ("pydantic", "openai", "langgraph"):
    try:
        payload["packages"][name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        payload["packages"][name] = "not-installed"
print(json.dumps(payload, ensure_ascii=False, indent=2))
PY

.venv/bin/python scripts/run_study.py \
  --plan "$PLAN" \
  --dataset "$DATASET" \
  --out "$RUN" \
  --allow-remote \
  --execution-cap 234 \
  --workers 5 \
  --interleave-treatments
