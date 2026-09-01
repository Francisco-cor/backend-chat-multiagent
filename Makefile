.PHONY: install lint format typecheck test cov pre-commit clean

install:
	pip install -r requirements.txt
	pip install ruff black mypy pre-commit pytest pytest-asyncio httpx aiosqlite anyio coverage pytest-cov

lint:
	ruff check app tests

format:
	ruff check --fix app tests
	ruff format app tests
	black app tests

typecheck:
	mypy app

test:
	pytest

cov:
	pytest --cov=app --cov-report=term-missing

pre-commit:
	pre-commit run --all-files

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
