# Layer Architecture — 12-Layer Validation and Governance Stack

> **Audience:** Platform architects, all engineers, operations
> **Status:** Design proposal for Phase 2

## 1. The 12 Validation Layers

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     COMPLETE VALIDATION & GOVERNANCE STACK                │
│                                                                          │
│  Layer   Name                 Location              Enforced By          │
│  ─────   ──────               ──────────            ───────────          │
│    1     Connector Valid.     finance/integration/   Provider Protocol    │
│    2     API Contract         python_runtime/api/    Pydantic model       │
│    3     Dataset Schema       python_runtime/valid/  Pandera DataFrame    │
│    4     Domain Models        finance/domain/        Pydantic + MoneyDec  │
│    5     Database Constraints shared/models/         SQLAlchemy + DDL     │
│    6     State Machines       finance/state_machines/ Transition enums    │
│    7     Business Rules       finance/rules/         RuleRegistry         │
│    8     Security             apps/api/ + DB          tenant_id + auth    │
│    9     Audit Trail          shared/models/          Append-only table   │
│   10     Versioned Models     finance/data_contracts/ ContractRegistry    │
│   11     Compute Validation   python_runtime/         HandlerResult type  │
│   12     Agent Validation     shared/utils/validators/ Assertion rules    │
└──────────────────────────────────────────────────────────────────────────┘
```

Each layer has a defined responsibility, an owner, and a failure mode. No layer silently passes bad data to the next — if a layer cannot validate, it produces a structured error.

---

## 2. Data Flow Through All 12 Layers

```
External Source (CSV, Google Sheets, ERP API, PostgreSQL)
    │
    │   RAW DATA (bytes, rows, API response)
    ▼
┌────────────────────────────────────────────────────────────────────┐
│ LAYER 1: CONNECTOR VALIDATION                                      │
│ ┌────────────────────────────────────────────────────────────────┐ │
│ │ Provider Protocol Check    │   Credential Validation           │ │
│ │ Source Reachability        │   ToolResult construction         │ │
│ └────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│ Output: ToolResult (source_fingerprint, row_count, coverage_pct)    │
│ Failure: ImportError → retry or fail                                │
└────────────────────────────────────────────────────────────────────┘
    │
    │   ToolResult
    ▼
┌────────────────────────────────────────────────────────────────────┐
│ LAYER 2: API CONTRACT                                              │
│ ┌────────────────────────────────────────────────────────────────┐ │
│ │ RuntimeRequest validation     │   JobType enum check           │ │
│ │ Source config validation      │   Parameter schema             │ │
│ └────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│ Output: validated RuntimeRequest                                    │
│ Failure: ComputeError(VALIDATION_ERROR)                             │
└────────────────────────────────────────────────────────────────────┘
    │
    │   RuntimeRequest + Dataset
    ▼
┌────────────────────────────────────────────────────────────────────┐
│ LAYER 10: VERSIONED MODELS                                         │
│ ┌────────────────────────────────────────────────────────────────┐ │
│ │ ContractRegistry.resolve()     →  InvoiceV3 model             │ │
│ │ ColumnMapper.apply()           →  alias resolution             │ │
│ │ UnknownColumnClassifier        →  ignore / map / reject       │ │
│ └────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│ Output: schema-aligned Dataset with known columns only              │
│ Failure: CONTRACT_VERSION_UNKNOWN, CONTRACT_COLUMN_CONFLICT         │
└────────────────────────────────────────────────────────────────────┘
    │
    │   Schema-aligned Dataset
    ▼
┌────────────────────────────────────────────────────────────────────┐
│ LAYER 3: DATASET SCHEMA (Pandera)                                  │
│ ┌────────────────────────────────────────────────────────────────┐ │
│ │ FinancialDatasetSchema.validate()  →  null / type / enum check │ │
│ │ VarianceInputSchema.validate()     →  bound / uniqueness check │ │
│ │ SCHEMA_REGISTRY lookup            →  schema per pipeline type  │ │
│ └────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│ Output: validated Dataset (or list of ValidationErrorInfo)          │
│ Failure: ComputeError(DATASET_VALIDATION_ERROR)                     │
└────────────────────────────────────────────────────────────────────┘
    │
    │   Validated Dataset (Pandera-passed)
    ▼
┌────────────────────────────────────────────────────────────────────┐
│ LAYER 4: DOMAIN MODELS                                             │
│ ┌────────────────────────────────────────────────────────────────┐ │
│ │ Pydantic model construction     │   MoneyDecimal validator     │ │
│ │ @model_validator invariants      │   State transition methods  │ │
│ │ Variance math guarantees         │   Cross-field consistency   │ │
│ └────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│ Output: typed domain objects (Budget, Variance, Actual, etc.)       │
│ Failure: Pydantic ValidationError                                   │
└────────────────────────────────────────────────────────────────────┘
    │
    │   Domain objects
    ▼
┌────────────────────────────────────────────────────────────────────┐
│ LAYER 7: BUSINESS RULES                                            │
│ ┌────────────────────────────────────────────────────────────────┐ │
│ │ RuleRegistry.evaluate(entity, context)                         │ │
│ │ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐         │ │
│ │ │Materiality│ │Autonomy  │ │Freshness │ │Compliance│         │ │
│ │ │Rules     │ │Rules     │ │Rules     │ │Rules     │         │ │
│ │ └──────────┘ └──────────┘ └──────────┘ └──────────┘         │ │
│ └────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│ Output: RuleEvaluationReport (passed, failed, policy decision)      │
│ Failure: Blocking rule → pipeline routes to human review            │
└────────────────────────────────────────────────────────────────────┘
    │
    │   Policy decision attached
    ▼
┌────────────────────────────────────────────────────────────────────┐
│ LAYER 5: DATABASE CONSTRAINTS                                      │
│ ┌────────────────────────────────────────────────────────────────┐ │
│ │ SQLAlchemy Column types     →  Numeric(15,2) for money         │ │
│ │ ForeignKey constraints      →  referential integrity           │ │
│ │ NOT NULL / UNIQUE           →  field-level constraints         │ │
│ │ CHECK constraints           →  state machine mirrors (see §7)  │ │
│ └────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│ Output: persisted records (or IntegrityError)                       │
└────────────────────────────────────────────────────────────────────┘
    │
    │   Persisted records
    ▼
┌────────────────────────────────────────────────────────────────────┐
│ LAYER 6: STATE MACHINES                                            │
│ ┌────────────────────────────────────────────────────────────────┐ │
│ │ PipelineRunSM      →  PENDING → RUNNING → SUCCESS/FAILED      │ │
│ │ AgentRunSM         →  PENDING → RUNNING → SUCCESS/FAILED      │ │
│ │ JobSM              →  QUEUED → RUNNING → ... → SUCCESS/FAILED  │ │
│ │ ActionItemSM       →  PROPOSED → APPROVED → ... → COMPLETED   │ │
│ │ RecommendationSM   →  PROPOSED → REVIEWED → APPROVED/REJECTED │ │
│ │ CommentarySM       →  DRAFT → REVIEWING → APPROVED/PUBLISHED  │ │
│ │ FiscalPeriodSM     →  OPEN → CLOSING → CLOSED → ARCHIVED      │ │
│ └────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│ Output: legal transition or TransitionError                         │
└────────────────────────────────────────────────────────────────────┘
    │
    │   State transition recorded
    ▼
┌────────────────────────────────────────────────────────────────────┐
│ LAYER 9: AUDIT TRAIL                                               │
│ ┌────────────────────────────────────────────────────────────────┐ │
│ │ AuditLog.append()    →  immutable, append-only                 │ │
│ │ StateTransitionEvent →  every status change recorded           │ │
│ │ RuleEvaluationReport →  every policy decision recorded         │ │
│ └────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│ Output: AuditLog entry (never fails — async fire-and-forget)        │
└────────────────────────────────────────────────────────────────────┘
    │
    │   Audit trail verified
    ▼
┌────────────────────────────────────────────────────────────────────┐
│ LAYER 8: SECURITY                                                  │
│ ┌────────────────────────────────────────────────────────────────┐ │
│ │ Tenant ID validation       →  every query filtered by tenant   │ │
│ │ Authentication check       →  JWT / API key validation         │ │
│ │ Authorization              →  user has permission for action   │ │
│ │ PII protection             →  no PII in logs or errors         │ │
│ └────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│ Output: authorized request (or HTTP 401/403)                        │
└────────────────────────────────────────────────────────────────────┘
    │
    │   Authorized data
    ▼
┌────────────────────────────────────────────────────────────────────┐
│ LAYER 11: COMPUTE VALIDATION                                       │
│ ┌────────────────────────────────────────────────────────────────┐ │
│ │ HandlerResult Pydantic model    →  structured output           │ │
│ │ Export serialization check      →  JSON-serializable types     │ │
│ │ Output row count validation     →  within expected bounds      │ │
│ │ Cache key verification          →  deterministic keys          │ │
│ └────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│ Output: HandlerResult (or ExportError)                              │
└────────────────────────────────────────────────────────────────────┘
    │
    │   Computed result
    ▼
┌────────────────────────────────────────────────────────────────────┐
│ LAYER 12: AGENT VALIDATION                                         │
│ ┌────────────────────────────────────────────────────────────────┐ │
│ │ AssertionValidator.validate()  →  support level downgrade      │ │
│ │ Evidence chain integrity       →  every evidence_id resolves   │ │
│ │ Source diversity check         →  minimum distinct sources     │ │
│ │ Contradiction detection        →  conflicting assertions       │ │
│ └────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│ Output: validated assertions (or downgraded support level)          │
└────────────────────────────────────────────────────────────────────┘
    │
    ▼
Final Output (Board Report, Commentary, Action Items)
```

---

## 3. Error Propagation and Graceful Degradation

### 3.1 Error Propagation Rules

| Layer | Error Type | Propagates? | Degraded Mode? | Human Notification? |
|-------|-----------|-------------|----------------|---------------------|
| 1 | ImportError | Up to retry policy | Yes (LOW_COVERAGE) | If retries exhausted |
| 2 | ComputeError(VALIDATION) | Immediate to caller | No | Yes |
| 10 | CONTRACT_VERSION_UNKNOWN | Immediate to caller | No | Yes |
| 10 | CONTRACT_DEPRECATED | Warning, continues | Yes (STALE_SOURCE) | Warning log |
| 3 | ComputeError(DATASET) | Blocks pipeline | Yes (LOW_COVERAGE) | Yes |
| 4 | ValidationError | Blocks pipeline | No | Yes |
| 7 | RuleEvaluation(FAIL) | Routes to human | Yes (policy decision) | Yes |
| 5 | IntegrityError | Blocks pipeline | No | Yes |
| 6 | TransitionError | Blocks state change | No | Yes |
| 8 | Auth failure | Immediate 401/403 | No | No |
| 11 | ExportError | Blocks final output | No | Yes |
| 12 | SupportLevel downgrade | Warning, continues | Yes (INSUFFICIENT_CAUSAL) | Warning |

### 3.2 Degraded Mode Cascading

```
             ┌──────────────┐
             │ Layer 1 fail │───→ LOW_COVERAGE
             └──────────────┘
                      │
                      ▼
             ┌──────────────┐
             │ Layer 7 fail │───→ POLICY_GATE (route to human)
             └──────────────┘
                      │
                      ▼
             ┌──────────────────┐
             │ Layer 12 fail    │───→ INSUFFICIENT_CAUSAL_EVIDENCE
             └──────────────────┘
                      │
                      ▼
             ┌──────────────────┐
             │ Agent pipeline   │───→ Respects degraded modes
             │ (AgentOps)       │     → Lower autonomy level
             └──────────────────┘     → Route for review
```

The `DegradedMode` enum (`shared/models/degraded_mode.py`) propagates through `PipelineState.degraded_modes` and is consumed by the policy engine:

```python
# In policy_evaluation.py
from shared.models.degraded_mode import DegradedMode

DEGRADED_AUTONOMY_MAP = {
    DegradedMode.LOW_COVERAGE: AutonomyLevel.MANAGER_APPROVAL,
    DegradedMode.STALE_SOURCE: AutonomyLevel.MANAGER_APPROVAL,
    DegradedMode.MISSING_FX: AutonomyLevel.MANAGER_APPROVAL,
    DegradedMode.INSUFFICIENT_CAUSAL_EVIDENCE: AutonomyLevel.REVIEW_REQUIRED,
    DegradedMode.FACT_VERIFIED_CAUSE_UNVERIFIED: AutonomyLevel.REVIEW_REQUIRED,
    DegradedMode.PRECEDENT_ONLY_SUPPORT: AutonomyLevel.AUTO_APPROVE,
}

def determine_autonomy(degraded_modes: list[str]) -> AutonomyLevel:
    mode_enums = [DegradedMode(m) for m in degraded_modes]
    for level in [AutonomyLevel.MANAGER_APPROVAL, 
                  AutonomyLevel.REVIEW_REQUIRED,
                  AutonomyLevel.AUTO_APPROVE]:
        if level in [DEGRADED_AUTONOMY_MAP.get(m, AutonomyLevel.AUTO_APPROVE) 
                     for m in mode_enums]:
            return level
    return AutonomyLevel.AUTO_APPROVE
```

### 3.3 Error Object Shape

All layers produce errors with a consistent structure:

```python
class ValidationLayerError(BaseModel):
    """Standard error envelope for all 12 layers."""
    
    layer: int                    # 1-12
    layer_name: str               # e.g., "Dataset Schema"
    code: str                     # e.g., "DATASET_MISSING_COLUMN"
    message: str                  # Human-readable
    severity: str                 # "info" | "warning" | "error" | "critical"
    recoverable: bool             # Can pipeline continue with degraded output?
    retryable: bool               # Should the operation be retried?
    details: dict[str, Any]       # Layer-specific context
    degraded_mode: str | None     # Corresponding DegradedMode if applicable
```

---

## 4. Layer Ownership and Evolution

| Layer | Owner | Change Process | Test File Location |
|-------|-------|---------------|-------------------|
| 1 | DataOps | Provider implementation changes | `tests/unit/test_finance/integration/` |
| 2 | Compute | RuntimeRequest model changes | `tests/unit/test_api/` |
| 3 | DataOps | Pandera schema changes | `tests/unit/test_validators/` |
| 4 | Domain | Domain model enrichment | `tests/unit/test_finance/domain/` |
| 5 | DevSecOps | Migration scripts | `tests/unit/test_models/` |
| 6 | Domain | State machine changes | `tests/unit/test_state_machines/` |
| 7 | Domain | Rule changes | `tests/unit/test_rules/` |
| 8 | DevSecOps | Security policy changes | `tests/backend/api/` |
| 9 | DevSecOps | Audit schema changes | `tests/unit/test_models/` |
| 10 | DataOps | Contract version changes | `tests/unit/test_data_contracts/` |
| 11 | Compute | Handler type changes | `tests/unit/test_runtime/` |
| 12 | AgentOps | Assertion rule changes | `tests/backend/validators/` |

---

## 5. Layer Interaction Matrix

Which layers call which other layers:

```
Layer   Calls →     1   2   3   4   5   6   7   8   9  10  11  12
─────────────────────────────────────────────────────────────────
1  Connector        ─   ✗   ✗   ✗   ✗   ✗   ✗   ✓   ✗   ✗   ✗   ✗
2  API Contract     ✓   ─   ✗   ✗   ✗   ✗   ✗   ✓   ✗   ✓   ✗   ✗
3  Dataset Schema   ✗   ✗   ─   ✗   ✗   ✗   ✗   ✗   ✗   ✓   ✗   ✗
4  Domain Models    ✗   ✗   ✗   ─   ✗   ✓   ✓   ✗   ✗   ✗   ✗   ✗
5  Database         ✗   ✗   ✗   ✗   ─   ✗   ✗   ✓   ✓   ✗   ✗   ✗
6  State Machines   ✗   ✗   ✗   ✓   ✓   ─   ✗   ✗   ✓   ✗   ✗   ✗
7  Business Rules   ✗   ✗   ✗   ✓   ✗   ✗   ─   ✗   ✓   ✗   ✗   ✓
8  Security         ✗   ✓   ✗   ✗   ✓   ✗   ✗   ─   ✓   ✗   ✓   ✗
9  Audit Trail      ✗   ✗   ✗   ✗   ✓   ✓   ✓   ✗   ─   ✗   ✗   ✗
10 Versioned Models ✗   ✓   ✓   ✗   ✗   ✗   ✗   ✗   ✗   ─   ✗   ✗
11 Compute Validate ✗   ✗   ✗   ✓   ✗   ✗   ✗   ✗   ✓   ✗   ─   ✗
12 Agent Validate   ✗   ✗   ✗   ✓   ✗   ✗   ✓   ✗   ✓   ✗   ✗   ─

✓ = calls  ✗ = does not call  ─ = self
```

Key rules:
- **Layer 4 (Domain Models)** is the most-coupled layer — it enforces invariants, drives state machines, and is evaluated by business rules.
- **Layer 8 (Security)** is called by the outer layers (1, 2, 5) — it is a cross-cutting concern.
- **Layer 9 (Audit Trail)** is a sink — layers 6, 7, and 11 write to it but nothing reads from it during normal pipeline execution.
- **No layer calls upward** — layer 3 does not call layer 1, layer 7 does not call layer 4's consumers, etc.

---

## 6. Testing the Layer Stack

### 6.1 Integration Test Pattern

```python
# tests/integration/layers/test_full_stack_ingestion.py

def test_full_ingestion_pipeline():
    """A complete CSV file traverses all 12 layers correctly."""
    
    # Arrange: a known-good CSV
    csv_data = b"account_id,amount,period,department\nACCT001,10000,2026-Q1,Sales\n"
    
    # Act: run through the full stack
    result = run_ingestion_pipeline(csv_data, pipeline_type="financial_dataset")
    
    # Assert: each layer succeeded
    assert result.layer_1_status == "passed"   # Connector
    assert result.layer_2_status == "passed"   # API Contract
    assert result.layer_3_status == "passed"   # Pandera
    assert result.layer_4_status == "passed"   # Domain model
    assert result.layer_7_report.passed > 0    # Business rules ran
    assert result.final_status == "success"
    assert isinstance(result.domain_objects[0], BudgetLine)

def test_layer_3_rejects_bad_types():
    """Pandera rejects type mismatches at the dataset boundary."""
    csv_data = b"account_id,amount,period,department\nACCT001,not_a_number,2026-Q1,Sales\n"
    
    result = run_ingestion_pipeline(csv_data, pipeline_type="financial_dataset")
    
    assert result.layer_3_status == "failed"
    assert "DATASET_TYPE_MISMATCH" in [e.code for e in result.errors]
    assert result.final_status == "blocked_at_layer_3"
```

### 6.2 Test Coverage Requirements

| Layer | Minimum Unit Coverage | Minimum Integration Coverage |
|-------|----------------------|-----------------------------|
| 1 | 90% | 3 scenarios (success, auth fail, unreachable) |
| 2 | 100% | 5 scenarios (all job types, missing fields, bad enums) |
| 3 | 100% | 5 scenarios per schema (null, type, enum, bound, missing) |
| 4 | 100% | Every domain model: valid, invalid, edge case |
| 5 | 90% | Every table: CRUD, constraint violation |
| 6 | 100% | Every transition defined = 1 test, every illegal = 1 test |
| 7 | 100% | Every rule: pass, fail, edge case |
| 8 | 100% | Auth success, auth failure, tenant mismatch |
| 9 | 100% | Append succeeds, update rejected |
| 10 | 100% | Version resolution, migration, deprecation warning |
| 11 | 100% | Every handler type: valid output, invalid output |
| 12 | 100% | Every assertion type: meets threshold, below threshold |
