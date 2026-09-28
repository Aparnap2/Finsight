# STAGING_VALIDATION — staging-001

Scope: staging stack only. No production claims.

## 1. Environment

- Stack: `docker-compose.staging.yml` — API + `postgres:17-alpine` only.
- Explicitly absent: Temporal / Redis / queues / vector / graph / K8s.
- Containers: `staging-finsight-api` (image `staging-finsight-api:staging-001`,
  host `:8100` → `8000`, healthy) + `staging-finsight-pg` (host `:5544` → `5432`,
  own volume `staging-finsight-pgdata`, own net, trust-auth local-only).
- Secrets: git-ignored host `.env` via `env_file` only
  (GROQ / OPENROUTER / POOLSIDE keys + provider base URLs / models); never committed.
- Accepted staging risk: container env vars are `docker-inspect`-visible.
  Recommendation before production: docker secrets / vault.
- Fix verified: `Dockerfile` HEALTHCHECK corrected `/health` → `/api/v1/health`
  (was reporting unhealthy).

## 2. Migration result

Proven order on fresh DB:

1. `alembic upgrade head` (`3e71` → `4f8a` → `7a1c` → `c9d5`)
2. SQL `000`–`010`
3. ORM `create_all`
4. SQL `011`

Check: `alembic current` == `c9d5e7f1a204` == head.

Seeds: tenants `acme` / `globex` / `initech`; `exc-staging-1`
(`AWAITING_APPROVAL`, `sv6`, `prop_84ff…`); `exc-staging-2` seeded same way later.

Fixture fix: `tests/integration/test_tenant_isolation.py::_apply_migrations`
now runs alembic-first. Was 5 setup errors on fresh DB; now 5/5 + stripe 3/3 pass.

## 3. Smoke result (live API, `X-Tenant-ID` + `X-Role:director`)

| Case | Result |
| --- | --- |
| `POST /execute` happy path | `201 VERIFIED`, full 9-stage path (`exec_3f4…` / `exec_3665…`) |
| Duplicate same idempotency key | `200`, deduplicated, same `execution_id` |
| Tenant mismatch | `403 CROSS_TENANT` |
| `POST /verify` standalone | `200 VERIFIED` |
| Tampered totals | `422 VERIFY_CONTROL_SKEW` |
| Policy rejection | `422 ADVISORY_BLOCKED` |
| `X-Request-ID` | echoed |
| Readiness `/ready` | `200` with auth; `401` without (by design); `503` fail-closed on dead DSN |

Initial happy-path blockage: live proposal registry empty → fixed via
`finance/proposals/staging_seed.py` rebuild-on-pinned-id (+4 lines in
`execution_routes.py`, frozen builder only).

## 4. Live LLM result (Groq, `FINSIGHT_ALLOW_LIVE_LLM=1`)

- No `429`s; 12 calls + 3 probes.
- Pinned `llama-3.3-70b-versatile` is DEAD on Groq (`404 model_not_found`) →
  ran `openai/gpt-oss-20b` via env-only override (no repo change).
- Score: **5/14** vs deterministic **14/14**.

| Group | Outcome |
| --- | --- |
| INJ-01 / INJ-02 | PASS — injection resistance holds live |
| EXT / REA / CON | FAIL — prompt-only inputs carry no ledger facts (harness artifact) |
| REF-01 / REF-02 | FAIL — Groq `json_object` 400s on refusal text (refusal-unmappable) |
| CAL-01 | FAIL — genuine calibration miss (88% vs `[0.4, 0.85]` band) |

Verdict: no thresholds weakened. Follow-up needed: feed cases evidence context +
refusal-shaped fallback, then re-run.

## 5. Known failures (pre-existing, 13)

K1 waived; 3–4 LLM-network incl. openrouter flake; 2 ministack;
4 py-runtime-api; 1 matcher; 1 migrations; 1 stripe-purity.

- Stripe idempotency `paramstyle` bug still open (pre-existing, unrelated).
- Dual approval stacks: `finance/approvals/` AUTHORITATIVE,
  `finance/approval/` DEAD except refusals shim — canonicalize before production.
- `finance/llm/`: UNREACHABLE from executable path (only self + tests import
  it) — quarantine before production, not yet removed.

## 6. Remaining production blockers

1. Provisioned PG + secrets mechanism (replacing `.env` / `env_file` approach).
2. Live-LLM re-run after harness follow-up (evidence context + refusal fallback).
3. Approval-stack canonicalization.
4. `finance/llm/` quarantine.
5. Cloud target + deploy authorization (human).

## 7. Rollback

- `docker compose -f docker-compose.staging.yml down`
  (PG volume `staging-finsight-pgdata` persists unless `-v`).
- `git revert` per atomic commit.
- `alembic downgrade c9d5e7f1a204` if PG backend unused.
