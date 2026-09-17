# Project Context — Meridian Commerce (Single-Company FinSight)

## Purpose
FinSight is an **internal agentic financial operations system for Meridian Commerce Pvt Ltd** (B2B commerce, ~1500 merchants, 20k Razorpay payments/day, 100–150Cr GMV). It detects, investigates, explains, proposes, executes under authorization, and verifies financial discrepancy resolution across payment (Razorpay), accounting (QuickBooks), operational (Google Sheets expected, Gmail context, Slack approval), and isolated legacy COBOL settlement ledger (fixed-width batch, no HTTP via S3). Existing systems own facts; FinSight owns reasoning state (FinancialSituation FS-2026-0916-00231, Investigation, Evidence, Hypothesis, ResolutionProposal, PolicyDecision, Approval, Execution, Verification, Audit).

## Tech Stack
- Python 3.12, FastAPI, SQLAlchemy, Alembic, Postgres+RDS, SQS/S3 via MiniStack/LocalStack (S3 `localstack:3.8 SERVICES=s3` as artifact/legacy transport), Pydantic v2, Decimal MoneyDecimal, `shared/tracing` TracerProtocol (NoOp/Phoenix/Langfuse optional via OTel), `shared/llm` LLMProvider thin SDKs (Groq/Fake/Replay, 3-call budget), `agents/investigation` (InvestigationRequest tenant→company_id=meridian + actor, InvestigationContext fenced UNTRUSTED_CONTENT, Planner 5 acts), `agents/verification` 6 stages, `agents/capabilities` frozen 5 + S3 tenant prefix, `finance/reconciliation` pure, `finance/exceptions` CAS, `finance/object_store` FakeS3+S3Adapter.

## Project Conventions

### Code Style
- Python 3.12, ruff (100 cols), mypy --strict, Decimal for money, typed/frozen Pydantic, `shared←finance←agents←apps` imports, `pytest -m "not live_llm"` default, `pytest -m ministack` gated, `openspec validate --strict`.

### Architecture Patterns
- 11-stage cognitive loop Detect→Triage→Investigate→Correlate→Explain→Propose→Policy→Auto/HITL→Execute→Verify→Close; deterministic code owns financial calc/policy/state/execution/verification, LLM handles semantic investigation/hypothesis over bounded evidence. `TracerProtocol` owns observability contract, vendors replaceable behind it.

### Testing Strategy
- ADR 11-stage: `pytest -m "not live_llm"` baseline, `pytest -m ministack` S3 contract (Fake + LocalStack, skipped when down not pass), `pytest -m live_llm` gated `FINSIGHT_ALLOW_LIVE_LLM`, golden datasets `happy/timing/fee/duplicate/legacy rejection/ambiguous/conflicting/prompt injection/cross-tenant/malformed/partial/timeout/UNKNOWN`, 6 dimensions grounding/investigation/security/control/financial/reliability, property `gross-fees-refunds-adjustments=net` + `hypothesis` fuzzing.

### Git Workflow
- `feat/finsight-*` from `finsight-p4-complete`/`finsight-p4-ministack-s3`/`finsight-p5-02-context` tags, `openspec validate --strict` before merge, atomic `feat/fix/docs` commits, `TenantIsolationError` alias → `CompanyIsolationError`.

## Domain Context
- **Company:** Meridian Commerce Pvt Ltd (`company_id=meridian`, `environment` dev/staging/prod, base_currency INR, tolerance_minor 100, auto_approval 500000, legacy correction approval true, single ISIN/company, not multi-tenant SaaS).
- **MeridianBusinessRules:** refund <5k auto if evidence complete, 5k–50k Manager, >50k Director; legacy correction always human approval+valid account code+balanced batch; closed period never modify. **RBAC is internal Meridian authorization** (Analyst READ+INVESTIGATE+PROPOSE, Payment Ops same, Manager APPROVE ≤50k, Director >50k, Auditor READ only, Agent READ_SCOPED+INVESTIGATE+CREATE_PROPOSAL, DENIED APPROVE/EXECUTE/MODIFY_POLICY/RBAC/SCOPE) — `Authenticated Actor → RBAC → Case Scope → Business Policy → Approval → Execution`. RBAC ≠ policy.
- **FinancialSituation** central object (e.g., FS-231 expected 10,00,000 vs Razorpay 9,72,500 (fee 7,500+refund 2,500+adj 10,000) vs QB 9,82,500 vs legacy 9,82,500 variance 10k → legacy batch LEGACY-20260916-0042 500 rec rejected INVALID_ACCOUNT_CODE 4812 → ResolutionProposal reprocess 10k Medium HITL → Slack Approve → CORRECTION_20260916_231.DAT via S3 → COBOL ACCEPTED → 9,92,500 CLOSED).
- **Authority:** Razorpay provider state, QuickBooks accounting, COBOL legacy, Sheets expected, Gmail context, Slack approval — FinSight owns reasoning state only.

## Important Constraints
- **Tenant isolation reinterpreted as company/environment isolation** (`app.company_id`, S3 `{company_id}/{case_id}/...`, `CompanyIsolationError` alias, RLS). LLM never chooses tenant/authority/approval/policy/scope. S3 is transport/artifact only. No SQS/SNS/EventBridge until queue gate. No financial truth moved to LLM.

## External Dependencies
- Razorpay, QuickBooks (mocked), Google Sheets, Gmail (search), Slack (approval), COBOL ledger via S3 (`finsight-legacy-outbound/result-test`), Postgres, MiniStack/LocalStack S3, Groq LLM, OTel/Phoenix (optional).
