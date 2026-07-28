# Hallucination Detection

## Purpose

The **Hallucination Detection** system is a set of guardrails that verify every claim made by the LLM against the evidence collected in the pipeline. It ensures that commentary, assertions, and recommendations are grounded in verified data — not fabricated by the language model. Hallucination detection is the final quality gate before any output reaches the user.

## Detection Dimensions

Hallucination detection operates across four dimensions:

1. **Contradiction Checking** — Does the claim match the evidence?
2. **Fact Verification** — Is the number grounded?
3. **Source Attribution** — Can we trace every claim?
4. **Confidence Threshold Enforcement** — Is the supporting evidence strong enough?

### 1. Contradiction Checking

Checks whether the LLM's claim directly contradicts established evidence.

#### What It Detects

| Hallucination Type | Example | Detection Method |
|-------------------|---------|-----------------|
| **Direction Error** | "Revenue increased 5%" when variance is -8.2% | Compare claim direction vs. evidence direction |
| **Magnitude Error** | "Variance of \$50K" when actual variance is \$250K | Compare claim magnitude vs. evidence magnitude |
| **Causal Error** | "Driven by price decrease" when bridge shows volume is the primary driver | Compare claim attribution vs. bridge decomposition |
| **Temporal Error** | "Q3 results" when analyzing Q2 | Check period identifiers |
| **Entity Error** | "Acme Corp subsidiary" when Acme Corp is the parent | Check company context |

#### Detection Implementation

Contradiction checks compare LLM output assertions against the assertion store:

```python
# Pseudocode
for claim in llm_output.assertions:
    matching_evidence = evidence_store.find(claim.topic, claim.period)
    
    if matching_evidence and sign(claim.value) != sign(matching_evidence.value):
        flag_contradiction(claim, matching_evidence)
    
    if matching_evidence and abs(claim.value - matching_evidence.value) > tolerance:
        flag_magnitude_error(claim, matching_evidence, tolerance)
```

**Tolerance**: Magnitude comparisons use a 10% tolerance by default (configurable per account tier). Claims within 10% of the evidence value pass the magnitude check.

### 2. Fact Verification

Verifies that every numeric claim is grounded in a specific evidence source.

#### Verification Rules

| Rule | Description | Enforcement |
|------|-------------|-------------|
| **Every number must have an evidence ID** | All monetary values in commentary must reference a `cited_data_points` entry | Hard — rejected if missing |
| **Percentages must be computable** | Any percentage claim (e.g., "8.2% decrease") must be derivable from two evidence values | Hard — rejected if not reproducible |
| **Trend claims need 2+ data points** | "Revenue has been declining" requires at least 2 periods of data showing decline | Soft — flagged as low confidence |
| **Causal claims need bridge analysis** | "Driven by price" requires bridge decomposition showing price as >50% of variance | Hard for CRITICAL/HIGH tiers |

#### Grounding Score

Each output section receives a **grounding score**:

```python
grounding_score = (
    number_of_grounded_claims / total_claims
) × data_quality_factor
```

- **grounded_claims**: Claims that have a matching evidence ID or computable from evidence.
- **total_claims**: All claims made in the section.
- **data_quality_factor**: 0.0 - 1.0 based on the data quality checks for the period.

Sections with `grounding_score < 0.90` are flagged for human review.

### 3. Source Attribution

Ensures every claim can be traced back through a chain of evidence to its original source.

#### Attribution Chain

```
LLM Claim ("Revenue declined 8.2% due to lower Enterprise volume")
  └─→ Assertion(id="bridge_4100_volume", value="-280000")
        └─→ EvidenceItem(source="bridge_analysis", record_id="4100", field="volume_effect")
              └─→ BridgeAnalysis(account_id="4100")
                    ├─→ Variance(account_id="4100", variance_amount=-450000)
                    │     ├─→ Actual(account_id="4100", amount=5850000)
                    │     └─→ Budget(account_id="4100", amount=6300000)
                    └─→ MaterialityAssessment(account_id="4100", tier="CRITICAL")
```

#### Attribution Requirements

| Element | Requirement |
|---------|-------------|
| **Every assertion** | Must have ≥ 1 evidence ID |
| **Every evidence ID** | Must resolve to a captured evidence item |
| **Every bridge claim** | Must reference a bridge decomposition component |
| **Every materiality claim** | Must reference the materiality assessment |
| **Recommendations** | Must cite ≥ 1 assertion ID plus additional supporting evidence |

#### Trace ID Format

All evidence items use traceable identifiers:

| Prefix | Source | Example |
|--------|--------|---------|
| `actual:` | Actuals table | `actual:4100:2025-03` |
| `budget:` | Budget table | `budget:4100:2025-03:v2` |
| `variance:` | Variance engine | `variance:4100:2025-03` |
| `bridge:` | Bridge analysis | `bridge:4100:price` |
| `materiality:` | Materiality engine | `materiality:4100:2025-03` |
| `forecast:` | Forecast table | `forecast:4100:2025-04:base` |
| `driver:` | Driver data | `driver:headcount:2025-03` |

### 4. Confidence Threshold Enforcement

Enforces minimum confidence levels for different types of claims.

#### Confidence by Output Type

| Output Type | Minimum Confidence | Action Below Threshold |
|-------------|-------------------|----------------------|
| **Numeric assertion** | 0.70 | Reject assertion, flag as degraded |
| **Comparative assertion** | 0.60 | Reject, mark as low confidence |
| **Causal assertion** | 0.50 | Downgrade to "hypothesis" |
| **Recommendation** | 0.60 | Route for human review |
| **Commentary section** | 0.70 overall | Flag section for review |

#### Confidence Decay

Confidence decreases as the chain from evidence to claim grows longer:

| Chain Length | Confidence Multiplier |
|-------------|---------------------|
| Direct (evidence → claim) | 1.0x |
| One hop (evidence → assertion → claim) | 0.9x |
| Two hops (evidence → analysis → assertion → claim) | 0.8x |
| Three+ hops | 0.7x |

This decay reflects that claims relying on longer reasoning chains are more susceptible to error.

## Retry Logic

When hallucination detection fails a section:

### Level 1: Soft Failure (Confidence 0.50 - 0.69)

- The section is re-generated with a single additional pass.
- The re-generation prompt includes the specific hallucination flags.
- If the re-generated section passes, it is accepted with a confidence penalty (-0.1).
- If it fails again, the section is downgraded to "low confidence" status.

### Level 2: Hard Failure (Confidence < 0.50, or Contradiction Detected)

- The section is **not re-generated automatically**.
- The failure is logged with the specific hallucination details.
- The section is replaced with a placeholder: "This section could not be reliably generated due to data quality concerns. Please review the underlying data."
- A degraded mode flag (`HALLUCINATION_DETECTED`) is raised.
- Human review is required to clear the degraded mode.

### Retry Limits

| Scenario | Max Retries | Action on Exhaustion |
|----------|-------------|---------------------|
| Commentary section | 2 | Replace with placeholder |
| Recommendation | 1 | Route for human review |
| Bridge analysis (deterministic) | 0 | Never retried — deterministic outputs are not re-generated |
| Assertion | 0 | Assertions are never from LLM — hard failure means assertion store corruption |

## Edge Cases

### Valid but Surprising Claims

Some legitimate claims may appear to be hallucinations (e.g., "Revenue increased 200% due to a one-time acquisition"). Detection handles this by:

1. Cross-referencing against the known risks list (acquisition should be documented).
2. Allowing one-time exceptions with documented business context.
3. Requiring the claim to include a qualifying note (e.g., "due to one-time acquisition").

### Ambiguous Evidence

When evidence is available but ambiguous (e.g., partial-period data):

1. The claim is checked against available (not total) evidence.
2. A data quality annotation is added to the claim.
3. Confidence is proportionally reduced based on data completeness.

### Multiple Sources with Conflicting Values

If two evidence sources provide different values for the same metric:

1. The system compares both evidence confidence scores.
2. The higher-confidence source is used as the reference.
3. The conflict is noted in the data quality report.
