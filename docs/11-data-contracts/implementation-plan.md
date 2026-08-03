# Implementation Plan — 6 Phase Rollout

> **Audience:** Engineering managers, platform team, QA
> **Status:** Design proposal for Phase 2
> **Total estimated effort:** 8-10 weeks for 2 engineers

---

## Phase 1: Foundation — Domain Model Enrichment (Weeks 1-2)

**Theme:** Make the existing domain models correct by construction.

### Goals
1. Add `@model_validator` invariants to Variance, BudgetLine, RootCauseFinding
2. Replace `str` status fields with `StrEnum` across all domain models
3. Add `created_at`, `updated_at`, `version` metadata to domain models that lack it
4. Add `MoneyDecimal` to any remaining `float` monetary fields

### Tasks

| # | Task | Files Affected | Effort |
|---|------|---------------|--------|
| 1.1 | Add `Variance.validate_variance_math()` invariant | `finance/domain/variance.py` | 0.5d |
| 1.2 | Add `Variance.validate_direction()` invariant | `finance/domain/variance.py` | 0.5d |
| 1.3 | Add `BudgetLine.validate_amount_sign()` invariant | `finance/domain/budget.py` | 0.5d |
| 1.4 | Add `RootCauseFinding.validate_evidence_sufficiency()` | `finance/domain/evidence.py` | 1d |
| 1.5 | Convert `RecommendationStatus` → StrEnum (already enum) | No change needed | 0d |
| 1.6 | Convert `CommentaryDraft.status` → `CommentaryStatus` StrEnum | `shared/models/state.py` | 0.5d |
| 1.7 | Convert `AgentRun.status` → `AgentRunStatus` StrEnum | `shared/models/database.py` | 0.5d |
| 1.8 | Add `created_at`/`updated_at` to Variance, BudgetLine domain models | `finance/domain/*.py` | 1d |
| 1.9 | Add `tenant_id` to domain models that reference external entities | Multiple domain models | 1d |
| 1.10 | Add `CompanyStatus` enum and onboarding state machine | `finance/domain/company.py` | 1d |
| 1.11 | Write unit tests for all new invariants | `tests/unit/test_finance/domain/` | 1d |
| 1.12 | Run existing test suite — ensure NO regressions | — | 0.5d |

### Validation
- ✅ All existing 83+ tests pass with no modifications
- ✅ `ruff check .` passes with no new warnings
- ✅ `mypy .` passes with no new errors
- ✅ Each domain model has `created_at`, `updated_at`, `version`
- ✅ Every `str` status field has been replaced with a `StrEnum`

---

## Phase 2: Data Contract Layer (Weeks 3-4)

**Theme:** Create the versioned contract layer between connectors and domain models.

### Goals
1. Create `finance/data_contracts/` directory structure
2. Implement `ContractRegistry` with version resolution
3. Implement `ColumnMapper` with alias resolution
4. Define V1 contracts for Invoice, Vendor, Payment, LedgerEntry
5. Implement migration functions (V1→V2)
6. Integrate with `python_runtime/validation/` module

### Tasks

| # | Task | Files Affected | Effort |
|---|------|---------------|--------|
| 2.1 | Create `finance/data_contracts/__init__.py` | New file | 0.5d |
| 2.2 | Implement `ContractRegistry` class | `finance/data_contracts/registry.py` | 1d |
| 2.3 | Implement `ContractInfo` metadata class | `finance/data_contracts/registry.py` | 0.5d |
| 2.4 | Implement `ColumnMapper` with alias resolution | `finance/data_contracts/column_mapping.py` | 1d |
| 2.5 | Implement `UnknownColumnClassifier` (ignore/map/reject) | `finance/data_contracts/column_mapping.py` | 1d |
| 2.6 | Define `InvoiceV1` contract | `finance/data_contracts/v1/invoice.py` | 0.5d |
| 2.7 | Define `InvoiceV2` contract (adds tax_amount) | `finance/data_contracts/v2/invoice.py` | 0.5d |
| 2.8 | Define `VendorV1` contract | `finance/data_contracts/v1/vendor.py` | 0.5d |
| 2.9 | Define `VendorV2` contract (adds risk_score) | `finance/data_contracts/v2/vendor.py` | 0.5d |
| 2.10 | Define `PaymentV1` contract | `finance/data_contracts/v1/payment.py` | 0.5d |
| 2.11 | Define `LedgerEntryV1` contract | `finance/data_contracts/v1/ledger.py` | 0.5d |
| 2.12 | Implement `invoice_v1_to_v2` migration | `finance/data_contracts/migrations/` | 1d |
| 2.13 | Implement `vendor_v1_to_v2` migration | `finance/data_contracts/migrations/` | 1d |
| 2.14 | Integrate `ContractRegistry` into `DualValidator` flow | `python_runtime/validation/validator.py` | 1d |
| 2.15 | Add `contract_version` field to `RuntimeRequest` | `python_runtime/api/models.py` | 0.5d |
| 2.16 | Write test suite for contract registry | `tests/unit/test_data_contracts/` | 1d |
| 2.17 | Write tests for column mapping and migrations | `tests/unit/test_data_contracts/` | 1d |

### File Count
- New files: ~15 (contract definitions, registry, migrations, tests)
- Modified files: ~3 (DualValidator, RuntimeRequest, existing domain models)

---

## Phase 3: State Machines (Weeks 4-5)

**Theme:** Enforce legal state transitions across all workflow entities.

### Goals
1. Create `finance/state_machines/` module
2. Implement `StateMachine` base class with transition validation
3. Define all 7 entity state machines
4. Add `transition_to()` methods to domain models
5. Add PostgreSQL CHECK constraints via Alembic migrations
6. Wire state transition audit events to `AuditLog`

### Tasks

| # | Task | Files Affected | Effort |
|---|------|---------------|--------|
| 3.1 | Create `finance/state_machines/registry.py` — `TransitionError`, `StateMachine` base | New file | 1d |
| 3.2 | Create `finance/state_machines/pipeline.py` — `PipelineRunSM` | New file | 0.5d |
| 3.3 | Create `finance/state_machines/agent.py` — `AgentRunSM` | New file | 0.5d |
| 3.4 | Create `finance/state_machines/job.py` — `JobSM` | New file | 0.5d |
| 3.5 | Create `finance/state_machines/action.py` — `ActionItemSM` | New file | 0.5d |
| 3.6 | Create `finance/state_machines/recommendation.py` — `RecommendationSM` | New file | 0.5d |
| 3.7 | Create `finance/state_machines/commentary.py` — `CommentarySM` | New file | 0.5d |
| 3.8 | Create `finance/state_machines/period.py` — `FiscalPeriodSM` | New file | 0.5d |
| 3.9 | Add `transition_to()` to `PipelineRun` domain model | Existing model | 0.5d |
| 3.10 | Add `transition_to()` to `ActionItem` | `shared/models/action.py` | 0.5d |
| 3.11 | Add `transition_to()` to `CommentaryVersion` | Existing model | 0.5d |
| 3.12 | Add `transition_to()` to `FiscalPeriod` | `finance/domain/fiscal_calendar.py` | 0.5d |
| 3.13 | Create Alembic migration for CHECK constraints | `alembic/versions/` | 1d |
| 3.14 | Add `StateTransitionEvent` model (not stored directly — serialized into `AuditLog`) | New model | 0.5d |
| 3.15 | Wire audit event emission in `transition_to()` | All state machine models | 1d |
| 3.16 | Write exhaustive test suite (every legal + illegal transition) | `tests/unit/test_state_machines/` | 2d |

### Testing
- Each state machine: `test_all_legal_transitions_pass()` + `test_all_illegal_transitions_raise()` + `test_terminal_states()` + `test_initial_states()`
- Each domain model with `transition_to()`: `test_transition_updates_status()` + `test_illegal_transition_raises()`
- Integration: `test_database_check_constraint_catches_illegal_status()`

---

## Phase 4: Business Rule Engine (Weeks 5-7)

**Theme:** Separate business policies from validation logic.

### Goals
1. Create `finance/rules/` module
2. Implement `BaseRule`, `RuleRegistry`, `RuleContext`
3. Implement all rule categories (materiality, autonomy, freshness, compliance, data quality)
4. Integrate with assertion pipeline
5. Integrate with policy engine
6. Write comprehensive test suite

### Tasks

| # | Task | Files Affected | Effort |
|---|------|---------------|--------|
| 4.1 | Create `finance/rules/base.py` — `BaseRule`, `RuleEvaluation`, enums | New file | 1d |
| 4.2 | Create `finance/rules/registry.py` — `RuleRegistry` | New file | 1d |
| 4.3 | Create `finance/rules/context.py` — `RuleContext` | New file | 0.5d |
| 4.4 | Create `finance/rules/report.py` — `RuleEvaluationReport` | New file | 0.5d |
| 4.5 | Implement `AbsoluteThresholdRule` | `finance/rules/materiality.py` | 0.5d |
| 4.6 | Implement `PercentageThresholdRule` | `finance/rules/materiality.py` | 0.5d |
| 4.7 | Implement `CombinedThresholdRule` | `finance/rules/materiality.py` | 0.5d |
| 4.8 | Implement `AccountTypeOverrideRule` | `finance/rules/materiality.py` | 0.5d |
| 4.9 | Implement `TrendMaterialityRule` | `finance/rules/materiality.py` | 0.5d |
| 4.10 | Implement `DegradedModeGateRule` | `finance/rules/autonomy.py` | 0.5d |
| 4.11 | Implement `ActionImpactReviewRule` | `finance/rules/autonomy.py` | 0.5d |
| 4.12 | Implement `FirstTimeActionRule` | `finance/rules/autonomy.py` | 0.5d |
| 4.13 | Implement `CommentaryAssertionMatchRule` | `finance/rules/autonomy.py` | 0.5d |
| 4.14 | Implement freshness rules (DataFreshness, SourceLag, PeriodCutoff) | `finance/rules/freshness.py` | 1d |
| 4.15 | Implement compliance rules (TaxAccount, PeriodCutoff, Currency) | `finance/rules/compliance.py` | 1d |
| 4.16 | Implement data quality rules (Coverage, RowCount, SourceDiversity) | `finance/rules/data_quality.py` | 1d |
| 4.17 | Create `finance/rules/__init__.py` — `register_all_rules()` | New file | 0.5d |
| 4.18 | Integrate RuleRegistry into assertion pipeline | `agents/assertion_pipeline.py` | 1d |
| 4.19 | Integrate RuleRegistry into policy evaluation | `shared/utils/policy.py` | 1d |
| 4.20 | Write tests for materiality rules | `tests/unit/test_rules/` | 1d |
| 4.21 | Write tests for autonomy/freshness/compliance rules | `tests/unit/test_rules/` | 1.5d |
| 4.22 | Write integration tests for rule+assertion pipeline | `tests/integration/` | 1d |

### Key Files Modified
- `agents/assertion_pipeline.py` — call `RuleRegistry.evaluate()`
- `shared/utils/policy.py` — consume `RuleEvaluationReport` in routing decisions
- `finance/rules/` directory — 15+ new files

---

## Phase 5: Layer Integration and Error Propagation (Weeks 7-8)

**Theme:** Wire all 12 layers together with consistent error handling and degraded mode propagation.

### Goals
1. Create the `LayerPipeline` orchestrator that runs through all 12 layers
2. Implement consistent error envelope across all layers
3. Implement degraded mode cascading
4. Wire audit trail from all layers
5. Add integration tests covering the full stack

### Tasks

| # | Task | Files Affected | Effort |
|---|------|---------------|--------|
| 5.1 | Create `LayerPipeline` orchestrator class | `finance/pipeline/layer_pipeline.py` | 2d |
| 5.2 | Define `ValidationLayerError` standard error envelope | `finance/pipeline/errors.py` | 0.5d |
| 5.3 | Implement `LayerResult` with per-layer status tracking | `finance/pipeline/layer_pipeline.py` | 0.5d |
| 5.4 | Implement degraded mode propagation from layer 1→up | `finance/pipeline/degraded.py` | 1d |
| 5.5 | Wire audit events from layers 5, 6, 7, 11 | All layer modules | 1d |
| 5.6 | Add `layer` field to `RuntimeErrorInfo` | `python_runtime/shared/errors.py` | 0.5d |
| 5.7 | Update `PipelineState` to carry per-layer results | `shared/models/state.py` | 0.5d |
| 5.8 | Write full-stack integration tests (happy path) | `tests/integration/layers/` | 1d |
| 5.9 | Write full-stack integration tests (each layer failure) | `tests/integration/layers/` | 2d |
| 5.10 | Write degraded mode cascade test | `tests/integration/` | 1d |

### Integration Test Scenarios

```python
# tests/integration/layers/test_pipeline_orchestrator.py

def test_happy_path_all_layers_pass():
    """Clean data passes through all 12 layers successfully."""
    result = LayerPipeline.run(csv_data=clean_financial_csv)
    assert all(layer.status == "passed" for layer in result.layer_results)
    assert result.final_status == "success"

def test_layer_1_connector_failure_propagates():
    """Source unreachable produces degraded mode and blocks pipeline."""
    result = LayerPipeline.run(csv_data=empty_csv)
    assert result.layer_results[0].status == "failed"
    assert result.layer_results[1].status == "skipped"  # blocked by layer 1
    assert DegradedMode.LOW_COVERAGE in result.degraded_modes

def test_layer_10_versioned_models_rejects_unknown():
    """Unknown contract version is caught at the boundary."""
    result = LayerPipeline.run(csv_data=csv_with_unknown_contract)
    assert result.layer_results[9].status == "failed"  # layer 10 = index 9
    assert "CONTRACT_VERSION_UNKNOWN" in [e.code for e in result.errors]

def test_layer_7_rule_violation_routes_to_human():
    """Business rule violation produces policy decision, not pipeline failure."""
    result = LayerPipeline.run(csv_data=high_value_variance_csv)
    assert result.layer_results[6].status == "warning"  # layer 7 = index 6
    assert result.policy_decision.routing_target == "manager_review"
```

---

## Phase 6: Testing, Documentation, and Stabilization (Weeks 8-10)

**Theme:** Production readiness — comprehensive testing, documentation, performance.

### Goals
1. Achieve 100% test coverage for all new code
2. Write or update all architecture documents
3. Performance benchmark the 12-layer pipeline
4. Add degraded mode recovery tests
5. Run full regression suite (existing 83+ tests + new tests)

### Tasks

| # | Task | Details | Effort |
|---|------|---------|--------|
| 6.1 | Write missing unit tests (measure coverage, fill gaps) | All new modules | 2d |
| 6.2 | Write property-based tests for state machines (Hypothesis) | State machine tests | 1d |
| 6.3 | Write property-based tests for variance invariants | Domain model tests | 1d |
| 6.4 | Performance benchmark: measure latency per layer | Benchmark script | 1d |
| 6.5 | Performance optimization: identify and fix bottlenecks | As needed | 2d |
| 6.6 | Write degraded mode recovery integration tests | Integration tests | 1d |
| 6.7 | Update `docs/09-platform/dataops.md` with contract layer | Documentation | 1d |
| 6.8 | Update `docs/09-platform/devsecops.md` with state machines | Documentation | 0.5d |
| 6.9 | Create `docs/11-data-contracts/` README linking all docs | Documentation | 0.5d |
| 6.10 | Full regression run: `ruff && mypy && pytest` | All code | 0.5d |
| 6.11 | Team review of all documents and code | Review | 2d |

### Exit Criteria

- [ ] All Phase 1-5 tasks complete with passing CI
- [ ] Test count > 200 (83 existing + ~120 new)
- [ ] `ruff check .` — zero warnings
- [ ] `mypy .` — zero errors
- [ ] `python -m pytest` — 100% pass rate
- [ ] All 12 layer integration tests pass (happy + all failure modes)
- [ ] `docs/11-data-contracts/*.md` reviewed by team
- [ ] Performance: full 12-layer pipeline < 500ms for 1000-row CSV (excluding compute)

---

## Summary: Phases at a Glance

| Phase | Focus | Weeks | New Files | Modified Files | Tests Added |
|-------|-------|-------|-----------|---------------|-------------|
| 1 | Domain Model Enrichment | 1-2 | 0 | ~15 | ~30 |
| 2 | Data Contract Layer | 3-4 | ~15 | ~5 | ~20 |
| 3 | State Machines | 4-5 | ~10 | ~8 | ~40 |
| 4 | Business Rule Engine | 5-7 | ~18 | ~3 | ~30 |
| 5 | Layer Integration | 7-8 | ~5 | ~5 | ~15 |
| 6 | Testing & Docs | 8-10 | ~5 | ~5 | ~10 |
| **Total** | | **8-10 weeks** | **~53** | **~41** | **~145** |

---

## Risk and Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Layer 1 change breaks existing providers | Low | High | Provider Protocol is stable; no changes needed |
| State machine CHECK constraints conflict with existing data | Medium | Medium | Run data migration to fix illegal statuses before adding constraints |
| Business rule engine performance impact | Low | Medium | Rules are evaluated per-entity; benchmark in Phase 6 |
| Contract registry introduces complexity for simple use cases | Medium | Low | Default to no-version (latest contract) — versioning is opt-in |
| Integration with existing 83+ tests requires adjustments | Medium | High | Run full suite after every phase; fix regressions immediately |
