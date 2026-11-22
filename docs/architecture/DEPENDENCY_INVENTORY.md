# FinSight Dependency and Configuration Inventory

**Version:** 1.0 (Task D deliverable)
**Status:** Read-only investigation
**Date:** 2026-11-22

---

## 1. Runtime Dependencies (pyproject.toml)

| Dependency | Version | Used by | Status |
|---|---|---|---|
| fastapi | >=0.115 | apps/api | KEEP |
| sqlalchemy | >=2.0 | shared/models, middleware | KEEP |
| alembic | >=1.13 | migrations | KEEP |
| pydantic | >=2.0 | shared/llm, finance/reconciliation, apps/api/schemas | KEEP |
| polars | >=1.0 | finance/feature_store, finance/analytics | CONSOLIDATE (slice 8) |
| duckdb | >=1.0 | finance/analytics | CONSOLIDATE (slice 8) |
| pandera | >=0.20 | (data validation) | KEEP (DataOps) |
| pyarrow | >=15.0 | finance/analytics | CONSOLIDATE (slice 8) |
| openai | >=1.0 | shared/llm/openai_compatible | KEEP (LLM) |
| httpx | >=0.27 | (async HTTP) | KEEP |
| nicegui | >=2.0 | apps/api/operator_console | KEEP |
| python-multipart | >=0.0.9 | apps/api (file upload) | KEEP |
| psycopg | >=3.1 | (PostgreSQL driver) | KEEP |
| boto3 | >=1.34 | shared/aws (test-only), finance/object_store | DEFER |
| uvicorn | >=0.30 | (ASGI server) | KEEP |
| ruff | >=0.5 | (linting) | KEEP (dev) |
| mypy | >=1.10 | (type checking) | KEEP (dev) |
| pytest | >=8.0 | (testing) | KEEP (dev) |
| hypothesis | >=6.100 | (not yet used) | ADD (testing standard) |

## 2. Environment Variables

| Variable | Used by | Status | Notes |
|---|---|---|---|
| `POSTGRES_URI` | shared/config, middleware | KEEP | Runtime DB contract (sole) |
| `DATABASE_URL` | Nothing | REMOVE | Dead config; read by nothing |
| `POOLSIDE_API_KEY` | shared/llm/config | KEEP | LLM provider |
| `POOLSIDE_BASE_URL` | shared/llm/config | KEEP | LLM provider |
| `POOLSIDE_CHAT_MODEL` | shared/llm/config | KEEP | LLM provider |
| `GROQ_API_KEY` | shared/llm/config | KEEP | LLM provider |
| `GROQ_BASE_URL` | shared/llm/config | KEEP | LLM provider |
| `GROQ_CHAT_MODEL` | shared/llm/config | KEEP | LLM provider |
| `OPENROUTER_API_KEY` | shared/llm/config | KEEP | LLM provider |
| `OPENROUTER_BASE_URL` | shared/llm/config | KEEP | LLM provider |
| `OPENROUTER_CHAT_MODEL` | shared/llm/config | KEEP | LLM provider |
| `OPENAI_API_KEY` | shared/llm/config | KEEP | LLM provider |
| `OPENAI_BASE_URL` | shared/llm/config | KEEP | LLM provider |
| `OPENAI_CHAT_MODEL` | shared/llm/config | KEEP | LLM provider |
| `LLM_PROVIDER` | shared/llm/config | KEEP | LLM provider selection |
| `LLM_API_KEY` | shared/llm/config | KEEP | LLM key override |
| `LLM_BASE_URL` | shared/llm/config | KEEP | LLM URL override |
| `LLM_CHAT_MODEL` | shared/llm/config | KEEP | LLM model override |
| `LLM_TIMEOUT_S` | shared/llm/config | KEEP | LLM timeout |
| `LLM_MAX_RETRIES` | shared/llm/config | KEEP | LLM retries |
| `AWS_ENDPOINT_URL` | shared/aws/config (test-only) | DEFER | MiniStack only |
| `AWS_REGION` | shared/aws/config (test-only) | DEFER | MiniStack only |
| `AWS_ACCESS_KEY_ID` | shared/aws/config (test-only) | DEFER | MiniStack only |
| `AWS_SECRET_ACCESS_KEY` | shared/aws/config (test-only) | DEFER | MiniStack only |
| `OPERATOR_CONSOLE_DEMO_TENANT_ID` | apps/api/operator_console | KEEP (demo) | Demo-only |
| `OPERATOR_CONSOLE_DEMO_ROLE` | apps/api/operator_console | KEEP (demo) | Demo-only |
| `OPERATOR_CONSOLE_DEMO_USER_ID` | apps/api/operator_console | KEEP (demo) | Demo-only |
| `STRIPE_WEBHOOK_SECRET` | apps/api/webhooks | KEEP | Stripe webhook verification |
| `STRIPE_TENANT_MAP` | apps/api/webhooks | KEEP | Tenant mapping |
| `APP_ENV` | shared/config | KEEP | Environment |
| `LOG_LEVEL` | shared/config | KEEP | Logging |

## 3. CI Workflows

| Workflow | File | Purpose | Jobs | Status |
|---|---|---|---|---|
| Quality | `.github/workflows/ci.yml` | Lint, typecheck, unit/contract, contract report | unit | KEEP |
| Integration | `.github/workflows/integration.yml` | PostgreSQL-gated, ministack S3 | integration, ministack | KEEP |
| AI Evals | `.github/workflows/ai-evals.yml` | Golden-dataset eval gate, manual LLM eval | golden-dataset, llm-evals | KEEP (but finance/evaluation/ is FP&A) |
| Verification | `.github/workflows/verification.yml` | PR verification, scope/risk classification | risk-classification, gate-evidence, exception-review | KEEP |
| Deploy Prod | `.github/workflows/deploy-prod.yml` | Production deployment | deploy | KEEP (local Docker Compose) |
| Deploy Staging | `.github/workflows/deploy-staging.yml` | Staging deployment | staging | KEEP |
| Rollback | `.github/workflows/rollback.yml` | Rollback procedure | rollback | KEEP |

## 4. Docker/Compose Services

| Service | Used by reconciliation product? | Status |
|---|---|---|
| postgres (dev) | Yes (PostgreSQL) | KEEP |
| redis | No (not used by reconciliation) | REMOVE (P3) |
| qdrant | No | REMOVE (P3) |
| redpanda | No | REMOVE (P3) |
| temporal | No | REMOVE (P3) |
| temporal-ui | No | REMOVE (P3) |
| jaeger | Observability (optional) | DEFER |
| litellm | LLM proxy (optional) | DEFER |
| compute-runtime | Yes (python_runtime.dispatcher) | KEEP |
| pgdata | Yes (PostgreSQL volume) | KEEP |

## 5. Runtime Entry Points

| Entry Point | File | Role | Status |
|---|---|---|---|
| FastAPI app | `apps/api/main.py` | HTTP API + NiceGUI | KEEP (add reconciliation routes) |
| Operator CLI | `finance/reconciliation/operator_report.py` | Reconciliation demo | KEEP |
| SQS worker | `apps/workers/sqs_execute.py` | Background execution | DEFER (not needed for sync reconciliation) |
| Compute runtime | `python_runtime/dispatcher.py` | Analytics job dispatcher | KEEP (used by routes.py) |

## 6. Alembic Migrations

| Migration | Purpose | Status |
|---|---|---|
| 000_init.sql | Initial schema | KEEP |
| 001_extensions.sql | PostgreSQL extensions | KEEP |
| 002_not_null.sql | NOT NULL constraints | KEEP |
| 003_check_constraints.sql | CHECK constraints | KEEP |
| 004_indexes.sql | Indexes | KEEP |
| 005_unique_constraints.sql | Unique constraints | KEEP |
| c9d5e7f1a204 | p8 durability tables (p8_run_states, p8_run_audit) | DEFER (slice 4b) |
| a3f6c1e8b2d4 | Tenant-scoped execution keys | KEEP |
| b7e2d9f4a516 (head) | Webhook outbox dispatch table | KEEP |

**Next migration needed:** Reconciliation tables (12 tables per DATABASE_SCHEMA.md).