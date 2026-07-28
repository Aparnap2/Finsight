# Evidence Collection Flow

## Purpose

The **Evidence Collection** system is the data foundation of the FinSight assertion pipeline. It identifies, captures, and tracks the provenance of every data point used to support financial assertions, variance analyses, and recommendations. Evidence ensures that every claim made in commentary can be traced back to a verifiable source.

## Evidence Collection Flow

The evidence collection process follows a three-stage pipeline:

```
Source Identification → Evidence Capture → Coverage Scoring
```

### Stage 1: Source Identification

The evidence collector identifies relevant data sources by following a structured chain from high-level KPIs down to individual driver values:

#### KPI → Variance → Driver Chain

```
KPI (Gross Margin decreased 2.2pp)
  └─→ Variance (Revenue -8.2% material, COGS +4.5% material)
        ├─→ Bridge Analysis (Price -$120K, Volume -$280K, Mix -$50K)
        │     ├─→ Driver (Avg Deal Size $45K → $42K -7.1%)
        │     └─→ Driver (Win Rate 32% → 28% -12.5%)
        └─→ Bridge Analysis (Scope +$150K, Rate +$100K)
              └─→ Driver (Headcount 420 → 450 +7.1%)
```

This chain ensures that every KPI movement is decomposed into its underlying drivers. The collector does not stop at the variance level — it continues down to the driver level to provide causal depth.

#### Source Types

| Source Type | Description | Example |
|-------------|-------------|---------|
| **Actuals Table** | Database of posted financial transactions | `actuals` table, ingestion layer |
| **Budget Table** | Budget values per account and period | `budget` table |
| **Forecast Table** | Forecast values per account and period | `forecast` table |
| **Driver Data** | Operational driver values from external systems | HR system headcount data, CRM deal data |
| **Variance Engine** | Pre-computed variance calculations | `Variance` and `MaterialityAssessment` objects |
| **Bridge Analysis** | Decomposed variance components | `BridgeComponent` (price, volume, mix, etc.) |
| **Formula Registry** | KPI calculation formulas | `FormulaRegistry` definitions |
| **Materiality Engine** | Materiality threshold assessments | `MaterialityAssessment` from `MaterialityEngine` |

### Stage 2: Evidence Capture

Each evidence item is captured as an `EvidenceItem` with standardized metadata:

```python
class EvidenceItem(BaseModel):
    source_table: str   # Which data source (actuals, budget, variance_engine, etc.)
    record_id: str      # Unique identifier within the source
    field: str          # Specific field name
    value: Decimal      # The actual value (never float)
    period: str         # Fiscal period identifier
    description: str    # Human-readable description
```

#### Evidence Metadata

| Field | Description | Example |
|-------|-------------|---------|
| `source` | Origin system or table | `"actuals"`, `"variance_engine"`, `"bridge_analysis"` |
| `type` | Kind of evidence | `"monetary"`, `"percentage"`, `"driver_value"`, `"kpi"` |
| `confidence` | Reliability of the evidence source | `0.95` (actuals), `0.85` (bridge analysis), `0.60` (heuristic) |
| `timestamp` | When the evidence was captured | `"2025-04-01T14:30:00Z"` |
| `provenance` | Chain of custody | `"ingestion → validation → variance_engine → evidence_collector"` |
| `degraded` | Whether this evidence is from a degraded mode | `False` |

#### Evidence from Deterministic vs. LLM Sources

All evidence items carry a `source` field that distinguishes deterministic from LLM-derived evidence:

| Source Value | Origin | Confidence Baseline |
|-------------|--------|-------------------|
| `"deterministic"` | Engine computation (variance, materiality, bridge) | ≥ 0.80 |
| `"llm_analysis"` | LLM-generated analysis from commentary pipeline | 0.40 - 0.70 |
| `"human"` | Manually entered or confirmed by FP&A team | ≥ 0.90 |

### Stage 3: Evidence Coverage Scoring

After collection, the system scores how well each variance is covered by evidence.

#### Coverage Scoring Algorithm

For each material variance, evidence coverage is calculated as:

```
Coverage Score = Evidence Weight / Required Evidence Weight

Where:
- Required Evidence Weight = sum of required evidence types for the variance
- Evidence Weight = sum of weights for captured evidence types
```

#### Evidence Types and Weights

| Evidence Type | Weight | Required For |
|--------------|--------|-------------|
| Actual value | 25% | All variances |
| Budget value | 25% | All variances |
| Variance calculation | 20% | All variances |
| Bridge decomposition | 15% | Revenue and COGS variances |
| Driver data | 10% | Driver-based analysis |
| Historical context | 5% | Trend analysis |

#### Coverage Thresholds

| Coverage Score | Label | Action |
|---------------|-------|--------|
| ≥ 90% | **Complete** | Proceed to commentary generation |
| 70% - 89% | **Adequate** | Proceed, include data quality note |
| 50% - 69% | **Partial** | Flag degraded mode, reduce confidence |
| < 50% | **Insufficient** | Escalate — cannot generate reliable commentary |

### Gap Detection

The evidence collector actively identifies missing evidence:

```python
class Assertion(BaseModel):
    evidence_ids: list[str] = []         # References to supporting evidence
    missing_evidence: list[str] = []     # Identified gaps
    support_level: SupportLevel          # Verified / Probable / Weak / Insufficient
```

#### Gap Categories

| Gap Type | Description | Example |
|----------|-------------|---------|
| **Missing Actuals** | Actual data not available for a period | "No actuals for Mar 2025 — period not closed" |
| **Missing Budget** | Budget not defined for an account | "Account 6200 has no budget allocation" |
| **Missing Driver Data** | Driver value not available | "Sales headcount data not loaded for Mar" |
| **Unreconciled Variance** | Bridge components don't sum to total | "Sum of components = -\$450K, total = -\$462K" |
| **Incomplete History** | Insufficient prior period data | "Account created in current year — no YoY comparison" |
| **Data Quality Failures** | Source data failed validation | "FX rate data quality check failed" |

#### Gap Escalation

When evidence gaps accumulate:

1. **Per-variance**: `missing_evidence` is populated on the relevant assertion.
2. **Per-run**: Aggregated gaps are reported in `data_quality.degraded_modes`.
3. **Over multiple runs**: Persistent gaps trigger a data quality investigation recommendation.

## Evidence Quality Tiers

Evidence is classified into quality tiers based on its source and confidence:

| Tier | Label | Confidence Range | Source Examples |
|------|-------|-----------------|-----------------|
| **Tier 1** | Verified | ≥ 0.90 | Posted actuals, confirmed budget, audited financials |
| **Tier 2** | High Confidence | 0.80 - 0.89 | Deterministic engine outputs (variance, bridge, materiality) |
| **Tier 3** | Moderate Confidence | 0.60 - 0.79 | Heuristic-based decomposition, clean LLM analysis |
| **Tier 4** | Low Confidence | 0.40 - 0.59 | LLM analysis with data limitations |
| **Tier 5** | Insufficient | < 0.40 | Missing data, high uncertainty — not usable for assertions |

### Quality Tier Enforcement

- **Tier 4-5** evidence cannot be the sole support for a recommendation.
- **Tier 3+** evidence is required for auto-approval workflows.
- **Tier 2+** evidence is required for CRITICAL and HIGH sensitivity accounts.
- Evidence quality is included in the assertion `support_level` field and affects the overall confidence score.
