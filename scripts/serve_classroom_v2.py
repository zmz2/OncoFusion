"""Run a separate, loopback-only classroom service with a real provider."""
import argparse
import json
import os
import subprocess
from pathlib import Path

import uvicorn

from oncofusion.api import create_app
from oncofusion.engine import implementation_digest
from oncofusion.providers import provider_from_env, provider_identity


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8181)
    args = parser.parse_args()
    os.environ["ONCOFUSION_CLASSROOM_ROOT"] = str(args.root.resolve())
    os.environ["ONCOFUSION_DEMO_REQUIRE_REAL"] = "1"
    os.environ["ONCOFUSION_API_CONCURRENCY"] = "20"
    provider = provider_from_env()
    if provider.simulated:
        raise RuntimeError("classroom service requires an explicit real provider")
    protocol = json.loads((args.root / "protocol.json").read_text())
    if protocol["implementation_digest"] != implementation_digest():
        raise RuntimeError("frozen implementation changed; prepare a new version before inference")
    environment = {"provider": provider_identity(provider),
                   "software_commit_at_start": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                   "frozen_execution_commit": protocol["code_commit"],
                   "implementation_digest": implementation_digest(),
                   "model_display": "千问 3.6 35B-A3B"}
    (args.root / "environment.json").write_text(json.dumps(environment, indent=2, ensure_ascii=False))
    app = create_app(args.root / "runs.sqlite3", provider=provider, max_workers=6)
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
