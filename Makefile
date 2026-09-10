.PHONY: install test doctor probe-all probe-2 summary build-mcp package-release clean lint

# Prefer python3 when `python` is absent (common on minimal Linux images).
PYTHON ?= $(shell command -v python3 >/dev/null 2>&1 && echo python3 || echo python)
PYTHONPATH := packages/core:packages/cli
export PYTHONPATH

install:
	$(PYTHON) -m pip install -e packages/core
	$(PYTHON) -m pip install -e packages/cli

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

# Build a user-installable offline release tarball under release/.
package-release:
	bash scripts/package_release.sh

clean:
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type d -name "*.egg-info" -prune -exec rm -rf {} +
	rm -rf packages/mcp/dist packages/mcp/node_modules packages/mcp/*.tgz
	rm -rf packages/core/dist packages/cli/dist release/

lint:
	ruff check packages/ reports/probes/ || true
