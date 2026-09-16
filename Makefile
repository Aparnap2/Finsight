# FinSight local CI entrypoints.
# Fast unit path mirrors .github/workflows/ci.yml; the gated integration path
# mirrors .github/workflows/integration.yml via docker-compose.test.yml.
# MiniStack S3 contract is per docs/architecture/MINISTACK_SEAM_AUDIT.md:
# single justified seam (S3), test-only, never in fast CI.

.PHONY: test test-integration evals ci-local ministack-up ministack-init ministack-test ministack-down

# $(wildcard ...) keeps local runs green before a suite directory exists;
# CI workflows reference the literal directories and fail fast instead.
UNIT_DIRS := $(wildcard tests/unit tests/contract)
INT_DIRS := $(wildcard tests/integration tests/failure tests/e2e)

test:
	uv run pytest $(UNIT_DIRS) -q

test-integration:
	@if command -v docker >/dev/null 2>&1 && docker compose -f docker-compose.test.yml config >/dev/null 2>&1; then \
		docker compose -f docker-compose.test.yml up --abort-on-container-exit --exit-code-from test; \
	else \
		uv run pytest $(INT_DIRS) -q -rs; \
	fi

evals:
	@echo "LLM evals are manual-only (Actions workflow_dispatch: ai-evals). No provider calls from this target."
	@echo "See evals/llm/README for the controlled eval procedure."

ci-local:
	@if command -v act >/dev/null 2>&1; then \
		act -j unit; \
	else \
		uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest $(UNIT_DIRS) -q; \
	fi

ministack-up:
	docker compose -f docker-compose.ministack.yml up -d --wait

ministack-init:
	uv run python scripts/ministack_init.py

ministack-test:
	uv run pytest -m ministack -q -rs

ministack-down:
	docker compose -f docker-compose.ministack.yml down -v

test-ministack: ministack-up ministack-init ministack-test ministack-down
