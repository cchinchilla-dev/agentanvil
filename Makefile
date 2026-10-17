.PHONY: install install-all test test-cov determinism lint format format-check typecheck version check validate run build clean

install:
	uv sync --group dev
	uv run pre-commit install

install-all:
	uv sync --group dev --all-extras
	uv run pre-commit install

test:
	uv run pytest

test-cov:
	uv run pytest --cov=agentanvil --cov-report=term-missing

determinism:
	uv run pytest tests/ci/test_determinism.py -m slow -q

lint:
	uv run ruff check src/ tests/

format:
	uv run ruff format src/ tests/

format-check:
	uv run ruff format --check src/ tests/

typecheck:
	uv run mypy src/

version:
	uv run python scripts/check_version_linearity.py

# Same gates as CI; coverage below fail_under (85%) fails test-cov
check: lint format-check typecheck test-cov determinism version

# CLI shortcuts
validate:
	@test -n "$(CONTRACT)" || (echo "Usage: make validate CONTRACT=contract.yaml" && exit 1)
	uv run agentanvil validate $(CONTRACT)

run:
	@test -n "$(AGENT)" || (echo "Usage: make run AGENT=path/to/agent CONTRACT=contract.yaml" && exit 1)
	uv run agentanvil run $(AGENT) --contract $(CONTRACT)

build:
	uv build --wheel

clean:
	rm -rf dist/ build/ *.egg-info .pytest_cache .mypy_cache .ruff_cache htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
