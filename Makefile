.PHONY: install test doctor probe-all probe-2 summary build-mcp clean lint

PYTHON ?= python
PYTHONPATH := packages/core:packages/cli
export PYTHONPATH

install:
	pip install -e packages/core
	pip install -e packages/cli

test:
	$(PYTHON) -m pytest packages/core/tests/ -v

doctor:
	dsh doctor || $(PYTHON) -m deepseek_harness_cli doctor

probe-2:
	$(PYTHON) reports/probes/probe_2_reasoning_lifecycle.py --n 3

probe-all:
	bash reports/probes/probe_11_v4flash_sweep.sh

summary:
	$(PYTHON) -m deepseek_harness.summarize reports/raw reports/summary

build-mcp:
	cd packages/mcp && npm install && npm run build

clean:
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type d -name "*.egg-info" -prune -exec rm -rf {} +
	rm -rf packages/mcp/dist packages/mcp/node_modules

lint:
	ruff check packages/ reports/probes/ || true
