.PHONY: install test smoke stress example serve
install:
	python -m pip install -e '.[dev]'
test:
	python scripts/run_checks.py
smoke:
	python scripts/http_smoke.py
stress:
	python scripts/stress_offline.py
example:
	python -m oncofusion examples --out data/synthetic
	python -m oncofusion demo --out results/demo.json
serve:
	python -m oncofusion serve --host 127.0.0.1 --port 8000
