"""Run offline checks and retain machine-readable evidence. No network or API key required."""
import importlib.metadata
import json
import platform
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = root / "results" / "checks"
out.mkdir(parents=True, exist_ok=True)
commands = [
    [sys.executable, "-m", "compileall", "-q", "oncofusion", "tests"],
    [sys.executable, "-m", "pytest", "-q", "--cov=oncofusion", "--cov-branch",
     "--cov-report=term-missing", f"--cov-report=json:{out / 'coverage.json'}",
     f"--junitxml={out / 'pytest.xml'}"],
]
records = []
for command in commands:
    result = subprocess.run(command, cwd=root, text=True, capture_output=True)
    print(result.stdout)
    print(result.stderr, file=sys.stderr)
    records.append({"command": command, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
report = {"python": platform.python_version(), "platform": platform.platform(),
          "dependencies": {name: importlib.metadata.version(name) for name in ("fastapi", "pydantic", "httpx", "pytest", "pytest-cov", "uvicorn", "python-multipart")},
          "checks": records}
(out / "checks.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
raise SystemExit(0 if all(r["returncode"] == 0 for r in records) else 1)
