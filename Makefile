.PHONY: install install-all test test-cov lint format typecheck check validate run build clean

install:
	uv sync --group dev

install-all:
	uv sync --group dev --all-extras

test:
	uv run pytest

test-cov:
	uv run pytest --cov=agentanvil --cov-report=term-missing

lint:
	uv run ruff check src/ tests/

format:
	uv run ruff format src/ tests/

typecheck:
	uv run mypy src/

check: lint typecheck test

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
