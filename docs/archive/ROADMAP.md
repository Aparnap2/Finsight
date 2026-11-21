# FinSight — Roadmap

> Development roadmap for the evidence-backed FP&A Intelligence System.

---

## Legend

| Marker | Meaning |
|--------|---------|
| ✅ | Done |
| 🔄 | In Progress |
| 📋 | Planned |
| ❌ | Never (explicitly out of scope) |

---

## Current — v0.1.0 (Deterministic Core)

### Formula Engine ✅

| Item | Status | Notes |
|------|--------|-------|
| `Formula` class (name, description, category, inputs, output_name, fn) | ✅ | Declarative formula definition |
| `FormulaRegistry` (register, get, list_by_category, names) | ✅ | Registry pattern with uniqueness enforcement |
| `evaluate(name, inputs)` — single formula evaluation | ✅ | Keyword-arg dispatch with missing-input detection |
| `evaluate_all(inputs)` — topological evaluation (Kahn's algorithm) | ✅ | Circular dependency detection |
| `DependencyResolver` | ✅ | Dependency graph construction |
| `FormulaEvaluator`, `EvaluationContext`, `EvaluationError` | ✅ | Execution engine |
| KPI formulas: gross_margin, operating_margin, ebitda_margin, net_margin, revenue_growth, burn_rate, operating_leverage | ✅ | 7 built-in formulas |
| Property-based tests for formula evaluation | ✅ | 449-line test suite |

### Materiality Engine ✅

| Item | Status | Notes |
|------|--------|-------|
| `SensitivityTier` enum (CRITICAL, HIGH, MEDIUM, LOW) | ✅ | Tier-based materiality classification |
| `MaterialityRule` (pct_threshold, abs_threshold, tier, combined_rule) | ✅ | Supports "any" and "both" combination logic |
| Account matching via exact code and glob patterns | ✅ | e.g. `4*` for all revenue accounts |
| `MaterialityConfig` with default threshold values | ✅ | CRITICAL: 3%/50K, HIGH: 5%/100K, MEDIUM: 10%/250K, LOW: 15%/500K |
| `MaterialityEngine.assess(variance)` → `MaterialityResult` | ✅ | Returns is_material, triggered_by, rule used |
| `TenantMaterialityConfig` for per-tenant overrides | ✅ | Multi-tenant ready |
| Default account-to-tier mappings | ✅ | Revenue → CRITICAL, COGS → HIGH, OPEX → MEDIUM |
| 523-line test suite | ✅ | Tests for all tiers, edge cases, custom configs |

### Calendar Engine ✅

| Item | Status | Notes |
|------|--------|-------|
| `FiscalPeriod` model (id, tenant_id, fiscal_year, fiscal_period, period_type, start_date, end_date, status) | ✅ | Pydantic model |
| `PeriodStatus` enum (OPEN, CLOSING, VALIDATING, ANALYZING, REVIEWING, COMPLETED, LOCKED) | ✅ | Period lifecycle states |
| `PeriodType` enum (MONTHLY, QUARTERLY, YEARLY) | ✅ | Three fiscal period types |
| `FiscalCalendar.generate_periods(year, type)` | ✅ | Configurable fiscal year start month |
| `FiscalCalendar.get_period(id)`, `get_period_for_date(date)` | ✅ | Period lookup by ID or date |
| `FiscalCalendar.get_prior_period(id)`, `get_periods_for_year(year)` | ✅ | Period navigation |
| `FiscalCalendar.get_range(start_id, end_id)` | ✅ | Range queries |
| Prior-period and prior-year-period linking | ✅ | Automatic cross-year references |
| `PeriodValidator`, `PeriodProgression` | ✅ | Lifecycle management |
| 349-line test suite | ✅ | Comprehensive period model tests |

### Decimal Money Layer ✅

| Item | Status | Notes |
|------|--------|-------|
| `MoneyDecimal` type (Decimal + float rejection) | ✅ | Pydantic `BeforeValidator` |
| `VarianceResponse` — all monetary fields reject float | ✅ | `field_validator` on actual_amount, budget_amount, variance_amount, variance_pct |
| `AssertionResponse` — value field rejects float | ✅ | `field_validator(mode="before")` |
| `ActionCreateRequest` — impact fields reject float | ✅ | Both expected_savings and expected_revenue |
| `DecimalEncoder` — JSON serialization | ✅ | Decimal → string in JSON |
| `serialize_amounts` — helper for dict conversion | ✅ | Recursive Decimal-to-string |
| Route-level float rejection tests | ✅ | 430-line test suite |
| No float used anywhere in finance engine | ✅ | All engine values are `Decimal` |

### Assertion Pipeline ✅

| Item | Status | Notes |
|------|--------|-------|
| `Assertion` model (id, type, text, value, evidence_ids, support_level, confidence, contradictions, source) | ✅ | Typed evidence-backed claim |
| `AssertionType` enum (NUMERIC, COMPARATIVE, CAUSAL, HYPOTHESIS, ACTION) | ✅ | Five assertion kinds |
| `SupportLevel` enum (VERIFIED, PROBABLE, WEAK, INSUFFICIENT) | ✅ | Four support tiers |
| `AssertionPipelineResult` (assertions, rejected, degraded_modes, summary) | ✅ | Pipeline output container |
| `run_assertion_pipeline(variances, tool_results)` | ✅ | Full pipeline execution |
| Per-type validation dispatch | ✅ | validate_numeric_claim, validate_comparative_claim, validate_causal_claim, validate_action_claim |
| Deterministic confidence computation | ✅ | compute_deterministic_confidence |
| Degraded mode detection and propagation | ✅ | 7 degraded mode types |

### Data Quality Engine ✅

| Item | Status | Notes |
|------|--------|-------|
| `ToolResult` standard contract (immutable) | ✅ | 16-field Pydantic model |
| `DataQualityCheck` — per-check result | ✅ | name, passed, severity, detail |
| `DataQualityReport` — aggregate result | ✅ | overall_score, passed, degraded_modes, checks |
| `assess_batch(tool_results)` — run all 6 checks | ✅ | Batch evaluation |
| Coverage check (coverage_pct < 0.5 → LOW_COVERAGE) | ✅ | |
| Freshness check (freshness > 90 days → STALE_SOURCE) | ✅ | |
| Row count check (row_count == 0 → INSUFFICIENT_DATA) | ✅ | |
| Source diversity check (diversity < 2 → single-source warning) | ✅ | |
| Required filters check (filters missing → scoping issue) | ✅ | |
| Quality score check (score < 0.5 → low quality data) | ✅ | |
| `compute_quality_score()` — composite score from coverage, rows, freshness | ✅ | |
| `compute_degraded_mode()` — derive from coverage + row count | ✅ | |

### Bridge Analysis ✅

| Item | Status | Notes |
|------|--------|-------|
| `BridgeType` enum (REVENUE, COST) | ✅ | |
| `BridgeComponent` enum (PRICE, VOLUME, MIX, FX, ONE_TIME, TIMING, SCOPE, RATE) | ✅ | |
| `BridgeDecomposition` dataclass | ✅ | component, amount, percentage, description, confidence |
| `decompose_bridge()` — revenue accounts (price/volume/mix) | ✅ | Deterministic decomposition |
| `decompose_bridge()` — cost accounts (one-time/timing/scope) | ✅ | |
| Bridge reconciliation check | ✅ | Components sum to total variance |

### Policy Engine ✅

| Item | Status | Notes |
|------|--------|-------|
| `AutonomyLevel` enum (FULLY_AUTONOMOUS, ANALYST_IN_THE_LOOP, MANAGER_APPROVAL, CFO_APPROVAL) | ✅ | |
| `PolicyDecision` (autonomy_level, routing_target, reasons, requires_review, blocked_actions, confidence) | ✅ | |
| `evaluate_policy(assertions, degraded_modes)` | ✅ | Confidence + degraded mode + assertion type analysis |
| `evaluate_from_pipeline_result(pipeline_result)` | ✅ | Convenience wrapper |

### Action Framework ✅

| Item | Status | Notes |
|------|--------|-------|
| `ActionDomain` enum (COST, REVENUE, HEADCOUNT, OPERATIONS, COMPLIANCE, STRATEGY) | ✅ | |
| `ActionStatus` enum (PROPOSED, APPROVED, IN_PROGRESS, COMPLETED, BLOCKED, REJECTED) | ✅ | |
| `ActionImpact` (expected_savings, expected_revenue, one_time_cost, confidence) | ✅ | |
| `ActionItem` (id, action, domain, target, description, cited_assertion_ids, owner, status, impact, policy_permitted) | ✅ | |
| 5-gate enforcement (taxonomy, cause, policy, owner, impact) | ✅ | `create_action()` returns errors + warnings |
| 20 approved action/domain pairs | ✅ | reduce cost, increase revenue, review, renegotiate, etc. |
| API endpoints: POST/GET /actions | ✅ | With structured 422 errors |

### Claim Validator ✅

| Item | Status | Notes |
|------|--------|-------|
| `MonetaryClaim` — single dollar figure extraction | ✅ | |
| `CausalClaim` — cause-effect relationship validation | ✅ | |
| `ActionClaim` — action proposal validation | ✅ | |
| `validate_numeric_claim(value, evidence)` | ✅ | |
| `validate_comparative_claim(value, baseline, variance)` | ✅ | |
| `validate_causal_claim(text, evidence)` | ✅ | |
| `validate_action_claim(action, domain, cause)` | ✅ | |
| `validate_commentary_claims(commentary, assertions)` — batch extraction + cross-check | ✅ | |

### Agent Orchestration ✅

| Item | Status | Notes |
|------|--------|-------|
| LangGraph StateGraph with 6 states | ✅ | ingestion → variance → root_cause → commentary → review → complete |
| Conditional routing: material → root_cause, immaterial → skip | ✅ | |
| Critical degraded mode detection and bypass | ✅ | LOW_COVERAGE, STALE_SOURCE, INSUFFICIENT_CAUSAL_EVIDENCE |
| HITL checkpoint routing (approve → complete, reject → remediation) | ✅ | |
| AsyncPostgresSaver checkpointer | ✅ | Production-grade checkpoint persistence |

### API Layer ✅

| Item | Status | Notes |
|------|--------|-------|
| 12 REST endpoints | ✅ | Full coverage of pipeline, commentary, variances, bridge, quality, policy, actions |
| Truth/render separation API | ✅ | Commentary endpoint returns both assertions + rendered text |
| CSV import endpoint | ✅ | Upload actuals + budget data |
| Pipeline sync execution | ✅ | ingest → variance → root cause → commentary in one request |
| HITL review endpoint | ✅ | approve/reject with notes |
| Status and health endpoints | ✅ | |

### Infrastructure ✅

| Item | Status | Notes |
|------|--------|-------|
| Docker Compose (PostgreSQL, Redis, Qdrant, Temporal, Jaeger) | ✅ | 2.8GB total |
| Alembic migrations | ✅ | 2 migration files |
| Seeded dataset (CloudForge Inc., 18 GL accounts, 18 months) | ✅ | 2 material variances |
| pyproject.toml with deps, ruff, mypy, pytest config | ✅ | |
| litellm-config.yaml | ✅ | Multi-provider routing |

---

## Next — v0.2.0 (Domain Models & External Adapters)

### Domain Models & Graph 📋

| Item | Priority | Notes |
|------|----------|-------|
| `Account` domain model (code, name, type, sensitivity_tier, natural_balance) | P1 | Chart of accounts representation |
| `AccountGraph` — hierarchical account relationships | P1 | Parent-child, rollup structure |
| `Department` domain model | P1 | Cost centre / profit centre |
| `Dimension` model (department, product, region, channel) | P2 | Multi-dimensional analysis support |
| Domain relationship traversal and validation | P2 | Ensure account/org structure integrity |

### Sheets / CSV Adapter 📋

| Item | Priority | Notes |
|------|----------|-------|
| Spreadsheet reader with schema inference | P1 | Column type detection, header parsing |
| Period-aware sheet ingestion | P1 | Map columns to fiscal periods |
| Formula detection and extraction | P2 | Parse Excel formulas for deterministic re-evaluation |
| Validation reporting for spreadsheet data | P1 | Coverage, completeness, consistency checks |

### Context Builder 📋

| Item | Priority | Notes |
|------|----------|-------|
| Structured context packaging for LLM queries | P1 | Precis, period context, variance summaries |
| Evidence enrichment with metadata | P1 | Attach data quality scores, freshness, source provenance |
| Section-aware context assembly | P1 | Per-section evidence selection (revenue, cost, cash, risks) |
| Context size management and truncation | P2 | Token budget enforcement |

### Evidence Engine 📋

| Item | Priority | Notes |
|------|----------|-------|
| Automated evidence gathering across all tool surfaces | P1 | GL, headcount, vendor, pipeline, billing, RAG |
| Evidence deduplication and fingerprinting | P1 | `compute_query_fingerprint()` with SHA-256 |
| Evidence freshness scoring | P1 | Recency-weighted evidence prioritisation |
| Multi-source evidence aggregation | P2 | Cross-source evidence combination |

### Prompt Harness 📋

| Item | Priority | Notes |
|------|----------|-------|
| Version-controlled prompt templates | P1 | Git-tracked prompt files |
| Prompt parameter injection | P1 | Context → prompt variable substitution |
| Prompt versioning and changelog | P1 | Track prompt changes across pipeline runs |
| A/B prompt comparison support | P2 | Side-by-side rendering comparison |

### LLM Integration 🔄

| Item | Priority | Notes |
|------|----------|-------|
| LiteLLM multi-provider routing with fallbacks | ✅ | Complete |
| Structured output parsing | ✅ | Pydantic response models |
| Prompt template loading from `shared/prompts/` | 📋 | In progress |
| Response retry with backoff | 📋 | Handle provider failures |
| Token usage tracking and budgeting | 📋 | Per-request and per-pipeline tracking |

### Guardrails 📋

| Item | Priority | Notes |
|------|----------|-------|
| Output validation against assertion contract | P1 | Ensure LLM doesn't exceed allowed operations |
| Prompt injection detection | P1 | Input-level injection scanning |
| Numerical consistency checking | P1 | Cross-verify all generated numbers |
| Topic boundary enforcement | P2 | Prevent LLM from discussing unrelated topics |
| Sensitivity/confidentiality filters | P2 | PII and confidential data detection |

### Validation Harness 📋

| Item | Priority | Notes |
|------|----------|-------|
| Trajectory evaluation for agent tool use | P1 | Tool selection accuracy, parameter correctness |
| Claim validator regression suite | P1 | Versioned test cases for each validation type |
| Confidence calibration monitoring | P1 | Track overconfidence vs underconfidence |
| Agentic hallucination test suite | P1 | Adversarial tests for numerical and causal claims |
| Eval runner for automated regression | P2 | Scheduled evaluation runs |

---

## Future — v0.3.0+

### Board Reporting 📋

| Item | Priority | Notes |
|------|----------|-------|
| PDF management pack generation | P2 | Structured board-ready PDF output |
| HTML report with embedded visualisations | P2 | Web-based report format |
| Distribution list management | P2 | Email-based report distribution |
| Report templates and branding | P3 | Customisable report styling |
| Excel export with formatted worksheets | P3 | Native Excel output |

### Evaluation 📋

| Item | Priority | Notes |
|------|----------|-------|
| Automated regression evaluation suite | P2 | Scheduled eval runs against historical data |
| Human override rate tracking dashboard | P2 | Visual override analytics |
| Claim validator catch-rate monitoring | P2 | Track hallucination detection effectiveness |
| Time-to-close measurement and trending | P2 | Close cycle duration analytics |
| Forecast accuracy MAPE tracking | P2 | Before vs after assumption update comparison |

### Temporal Durable Workflows 📋

| Item | Priority | Notes |
|------|----------|-------|
| PeriodRun workflow wrapped in Temporal | P2 | Crash-resilient close orchestration |
| HITL checkpoint as Temporal signals | P2 | Durable human review waits |
| Activity retry and timeout policies | P2 | Per-activity failure handling |
| Workflow recovery after process crash | P2 | Resume from last checkpoint |
| Temporal integration tests | P2 | Workflow resumption and idempotency |

### Real ERP Connectors 📋

| Item | Priority | Notes |
|------|----------|-------|
| NetSuite connector (SuiteQL) | P2 | Actuals, budget, chart of accounts |
| QuickBooks Online connector | P2 | Profit & loss, balance sheet |
| Salesforce connector | P3 | Pipeline, bookings, attrition |
| Google Sheets connector | P3 | Spreadsheet-based budget input |
| Connector health monitoring | P2 | Sync status, freshness, error tracking |

---

## Never

The following are **explicitly excluded** from the roadmap and will never be implemented:

| Item | Rationale |
|------|-----------|
| **Chatbot / conversational AI** | FinSight is not a chatbot. No open-ended Q&A interface. |
| **Enterprise Resource Planning** | No transaction processing, order management, inventory, procurement, or supply chain functionality. |
| **General Purpose Workflow Engine** | No BPMN, no custom workflow builder, no generic state machine. The only workflow is the period-run pipeline. |
| **Autonomous Finance** | FinSight never writes to systems of record, never posts to GL/ERP, never changes budgets, never approves payments. All actions are gated and policy-bound. |
| **Custom ML Model Training** | No fine-tuned finance models. Uses pre-trained LLMs exclusively. |
| **Full ELT / Data Pipeline** | No Spark, Airflow, or complex data engineering. Connectors are purpose-built and lightweight. |
| **Mobile App** | Web-first only. |
| **Real-time Collaboration** | Sequential review workflow only. No simultaneous editing. |
| **Real-time Trading / Market Data** | Not a trading system. No market data feeds. |
| **Billing / Invoicing** | No customer billing, no invoice generation, no payment processing. |
| **Authentication / Authorisation System** | No SSO, RBAC, or user management. Assumes gateway-level auth. |

---

## Milestone Summary

| Version | Focus | Target Date | Key Deliverables |
|---------|-------|-------------|------------------|
| **v0.1.0** | Deterministic Core | ✅ Complete | Formula Engine, Materiality Engine, Calendar Engine, Decimal Money Layer, Bridge Analysis, Data Quality, Assertion Pipeline, Policy Engine, Action Framework, Claim Validator, Agent Orchestration, API (12 endpoints), Infrastructure (Docker, DB, migrations, seed data), 83+ tests |
| **v0.2.0** | Domain & Intelligence | TBD | Domain models & graph, Sheets adapter, Context builder, Evidence engine, Prompt harness, LLM guardrails, Validation harness |
| **v0.3.0** | Production & Reporting | TBD | Board reporting (PDF/HTML), Evaluation suite, Temporal durable workflows, Real ERP connectors (NetSuite, QuickBooks), Connector health monitoring |

---

## Test Count Target

| Version | Unit | Integration | Agentic | E2E | Total |
|---------|------|-------------|---------|-----|-------|
| v0.1.0 | 42 | 41 | 7 | 0 | 90 |
| v0.2.0 | +20 | +15 | +10 | +5 | +50 |
| v0.3.0 | +15 | +20 | +5 | +10 | +50 |
| **Total** | **77** | **76** | **22** | **15** | **190** |
