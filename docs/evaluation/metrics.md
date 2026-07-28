# Evaluation Metrics

## Purpose

The **Evaluation Metrics** framework measures the quality, reliability, and performance of the FinSight pipeline. These metrics are tracked across every pipeline run, aggregated over time, and used to:

- Detect regressions in pipeline output quality.
- Validate improvements to the assertion, commentary, and recommendation engines.
- Provide visibility into system health for operations and product teams.
- Establish benchmark targets for release readiness.

## Metric Definitions

### 1. Grounding Score

**Definition**: The percentage of LLM-generated claims that have at least one supporting evidence source.

```
Grounding Score = Grounded Claims / Total Claims × 100
```

**Measurement**:

- Each claim in a commentary section is checked against the assertion store.
- A claim is "grounded" if its `cited_data_points` field contains at least one valid evidence ID.
- Claims about entity names, period identifiers, and structural metadata (e.g., "This analysis covers Acme Corp for March 2025") are exempt from grounding requirements.

**Target**: ≥ 95%

**Why it matters**: Low grounding scores indicate hallucination risk — the LLM is making claims it cannot support. This is the primary quality metric for the commentary pipeline.

---

### 2. Evidence Coverage

**Definition**: The percentage of material variance dollar amount that is explained by collected evidence.

```
Evidence Coverage = Sum of Explained Variance ($) / Total Material Variance ($) × 100
```

**Measurement**:

- For each material variance, the bridge analysis determines how much of the variance is decomposed into components.
- "Explained" variance is the sum of bridge component amounts for material variances.
- "Total" variance is the sum of all material variance amounts.
- Variances with no bridge decomposition (cost accounts without flags, or data gaps) count as unexplained.

**Target**: ≥ 90%

**Why it matters**: Low evidence coverage means root causes are not understood — the commentary will be shallow and recommendations will be poorly supported.

---

### 3. Hallucination Rate

**Definition**: The percentage of claims that are unsupported or contradicted by evidence.

```
Hallucination Rate = Hallucinated Claims / Total Claims × 100
```

**Measurement**:

- Hallucination detection (see **[guardrails/hallucination.md](../guardrails/hallucination.md)**) labels each claim as:
  - **Supported**: Claim is consistent with evidence (passes contradiction + verification).
  - **Unsupported**: Claim cannot be verified (no matching evidence).
  - **Contradicted**: Claim directly contradicts evidence.
- Only **contradicted** and **unsupported** claims count toward hallucination rate.
- Claims labeled "unsupported" due to evidence gaps in upstream data are counted at half weight (the gap originated in data quality, not the LLM).

**Target**: < 5% (overall), < 1% (direct contradictions only)

**Why it matters**: Hallucinations erode trust in the entire system. The target of < 5% ensures that the vast majority of commentary is reliable.

---

### 4. Schema Compliance

**Definition**: The percentage of structured outputs that pass Pydantic schema validation on first attempt.

```
Schema Compliance = Valid Outputs / Total Outputs × 100
```

**Measurement**:

- Every run produces structured outputs: `Variance`, `MaterialityAssessment`, `Assertion`, `CommentarySection`, `ActionItem`, and response payloads.
- Schema compliance is measured at the output serialization point (before the response is sent to the API consumer).
- Schema failures from the deterministic pipeline (variance engine, materiality engine, bridge analysis) are **hard failures** — they indicate a bug.
- Schema failures from the LLM (structured output parsing) are **soft failures** — they indicate parsing or prompt issues.

**Target**: 100% (deterministic pipeline), ≥ 99% (LLM-generated outputs)

**Why it matters**: Schema compliance ensures that downstream consumers (API clients, frontends, integrations) always receive well-formed data.

---

### 5. Recommendation Quality

**Definition**: Precision and recall of generated recommendations compared to a held-out judgment set.

#### Precision

```
Precision = True Positive Recommendations / (True Positive + False Positive) × 100
```

The proportion of generated recommendations that are correct and actionable.

#### Recall

```
Recall = True Positive Recommendations / (True Positive + False Negative) × 100
```

The proportion of actual actionable insights that were captured as recommendations.

**Measurement**:

- A held-out evaluation dataset is maintained with known-valid recommendations for historical periods.
- Each pipeline run's recommendations are compared against this dataset.
- **True positive**: Recommendation matches a known-valid recommendation.
- **False positive**: Recommendation was generated but is not valid.
- **False negative**: Known-valid recommendation exists but was not generated.

**Targets**:

| Metric | Target |
|--------|--------|
| Precision | ≥ 85% |
| Recall | ≥ 80% |
| F1 Score | ≥ 82% |

**Why it matters**: Low precision means the system generates too many false alarms (noise). Low recall means it misses legitimate issues (gaps).

---

### 6. Consistency

**Definition**: The degree to which the pipeline produces the same output for the same inputs.

```
Consistency = 1 - (Variance in Outputs / Expected Output Range)
```

**Measurement**:

- The same period is analyzed twice (with the same input data).
- The two outputs are compared for:
  - **Assertion identity**: Same set of assertions with same values.
  - **Materiality decisions**: Same variances flagged as material.
  - **Recommendation overlap**: Same recommendations generated (≥ 90% overlap).
  - **Commentary similarity**: Sections cover same topics (semantic similarity ≥ 0.85).
- Deterministic outputs (variances, materiality, bridge) must be **identical** across runs.
- LLM-generated outputs (commentary) may vary in phrasing but must agree on facts.

**Targets**:

| Component | Consistency Target |
|-----------|-------------------|
| Deterministic pipeline | 100% |
| Assertions (LLM-extracted) | ≥ 95% |
| Recommendations | ≥ 90% |
| Commentary (semantic) | ≥ 85% |

**Why it matters**: Inconsistency erodes trust. Users should be able to re-run the same analysis and get the same answers.

---

### 7. Latency Budget

**Definition**: The P95 response time for each pipeline endpoint, measured from API request receipt to response delivery.

#### Endpoints

| Endpoint | Description | P95 Target |
|----------|-------------|------------|
| `POST /pipeline/run` | Full pipeline execution (sync mode) | < 30s |
| `POST /pipeline/execute` | Truth + render execution | < 60s |
| `POST /pipeline/async-run` | Async pipeline submission | < 2s (ack only) |
| `GET /pipeline/result/{id}` | Pipeline result retrieval | < 1s |
| `POST /actions/create` | Action item creation | < 2s |
| `GET /commentary/{period}` | Commentary retrieval | < 3s |

#### Measurement

- Latency is measured at the API gateway level (wall-clock time).
- P95 means 95% of requests complete within the target time.
- Cache hits are excluded from latency measurement (only cache misses count).
- LLM inference time is the largest component of total latency for the execute endpoint.

**Targets**: See endpoint table above.

**Why it matters**: Users expect responsive feedback. Excessive latency degrades the user experience and reduces the frequency of analysis runs.

## Dashboard

Aggregated metrics are reported on the following cadence:

| Metric | Aggregation | Reporting Cadence |
|--------|-------------|-------------------|
| Grounding Score | Per-run, per-tenant, system-wide | Per-run (detailed), weekly (trend) |
| Evidence Coverage | Per-run, per-tenant | Per-run |
| Hallucination Rate | Per-run, rolling 7-day | Per-run (alerts), weekly (trend) |
| Schema Compliance | Rolling 7-day | Daily |
| Recommendation Quality | Per evaluation dataset version | Per model update |
| Consistency | Per evaluation suite run | Per release candidate |
| Latency Budget | Per-endpoint, rolling 7-day | Daily (p95), weekly (p99) |

## Degradation Response

When metrics fall below target thresholds:

| Metric | Below Target | Action |
|--------|-------------|--------|
| Grounding Score | < 85% | Pipeline downgraded — commentary replaced with assertion data dump |
| Hallucination Rate | > 10% | LLM model or prompt evaluated for update |
| Schema Compliance | < 98% (LLM) | Structured output parsing prompt updated |
| Latency | > 2x P95 target | Investigate LLM provider, caching, or parallelism |
| Consistency | < 80% | Deterministic pipeline frozen — LLM outputs disabled |

## Tooling

All metrics are:

1. **Logged** to the application metrics store at the end of each pipeline run.
2. **Visualized** in operational dashboards for real-time monitoring.
3. **Alerted** on when threshold violations occur (e.g., grounding score drops below 85%).
4. **Tracked** over time to identify trends and regressions.
