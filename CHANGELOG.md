# Changelog

All notable changes to the FinSight FP&A Intelligence System will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0] — 2026-07-28

### Added

#### Formula Engine

- `Formula` class with name, description, category (ratio/aggregation/variance/growth/margin), typed inputs list, and deterministic callable returning `Decimal`
- `FormulaRegistry` with registration (uniqueness enforcement), lookup by name, category filtering, and full name listing
- `FormulaRegistry.evaluate(name, inputs)` — single formula evaluation with missing-input detection
- `FormulaRegistry.evaluate_all(inputs)` — topological evaluation using Kahn's algorithm with circular dependency detection
- `DependencyResolver` — dependency graph construction for formula chains
- `FormulaEvaluator` with `EvaluationContext` and `EvaluationError` — execution engine with context propagation
- 7 built-in KPI formulas: `gross_margin`, `operating_margin`, `ebitda_margin`, `net_margin`, `revenue_growth`, `burn_rate`, `operating_leverage`
- 449-line test suite covering registration, evaluation, dependency resolution, error handling, and edge cases

#### Materiality Engine

- `SensitivityTier` enum: `CRITICAL` (revenue, cash), `HIGH` (COGS, gross margin), `MEDIUM` (operating expenses), `LOW` (non-material)
- `MaterialityRule` with `pct_threshold`, `abs_threshold`, `tier`, `combined_rule` (any/both), and account matching via exact code and glob patterns
- Default thresholds: CRITICAL (3%, $50K), HIGH (5%, $100K), MEDIUM (10%, $250K), LOW (15%, $500K)
- `MaterialityConfig` — default rules with tier defaults
- `MaterialityEngine.assess()` — evaluates variance against matching rules and returns `MaterialityResult` with `is_material`, `triggered_by`, and rule reference
- `TenantMaterialityConfig` — per-tenant rule overrides for multi-tenancy
- Default account-to-tier mapping: `4*` → CRITICAL (revenue), `5*` → HIGH (COGS), `6*` → MEDIUM (OPEX)
- 523-line test suite covering all sensitivity tiers, combined rules, account patterns, and custom configurations

#### Calendar Engine

- `FiscalPeriod` Pydantic model with id, tenant_id, fiscal_year, fiscal_period, period_type, start_date, end_date, status, prior_period_id, prior_year_period_id, audit_trail
- `PeriodStatus` enum: OPEN, CLOSING, VALIDATING, ANALYZING, REVIEWING, COMPLETED, LOCKED
- `PeriodType` enum: MONTHLY, QUARTERLY, YEARLY
- `FiscalCalendar` — period generation with configurable fiscal year start month
- Monthly, quarterly, and yearly period generation with correct date boundaries
- Period lookup by ID (`get_period`), by date (`get_period_for_date`), by year (`get_periods_for_year`), and range (`get_range`)
- Prior-period and prior-year-period automatic linking across all stored periods
- `PeriodValidator` with `PeriodValidationResult` — validation of period structure and lifecycle
- `PeriodProgression` — period lifecycle state machine management
- 349-line test suite covering generation, lookup, navigation, validation, and lifecycle transitions

#### Decimal Money Layer

- `MoneyDecimal` type annotation — Pydantic `BeforeValidator` that rejects `float` and accepts `Decimal`, `int`, or `str`
- Float rejection in `VarianceResponse` — `field_validator` on `actual_amount`, `budget_amount`, `variance_amount`, `variance_pct`
- Float rejection in `AssertionResponse` — `value` field with `mode="before"` validator
- Float rejection in `ActionCreateRequest` — `impact_expected_savings` and `impact_expected_revenue`
- `DecimalEncoder` — custom JSON encoder that serialises `Decimal` to string (no float precision loss)
- `serialize_amounts` — recursive helper to convert all `Decimal` values in dicts/lists to strings
- No `float` used anywhere in the finance engine — all monetary values are `Decimal`
- 430-line test suite covering schema-level, encoder-level, serializer-level, and route-level decimal enforcement

#### Bridge Analysis

- `BridgeType` enum: REVENUE, COST
- `BridgeComponent` enum: PRICE, VOLUME, MIX, FX (revenue); ONE_TIME, TIMING, SCOPE, RATE (cost)
- `BridgeDecomposition` dataclass — component, amount (`Decimal`), percentage (`Decimal`), description, confidence
- `BridgeAnalysis` — account_id, account_name, total_variance, bridge_type, components, reconciles, confidence, degraded_modes
- `decompose_bridge()` for revenue accounts — price/volume/mix decomposition
- `decompose_bridge()` for cost accounts — one-time/timing/scope decomposition
- Deterministic bridge reconciliation check — components sum to total variance

#### Data Quality Engine

- `ToolResult` — immutable 16-field Pydantic model serving as standard evidence contract
- `compute_quality_score()` — composite quality score from coverage, row count, and freshness
- `compute_degraded_mode()` — derive `DegradedMode` from coverage and row count
- `compute_query_fingerprint()` — deterministic MD5 hash for dedup and caching
- 6 deterministic checks: coverage (LOW_COVERAGE), freshness (STALE_SOURCE), row count (INSUFFICIENT_DATA), source diversity (single-source warning), required filters (missing scoping), quality score (low quality)
- `DataQualityCheck` — per-check result with name, passed, severity, detail
- `DataQualityReport` — aggregate result with overall_score, passed, degraded_modes, checks
- `assess_batch(tool_results)` — batch evaluation producing complete report
- Severity levels: critical, warning, info

#### Assertion Pipeline

- `Assertion` Pydantic model — id, type (NUMERIC/COMPARATIVE/CAUSAL/HYPOTHESIS/ACTION), text, value (`Decimal`), evidence_ids, support_level (VERIFIED/PROBABLE/WEAK/INSUFFICIENT), confidence, contradictions, missing_evidence, max_allowed_action, source, metadata
- `AssertionType` enum with 5 assertion kinds
- `SupportLevel` enum with 4 support tiers
- `AssertionPipelineResult` — assertions, rejected, degraded_modes, summary, `has_valid_assertions`, `highest_confidence`
- `run_assertion_pipeline(variances, tool_results)` — full pipeline execution
- Per-type validation: `validate_numeric_claim`, `validate_comparative_claim`, `validate_causal_claim`, `validate_action_claim`
- Deterministic confidence computation via `compute_deterministic_confidence`
- 7 degraded mode types: NONE, PRELIMINARY_ONLY, MISSING_FX, LOW_COVERAGE, STALE_SOURCE, INSUFFICIENT_CAUSAL_EVIDENCE, FACT_VERIFIED_CAUSE_UNVERIFIED, PRECEDENT_ONLY_SUPPORT

#### Policy Engine

- `AutonomyLevel` enum: FULLY_AUTONOMOUS, ANALYST_IN_THE_LOOP, MANAGER_APPROVAL, CFO_APPROVAL
- `PolicyDecision` — autonomy_level, routing_target, reasons, requires_review, blocked_actions, confidence
- `evaluate_policy(assertions, degraded_modes)` — evaluates confidence scores, degraded modes, and assertion types
- `evaluate_from_pipeline_result(pipeline_result)` — convenience wrapper for pipeline response
- Autonomy matrix: confidence ≥ 0.8 with no degraded modes → FULLY_AUTONOMOUS; confidence ≥ 0.6 with minor issues → ANALYST_IN_THE_LOOP; confidence ≥ 0.4 with degraded modes → MANAGER_APPROVAL; confidence < 0.4 → CFO_APPROVAL

#### Action Framework

- `ActionDomain` enum: COST, REVENUE, HEADCOUNT, OPERATIONS, COMPLIANCE, STRATEGY
- `ActionStatus` enum: PROPOSED, APPROVED, IN_PROGRESS, COMPLETED, BLOCKED, REJECTED
- `ActionImpact` — expected_savings, expected_revenue, one_time_cost, payback_period_months, confidence, notes
- `ActionItem` — id, action, domain, target, description, cited_assertion_ids, owner, status, impact, policy_permitted
- 20 approved action/domain pairs (reduce cost, increase revenue, review, renegotiate, invest, divest, restructure, etc.)
- 5-gate enforcement via `create_action()`: (1) approved taxonomy, (2) validated cause cited, (3) policy permission, (4) owner identified, (5) impact quantified or flagged
- `ActionCreationResult` — action_item, created flag, errors list, warnings list
- Structured 422 error responses when gates fail

#### Claim Validator

- `MonetaryClaim` — single dollar figure extraction and cross-verification
- `CausalClaim` — cause-effect relationship validation
- `ActionClaim` — action proposal validation
- `validate_numeric_claim(value, evidence)` — exact match and rounding tolerance (±5%)
- `validate_comparative_claim(value, baseline, variance)` — comparative claim verification
- `validate_causal_claim(text, evidence)` — causal relationship validation
- `validate_action_claim(action, domain, cause)` — action proposal validation
- `validate_commentary_claims(commentary, assertions)` — batch extraction of all monetary claims from commentary text with cross-verification against evidence graph

#### Agent Orchestration

- LangGraph `StateGraph` with 6 pipeline states: ingestion → variance_detection → root_cause → commentary → review → complete
- `_route_after_variance` — conditional routing: material variances → root_cause, immaterial or degraded → commentary
- `_route_after_scenario` — HITL check: review required → review, autonomous → complete
- `_route_after_review` — approve → complete, reject → remediation
- Critical degraded mode detection: LOW_COVERAGE, STALE_SOURCE, INSUFFICIENT_CAUSAL_EVIDENCE trigger root cause bypass
- HITL checkpoint infrastructure with review routing
- AsyncPostgresSaver checkpointer integration for production-grade state persistence

#### Variance Agent

- `compute_variances(actuals, budget)` — actual-vs-budget comparison using `Decimal` arithmetic
- `apply_materiality(variances, threshold)` — absolute + percentage materiality marking
- `variance_node(state)` — LangGraph node that chains computation + materiality application
- 100% deterministic — no LLM calls

#### Commentary Agent

- `CommentaryRenderInput` — structured input with verified_assertions, probable_assertions, weak_assertions, degraded_modes, required_sections, audience, period, entity_name
- Truth/render separation — LLM receives only pre-validated assertions
- Explicit rendering prohibitions: no invented values, no hypothesis-to-fact upgrades, no new claims
- `render_commentary(input, llm_client)` — LLM rendering from assertions
- `generate_commentary(findings, scenarios, llm_client)` — commentary generation entry point
- Section parsing: executive_summary, variance_analysis
- `CommentaryRenderInput.from_assertion_list()` — factory for building render input from assertion pipeline output

#### Root-Cause Agent

- `investigate_root_causes(material_variances, llm_client)` — LLM-guided investigation
- Read-only evidence gathering through standardised tool contracts
- Evidence graph construction with `EvidenceItem` linking to source records
- Alternative hypothesis generation with confidence scores
- Explicit data gap documentation

#### API Layer

- `GET /api/v1/status` — system status with version and available endpoint list
- `GET /api/v1/health` — health check
- `POST /api/v1/pipeline/run` — trigger pipeline with optional sync mode
- `POST /api/v1/pipeline/execute` — full pipeline (ingest → variance → root cause → assertions → commentary → policy) returning both truth and rendered layers
- `GET /api/v1/pipeline/{run_id}/status` — check pipeline run status
- `GET /api/v1/pipeline/{run_id}/results` — get completed pipeline results
- `POST /api/v1/pipeline/{run_id}/review` — human-in-the-loop review (approve/reject)
- `GET /api/v1/commentary/{period}` — commentary + assertions with truth/render separation
- `GET /api/v1/variances/{period}` — computed variances for a period
- `GET /api/v1/bridge/{period}/{account_id}` — bridge variance decomposition
- `GET /api/v1/data-quality/{period}` — data quality assessment
- `GET /api/v1/policy/{period}` — policy/autonomy decision
- `GET /api/v1/actions` — list all action items
- `POST /api/v1/actions` — create action item with gate enforcement (422 on failure)
- `GET /api/v1/actions/{action_id}` — get specific action item
- `POST /api/v1/import/csv` — CSV data import (actuals + budget)
- All response schemas use `MoneyDecimal` for monetary fields
- All responses include degraded_modes where applicable

#### Infrastructure

- Docker Compose with 6 services: PostgreSQL, Redis (port 6380), Qdrant, Temporal, Jaeger, FastAPI backend
- Memory-limited containers: total 2.8GB
- Alembic migrations (2 migration files: initial schema + PRD domain tables)
- 15 database tables via SQLAlchemy ORM
- Seeded CloudForge Inc. dataset: 18 GL accounts, 18 months, 2 material variances (Revenue Product Y: -12%, Cloud Infrastructure: +35%)
- `pyproject.toml` with all dependencies, ruff linting config, mypy strict mode, pytest-asyncio config
- `litellm-config.yaml` for multi-provider LLM routing
- `.env.example` with all required environment variables
- `Dockerfile.backend` for containerised deployment

#### Shared Models

- `PipelineState` (TypedDict) — full pipeline state shape with period, tenant_id, actuals, budget, variances, root_causes, commentary_draft, scenarios, review_decisions, error, current_step
- `Variance` — account_id, account_name, department, actual_amount, budget_amount, variance_amount, variance_pct (all `Decimal`), is_material
- `EvidenceItem` — source_table, record_id, field, value (`Decimal`), period, description
- `RootCauseFinding` — variance_id, summary, assertions, evidence, confidence_score, recommended_action, alternative_hypotheses, data_gaps
- `CommentarySection` — section_type, content, cited_data_points
- `ActionItem` (state model) — description, assigned_to, due_by, priority
- `CommentaryDraft` — sections, actions, assertions_used, generated_at, version, status, approval_state
- `Scenario` — name, description, assumptions, revenue/ebitda/cash impact (`Decimal`), probability_assessment
- `DegradedMode` enum: 7 values (NONE, PRELIMINARY_ONLY, MISSING_FX, LOW_COVERAGE, STALE_SOURCE, INSUFFICIENT_CAUSAL_EVIDENCE, FACT_VERIFIED_CAUSE_UNVERIFIED, PRECEDENT_ONLY_SUPPORT)

#### Shared Utilities

- `LLMClient` — LiteLLM client abstraction for multi-provider calls
- `PolicyEngine` — full autonomy policy matrix with confidence-based routing
- `DecimalEncoder` — JSON serialization for Decimal types
- `ToolResult` — immutable 16-field standard evidence contract
- `compute_quality_score()` — composite data quality scoring
- `compute_degraded_mode()` — degraded mode derivation
- `compute_query_fingerprint()` — MD5 query fingerprint for dedup
- `GLTools`, `HeadcountTools`, `VendorTools`, `PipelineTools`, `RagTools` — evidence-gathering tool implementations
- `ClaimValidator` — monetary claim extraction, causal claim validation, action claim validation, commentary batch cross-check

#### Tests

- **37 test files** across unit, integration, and agentic layers
- Unit tests for formula engine (449 lines), calendar (349 lines), materiality (523 lines), decimal layer (430 lines)
- Integration tests for API routes, schemas, agents (orchestrator, variance, root-cause, commentary, ingestion, scenario), engine (assertion pipeline, confidence, bridge, policy, data quality), models (state, assertions, database, evidence, action, tenant isolation), validators (claim validator), tools, and seed data
- Agentic tests for hallucination resistance, decision making, type safety, tool calls, formatting, RAG, and master workflow
- All tests pass with `pytest tests/ -v`
