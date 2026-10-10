PY ?= python
export PYTHONHASHSEED = 0

.PHONY: install lint format typecheck test check config-check
install:
	$(PY) -m pip install -r requirements/dev.txt && $(PY) -m pip install -e . --no-deps
lint:
	ruff check . && ruff format --check .
format:
	ruff check --fix . && ruff format .
typecheck:
	mypy
test:
	pytest
check: lint typecheck test
config-check:
	$(PY) -m app.cli check-config --config configs/dev_cpu.yaml
