# Validation Stages

## Purpose

The FinSight pipeline applies **7 validation stages** to every analysis run. These stages form a progressive quality gate — each stage must pass before the next begins. If any stage fails, the pipeline either degrades gracefully (with a degraded mode flag) or halts with a clear error message.

The validation system ensures that financial commentary is:

- **Accurate** — numbers are correct and reconciled.
- **Grounded** — every claim has supporting evidence.
- **Compliant** — policies and business rules are followed.
- **Actionable** — recommendations are supported and achievable.
- **Review-ready** — output is clear, complete, and professional.

## Validation Pipeline

```
Schema → Financial → Business Rule → Evidence → Hallucination → Recommendation → Executive Review
   V1         V2            V3           V4           V5               V6               V7
```

### Stage 1: Schema Validation

**Domain**: `shared/models/` and `apps/api/schemas.py`

**Purpose**: Ensure all data entering the pipeline conforms to defined Pydantic schemas.

#### What is Validated

| Check | Description | Enforced By |
|-------|-------------|-------------|
| **Type correctness** | All fields match their declared types (str, Decimal, date, etc.) | Pydantic model validation |
| **Monetary values** | All monetary fields use `Decimal` — float values are rejected | `MoneyDecimal` type alias with `_reject_float_money` validator |
| **Required fields** | All required fields are present | Pydantic `BaseModel` |
| **Enum constraints** | All enum fields contain valid values | Pydantic `field_validator` |
| **Field constraints** | String lengths, numeric ranges, pattern matches | Pydantic `Field` constraints |

#### Failure Behavior

- **Rejection**: Data that fails schema validation is rejected with a clear error message identifying the specific field and reason.
- **Non-recoverable**: Schema validation failures are never retried — the input data must be corrected.
- **Pipeline impact**: Schema failure at any input point halts the pipeline for that run.

#### Key Code References

- `MoneyDecimal = Annotated[Decimal, BeforeValidator(_reject_float_money)]` — Rejects float monetary values.
- `field_validator("value", mode="before")` — Applied to all monetary fields in request/response schemas.
- `BaseModel` inheritance — All pipeline models inherit from Pydantic `BaseModel`.

---

### Stage 2: Financial Validation

**Domain**: `finance/validation/`

**Purpose**: Ensure financial data balances and is internally consistent.

#### What is Validated

| Check | Description |
|-------|-------------|
| **Balancing** | Total revenue = sum of department revenues (within tolerance) |
| **Period integrity** | Fiscal period boundaries are contiguous — no gaps or overlaps |
| **Cross-period consistency** | YTD actuals = sum of individual period actuals |
| **Budget-actual alignment** | Same accounts exist in both budget and actual data |
| **Currency consistency** | All values in a single run use the same base currency |
| **Date boundaries** | Transaction dates fall within the correct fiscal period |

#### Failure Behavior

- **Degraded mode**: Financial validation failures do not halt the pipeline but raise degraded mode flags.
- **Annotated output**: Sections affected by validation failures include a data quality note.
- **Confidence reduction**: Overall confidence is reduced proportionally to the severity of failures.
- **Error aggregation**: Multiple failures are aggregated and reported in the `DataQualityResponse`.

#### Key Code References

- `finance/validation/validator.py` — Validation logic.
- `finance/validation/calendar.py` — Fiscal period boundary validation.
- `finance/validation/data_quality.py` — Data quality scoring and reporting.
- `DataQualityCheckResponse(check=..., passed=bool, severity=str)` — Validation result format.

---

### Stage 3: Business Rule Validation

**Domain**: `finance/validation/` and `shared/models/assertions.py`

**Purpose**: Ensure the analysis complies with configured business policies.

#### What is Validated

| Check | Description |
|-------|-------------|
| **Account structure** | All referenced accounts exist in the chart of accounts |
| **Account status** | No deactivated accounts are used as active analysis targets |
| **Period status** | The fiscal period is in a valid state for analysis (OPEN, ANALYZING) |
| **Version currency** | Budget version referenced is the current approved version |
| **Materiality configuration** | Materiality rules are valid and complete |
| **Policy compliance** | Recommendations comply with configured policy rules |

#### Failure Behavior

- **Blocking**: Some business rule violations (e.g., referencing a non-existent account) block the pipeline.
- **Non-blocking**: Other violations (e.g., deactivated account with historical data) raise degraded mode flags.
- **Escalation**: Persistent violations across multiple runs escalate to a data quality ticket.

#### Key Code References

- `FiscalPeriod.status` — Period must be in a valid state for analysis.
- `MaterialityConfig` — Must be valid and complete with all tiers defined.
- `PolicyDecisionResponse` — Policy compliance decisions for recommendations.

---

### Stage 4: Evidence Validation

**Domain**: `shared/models/assertions.py`

**Purpose**: Ensure every assertion has traceable, verifiable supporting evidence.

#### What is Validated

| Check | Description |
|-------|-------------|
| **Evidence existence** | Every `evidence_id` resolves to a captured evidence item |
| **Evidence sufficiency** | Each assertion has enough evidence to support its claim |
| **Evidence confidence** | Evidence confidence meets the minimum for the assertion type |
| **Evidence period alignment** | Evidence periods match the analysis period |
| **Evidence completeness** | No required evidence types are missing |

#### Failure Behavior

- **Gap logging**: Missing evidence is logged to `Assertion.missing_evidence`.
- **Support level downgrade**: Insufficient evidence causes `support_level` to drop (e.g., VERIFIED → PROBABLE → WEAK → INSUFFICIENT).
- **Degraded mode**: Evidence gaps raise `INSUFFICIENT_CAUSAL_EVIDENCE` degraded mode flags.
- **Rejection**: Assertions with no evidence at all are rejected and not included in output.

#### Key Code References

- `Assertion(evidence_ids=..., support_level=...)` — All assertions carry evidence references and a support level.
- `SupportLevel.VERIFIED / PROBABLE / WEAK / INSUFFICIENT` — Support level enum.
- `EvidenceItem(source_table=..., record_id=..., field=...)` — Captured evidence structure.

---

### Stage 5: Hallucination Detection

**Domain**: Guardrails system

**Purpose**: Verify that LLM-generated claims match the evidence and are not fabricated.

#### What is Validated

| Check | Description |
|-------|-------------|
| **Contradiction** | Claims do not contradict established evidence |
| **Fact verification** | Every number is grounded in an evidence source |
| **Source attribution** | Every claim is traceable through an attribution chain |
| **Confidence thresholds** | Claims meet minimum confidence requirements |

#### Failure Behavior

- **Soft failure** (confidence 0.50-0.69): One retry with hallucination flag guidance. Confidence penalty of -0.1 if passed.
- **Hard failure** (confidence < 0.50 or contradiction): Section replaced with placeholder. `HALLUCINATION_DETECTED` degraded mode raised.
- **Escalation**: Persistent hallucinations across multiple runs trigger an investigation.

#### Key Code References

- See **[hallucination.md](./hallucination.md)** for complete hallucination detection documentation.
- `Assertion(source="deterministic" | "llm_analysis" | "human")` — Source type affects hallucination checking strictness.

---

### Stage 6: Recommendation Validation

**Domain**: `finance/recommendation_engine/`

**Purpose**: Ensure recommendations are actionable, supported, and policy-compliant.

#### What is Validated

| Check | Description |
|-------|-------------|
| **Actionability** | Recommendation describes a concrete, executable action |
| **Evidence support** | Recommendation cites at least one assertion ID |
| **Policy compliance** | Recommendation passes policy decision engine |
| **Non-conflicting** | Recommendation does not contradict another active recommendation |
| **Impact quantification** | Financial impact is quantified where possible |

#### Failure Behavior

- **Blocked**: Recommendations that fail policy compliance are blocked and logged.
- **Routed**: Recommendations with insufficient confidence are routed for human review.
- **Annotated**: Conflicting recommendations are annotated with a conflict note.

#### Key Code References

- `ActionItem(policy_permitted=bool, blocked_reason=str)` — Policy compliance status.
- `PolicyDecisionResponse(autonomy_level=..., blocked_actions=[...])` — Policy decisions.
- `ActionCreateRequest(impact_expected_savings=MoneyDecimal, ...)` — Impact quantification.

---

### Stage 7: Executive Review Readiness

**Purpose**: Ensure the final output is clear, complete, and suitable for executive consumption.

#### What is Validated

| Check | Description |
|-------|-------------|
| **Completeness** | All required commentary sections are present |
| **Clarity** | Writing is clear, jargon-minimized, and well-structured |
| **Consistency** | Same facts produce same conclusions across sections |
| **Tone** | Professional, objective, and fact-based |
| **Presentation quality** | Numbers are formatted, sections are ordered logically |
| **Executive summary** | Key message is conveyed in the opening section |

#### Failure Behavior

- **Re-formatting**: Presentation quality issues trigger a formatting pass (no content change).
- **Flagging**: Consistency or clarity issues are flagged for human review.
- **No blocking**: Stage 7 failures never block delivery — they add review annotations.

#### Key Code References

- `CommentaryDraft(status="draft", approval_state=str)` — Draft before executive review.
- `CommentarySection(section_type=..., content=..., cited_data_points=[...])` — Individual sections.

## Validation Summary

| Stage | Name | Domain | Failure Type | Blocking? |
|-------|------|--------|-------------|-----------|
| V1 | Schema Validation | `shared/models/`, `apps/api/schemas.py` | Rejection | Yes |
| V2 | Financial Validation | `finance/validation/` | Degraded | No |
| V3 | Business Rule Validation | `finance/validation/`, `shared/models/` | Degraded / Blocking | Sometimes |
| V4 | Evidence Validation | `shared/models/assertions.py` | Degraded / Rejection | Sometimes |
| V5 | Hallucination Detection | Guardrails | Retry / Placeholder | Soft |
| V6 | Recommendation Validation | `finance/recommendation_engine/` | Blocked / Routed | Soft |
| V7 | Executive Review Readiness | — | Flagged / Re-formatted | No |
