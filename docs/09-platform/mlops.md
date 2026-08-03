# MLOps — Predictive Modelling Layer

**Layer classification:** Predictive modelling — orthogonal operational discipline  
**Layer owner:** Finance ML Engineering  
**Codebase path:** `finance/ml/` (proposed)  
**Status:** Greenfield capability (no ML models in current codebase)

---

## Purpose

MLOps owns the predictive modelling layer of the Finance Operations OS. This layer fills analytical gaps that deterministic rules cannot cover — detecting anomalous payments, scoring vendor risk, flagging duplicate invoices, predicting late payments, and forecasting cash flows. Every model exposes the same `RiskProvider` protocol so that agents consume predictions without knowing whether the provider is a rule set, a decision tree, or a time-series model.

This layer is **strictly optional**. The agent pipeline runs without it. ML enriches decisions where pattern recognition beats threshold logic.

### What MLOps owns

| Capability | Detail |
|-----------|--------|
| **Model training** | Classical ML on CPU: scikit-learn, XGBoost, LightGBM, CatBoost |
| **Feature engineering** | Polars transformations from tabular finance data |
| **Inference** | `RiskProvider` protocol; `InferenceRegistry` for model lifecycle |
| **Model registry** | Versioned predictors with metadata (schema, training window, metrics) |
| **Model monitoring** | Prediction drift, feature drift, data drift |
| **Offline evaluation** | Precision, recall, RMSE, MAPE on golden datasets |
| **Retraining cycles** | Scheduled (weekly/monthly) or drift-triggered |

### What MLOps does NOT own

- **LLM model management** — belongs to LLMOps (prompt versioning, LiteLLM routing, Langfuse tracing)
- **Data pipelines** — belongs to DataOps (ingestion, validation, quality checks via `finance/ingestion/` and `finance/validation/`)
- **Agent orchestration** — belongs to AgentOps (LangGraph state machines, routing, HITL checkpoints)

---

## When to Use ML (and When Not To)

The FinSight architecture is **deterministic-first**. Every financial number — variance, KPI, materiality, bridge decomposition — is computed by pure Python engines using `decimal.Decimal` arithmetic. This is not negotiable. The PRD (NFR-02) mandates that identical inputs produce identical outputs for all finance engine functions.

ML enters the picture only where deterministic rules cannot produce the right answer:

### When ML adds value

| Situation | Why rules fail | ML approach |
|-----------|---------------|-------------|
| **Duplicate invoice detection** | "Same vendor, same amount" catches exact dupes, but not split invoices or slightly altered amounts | Similarity scoring (cosine + amount proximity) with Isolation Forest outlier rejection |
| **Vendor risk scoring** | Rules can flag "new vendor > $50K" but miss subtle patterns (vendor-of-convenience clusters, sudden change in payment terms) | Gradient-boosted classifier on vendor metadata + payment history features |
| **Payment anomaly detection** | Dollar thresholds produce false positives on legit large payments and miss small anomalous patterns | Isolation Forest on amount × frequency × time-of-day feature space; XGBoost for triage |
| **Late payment prediction** | "Invoice is 30 days overdue" is descriptive, not predictive | Binary classifier trained on payment history, vendor category, seasonality, and macro indicators |
| **Cash-flow forecasting** | Simple moving averages fail on cyclical or event-driven patterns | Gradient-boosted time-series (LightGBM with lag features) or Prophet for interpretability |

### When ML is the wrong tool

| Situation | Why | Alternative |
|-----------|-----|-------------|
| **Variance computation** | Requires exact arithmetic; ML introduces error | Deterministic `VarianceEngine` (already built) |
| **Materiality assessment** | Policy-based rules with account-code matching and tiered thresholds | `MaterialityEngine` with `MaterialityConfig` (already built) |
| **KPI calculation** | Declarative formulas with topological dependency resolution | `FormulaRegistry.evaluate_all()` (already built) |
| **Bridge decomposition** | Price/volume/mix decomposition is algebraic | `BridgeDecomposition` in `finance/driver_engine/` (already built) |
| **Numeric claim validation** | Every monetary figure must cross-check against source evidence | `ClaimValidator` with exact match and tolerance verification (already built) |
| **Small-n decisions** | < 100 historical records; any model would overfit | Rules + business logic + agent judgment |

**Rule of thumb:** If a human analyst could write a deterministic rule that matches their judgment > 95% of the time, implement the rule. ML is for patterns that are real but inexpressible as threshold logic.

---

## Model Candidates

All models run on CPU. The target hardware is a Ryzen 5 3600 in Docker — no GPU required. Training data is tabular (Polars DataFrame sourced from `finance/ingestion/`), typically 10K–500K rows per use case.

| Model | Problem Type | Algorithm | Why This Algorithm | Training Data | Expected Volume |
|-------|-------------|-----------|-------------------|---------------|-----------------|
| **Duplicate invoice detector** | Unsupervised anomaly + pairwise similarity | Isolation Forest + cosine similarity on TF-IDF vendor/description text | Handles unseen invoice patterns; no labelled data required | Invoice header + line items from GL and vendor feeds | Batch, per ingestion cycle |
| **Vendor risk scorer** | Binary classification (risk / no-risk) | XGBoost with class-weight tuning | Handles missing vendor metadata well; built-in handling of categorical features | Vendor master + payment history + external risk feeds | Weekly retraining, ~50–200K vendors |
| **Payment anomaly detector** | Unsupervised anomaly | Isolation Forest on engineered features (amount Z-score, inter-payment interval, hour-of-day entropy) | Lightweight, interpretable via feature contributions; no labels needed | Payment transactions (from `Actual` table in PostgreSQL) | Near-real-time per payment batch |
| **Late payment classifier** | Binary classification | LightGBM with early stopping | Faster than XGBoost at this data volume; native categorical support; handles class imbalance | Invoice payment history + vendor segment + calendar features | Daily inference, ~5–20K invoices/day |
| **Cash-flow forecaster** | Time-series regression | LightGBM with lag features (28d, 56d, 90d, YoY) + calendar regressors | Outperforms ARIMA and Prophet on tabular time-series with strong exogenous signals; no GPU needed | Daily cash position from `Actual` table + forecast from `forecast_engine/` | Weekly retraining; daily inference rolling 13-week window |
| **Duplicate vendor detector** | Unsupervised clustering | HDBSCAN on vendor name embeddings (CountVectorizer + SVD) + payment fingerprint | Discovers vendor clusters without predefined thresholds; handles typos and abbreviations | Vendor master from procurement and AP systems | Monthly retraining (vendor master is slow-changing) |

**Implementation note:** All monetary features must be derived from `Decimal`-typed source columns and converted to `float` only at the model boundary. Feature pipelines should validate that input monetary columns are `Decimal` before conversion, following the `MoneyDecimal` pattern established in `finance/domain/_types.py`.

---

## Inference Registry

Every ML model implements the `RiskProvider` protocol — a single interface that agents call without knowing whether the provider is a rule evaluator, a trained model, or a hybrid. This is the same pattern that the existing evaluation framework uses for `ToolResult` and `Assertion` interfaces.

### Protocol Definition

```python
# finance/ml/protocol.py (proposed)

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from shared.models.assertions import Assertion  # existing typed claim model


@runtime_checkable
class RiskProvider(Protocol):
    """Interface for risk evaluation — rules, ML, or hybrid.

    Agents call ``evaluate()`` without knowing the implementation.
    This is the same protocol pattern used by ``ToolResult`` across
    the ingestion and evidence layers.
    """

    model_id: str
    """Unique model identifier — matches model registry entry."""

    version: str
    """Semantic version of the model or rule set."""

    def evaluate(self, context: dict[str, Any]) -> RiskEvaluation:
        """Score a single entity (vendor, invoice, transaction).

        Args:
            context: Feature dictionary for the entity. Keys must match
                     the feature schema registered in the model metadata.
        Returns:
            RiskEvaluation with score, evidence, and metadata.
        """
        ...

    def metadata(self) -> ModelMetadata:
        """Return model metadata: schema, training window, metrics."""
        ...


class RiskEvaluation(BaseModel):
    """Typed output of a RiskProvider evaluation.

    Mirrors the ``Assertion`` model structure — every ML judgment
    carries evidence and confidence, just like deterministic assertions.
    """

    provider_id: str
    entity_id: str
    score: float  # 0.0 (low risk) to 1.0 (high risk)
    confidence: float  # model confidence in this prediction
    evidence: list[dict[str, Any]]  # feature contributions, SHAP values, etc.
    metadata: dict[str, Any]  # inference latency, model version, data freshness
    evaluated_at: datetime
```

### Inference Registry

```python
# finance/ml/registry.py (proposed)

class InferenceRegistry:
    """Registry of available RiskProvider instances.

    Usage::

        registry = InferenceRegistry()
        registry.register("vendor_risk", xgboost_provider_v2)
        registry.register("payment_anomaly", isolation_forest_provider)

        # Agent calls this — no knowledge of the provider type
        result = registry.get("vendor_risk").evaluate({"vendor_id": "V12345"})
    """

    def __init__(self) -> None:
        self._providers: dict[str, RiskProvider] = {}

    def register(self, name: str, provider: RiskProvider) -> None:
        self._providers[name] = provider

    def get(self, name: str) -> RiskProvider:
        if name not in self._providers:
            raise KeyError(f"Unknown provider: {name}")
        return self._providers[name]

    def list_providers(self) -> list[dict[str, str]]:
        return [
            {"name": name, "model_id": p.model_id, "version": p.version}
            for name, p in self._providers.items()
        ]

    def evaluate_all(
        self, contexts: dict[str, dict[str, Any]]
    ) -> dict[str, RiskEvaluation]:
        """Batch evaluate multiple providers.

        Useful for agent workflows that need multiple risk signals
        before making a decision (e.g., check vendor risk AND
        payment anomaly before routing for human review).
        """
        return {
            name: self._providers[name].evaluate(ctx)
            for name, ctx in contexts.items()
            if name in self._providers
        }
```

### Registry Integration with Agent Pipeline

The registry is instantiated at startup (same pattern as `FormulaRegistry` in `finance/formula_engine/formula_registry.py`) and injected into agent tool context. Agents call providers through the registry, not directly:

```
Agent Tool Context
    │
    ├── InferenceRegistry.get("vendor_risk")
    ├── InferenceRegistry.get("payment_anomaly")
    │
    ▼
RiskProvider.evaluate(context)
    │
    ├── RuleProvider    → deterministic threshold evaluation
    ├── MLProvider      → model.predict(feature_vector)
    └── HybridProvider  → rules first, ML on edge cases
```

The agent never imports `xgboost`, `sklearn`, or any ML dependency. The only coupling is through the `RiskProvider` protocol, which lives in `finance/ml/protocol.py` — the boundary layer that `finance/` may depend on.

---

## Hybrid Decision Pipeline

No model makes autonomous decisions. Every ML prediction passes through a three-stage hybrid pipeline before reaching the agent:

```
  ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────────┐
  │  Rules   │ ──▶ │    ML    │ ──▶ │ Business │ ──▶ │ Agent        │
  │ (first)  │     │ (second) │     │  Rules   │     │ Decision     │
  └──────────┘     └──────────┘     └──────────┘     └──────────────┘
```

### Stage 1 — Deterministic Rules (gate)

Fast, zero-cost rules that short-circuit ML for clear-cut cases:

```python
# Pseudocode for vendor risk gating

def vendor_risk_gate(vendor: Vendor) -> str | None:
    """Return 'low', 'high', or None (needs ML)."""
    if vendor.is_blocklisted:
        return "high"          # → escalation, no ML needed
    if vendor.tenure_years > 5 and vendor.total_paid < 100_000:
        return "low"           # → auto-approve, no ML needed
    return None                # → proceed to ML
```

### Stage 2 — ML Model (predict)

Only ambiguous cases reach the model:

```python
def vendor_risk_ml(vendor: Vendor, registry: InferenceRegistry) -> RiskEvaluation:
    gate = vendor_risk_gate(vendor)
    if gate is not None:
        return RiskEvaluation(score=0.0 if gate == "low" else 1.0, ...)
    provider = registry.get("vendor_risk")
    return provider.evaluate(vendor.to_feature_dict())
```

### Stage 3 — Business Rules (override)

Business rules applied to the ML output before the agent sees it:

```python
def apply_business_overrides(eval: RiskEvaluation, vendor: Vendor) -> RiskEvaluation:
    """Override ML prediction when business context demands it."""
    if vendor.is_government_entity and eval.score > 0.7:
        eval.score *= 0.5     # government entities are slow payers but not risky
    if vendor.is_intercompany and eval.score > 0.3:
        eval.score = 0.0      # intercompany transactions are zero-risk
    return eval
```

### Stage 4 — Agent Decision

The agent receives the final `RiskEvaluation` alongside deterministic assertions from the existing pipeline. It uses both to decide routing, escalation, or auto-approval — consistent with the autonomy policy matrix in the PRD (§9).

**Why three stages?** Each stage catches different failure modes:
- **Rules** catch edge cases the model never saw in training
- **ML** catches patterns the rule-writer never thought of
- **Business rules** encode institutional knowledge that neither rules nor ML capture
- **Agent** applies policy context (materiality, confidence, HITL requirements)

---

## Evaluation Strategy

ML model evaluation extends the existing golden dataset framework (`finance/evaluation/`) with model-specific metrics. The same `EvaluationRunner` and `Comparator` infrastructure is reused — ML eval produces `EvaluationReport` records that feed into the same regression detection pipeline.

### Offline Metrics

| Model | Primary Metric | Secondary Metrics | Evaluation Dataset |
|-------|---------------|-------------------|--------------------|
| Duplicate invoice detector | Precision@10 | Recall, F1, pairwise accuracy | 5,000 labelled invoice pairs (synthetic + hand-labelled) |
| Vendor risk scorer | AUC-ROC | Precision, Recall, F1, confusion matrix at threshold 0.7 | 20,000 vendors with known outcomes (payment defaults, fraud flags) |
| Payment anomaly detector | Precision@K (K=50) | Recall@K, false-positive rate per period | 100K payment transactions with injected anomalies |
| Late payment classifier | F1 score | Precision, Recall, AUC-PR, log loss | 50K invoices with payment timing labels |
| Cash-flow forecaster | MAPE (13-week horizon) | RMSE, MAE, bias (signed error), coverage of prediction intervals | 5 years of daily cash positions; rolling window evaluation |
| Duplicate vendor detector | Adjusted Rand Index | Homogeneity, completeness, V-measure | 10K vendor records with known duplicate clusters |

### Golden Dataset Integration

Model evaluation datasets follow the same structure as existing golden datasets in `finance/evaluation/datasets/`. A new category `predictive_models` is added:

```
finance/evaluation/datasets/
├── financial_logic/        # 7 datasets (existing)
├── data_quality/           # 5 datasets (existing)
├── runtime_behaviour/      # 4 datasets (existing)
├── governance/             # 4 datasets (existing)
└── predictive_models/      # NEW: 6 datasets (one per model)
    ├── duplicate_invoice.json
    ├── vendor_risk.json
    ├── payment_anomaly.json
    ├── late_payment.json
    ├── cash_flow_forecast.json
    └── duplicate_vendor.json
```

Each predictive dataset follows the same `GoldenDataset` schema:

```json
{
  "metadata": {
    "id": "vendor_risk_001",
    "name": "Vendor Risk Scoring — Baseline",
    "category": "predictive_models",
    "description": "20 vendors with known risk outcomes, covering all risk tiers",
    "tags": ["vendor_risk", "classification"],
    "difficulty": "intermediate"
  },
  "input": {
    "query": "Evaluate vendor risk",
    "context": {
      "vendors": [
        {"vendor_id": "V001", "tenure_years": 8, "category": "software", ...}
      ]
    }
  },
  "expected": {
    "output": {
      "predictions": [
        {"vendor_id": "V001", "risk_score": 0.12, "risk_tier": "low"},
        {"vendor_id": "V008", "risk_score": 0.89, "risk_tier": "high"}
      ]
    }
  }
}
```

### ML-Specific Evaluation Metrics

New metric classes in `finance/evaluation/metrics.py` (extending the existing pattern):

```python
class PredictionAccuracy:
    """Fraction of predictions matching expected risk tier.

    Extends the ``VarianceAccuracy`` pattern to classification output.
    Matching is by ``entity_id`` and predicted tier.
    """

    @staticmethod
    def compute(expected: list[dict[str, Any]], actual: list[dict[str, Any]]) -> float:
        if not expected:
            return 0.0
        matched = 0
        for exp in expected:
            for act in actual:
                if exp.get("entity_id") == act.get("entity_id"):
                    if exp.get("risk_tier") == act.get("risk_tier"):
                        matched += 1
                    break
        return matched / len(expected)


class ForecastError:
    """MAPE between forecast and actual values.

    Score is 1.0 - min(MAPE / tolerance, 1.0), so higher is better,
    consistent with all other metric classes.
    """

    def __init__(self, tolerance: float = 0.15) -> None:
        self._tolerance = tolerance

    def compute(self, expected: list[dict], actual: list[dict]) -> float:
        mape = _calculate_mape(expected, actual)
        return max(0.0, 1.0 - (mape / self._tolerance))
```

### Regression Detection for Models

The existing `Comparator` and `RegressionRunner` from `finance/evaluation/regression.py` detect model regressions automatically. A typical CI check:

```
vendor_risk_001:  AUC-ROC 0.94 → 0.91  (delta -0.03)
  break threshold: -0.02
  → REGRESSION_DETECTED
```

Retraining is prevented from deploying if the regression check fails against the baseline.

---

## Operational Metrics

ML models publish operational metrics through the same channels as the rest of the system — structured JSON via API, captured by OpenTelemetry, and surfaced in the evaluation dashboard.

### Model Health Metrics

| Metric | Description | Collection | Alert Threshold |
|--------|-------------|-----------|-----------------|
| **Prediction drift** | PSI (Population Stability Index) of score distribution vs training | Per inference batch | PSI > 0.1 |
| **Feature drift** | Per-feature KS statistic or JS divergence | Per inference batch | Any feature drift p < 0.01 |
| **Data drift** | Row count, null rate, type violations in inference requests | Per inference batch | Row count < 80% of expected, null rate > 5% |
| **Inference latency** | P50 / P95 / P99 of `evaluate()` call duration | Per request (captured via OpenTelemetry) | P95 > 500ms |
| **Throughput** | Predictions per second | Rolling 5-minute window | < 10 req/s (should be 100+ on CPU) |
| **Model freshness** | Hours since last training | Cron check | > 2x expected retraining interval |
| **Error rate** | Fraction of `evaluate()` calls raising exceptions | Per request | > 0.1% |

### Retraining Triggers

| Trigger | Threshold | Action |
|---------|-----------|--------|
| Scheduled | Weekly (vendor models), daily (cash-flow) | Retrain on latest data; deploy if regression check passes |
| Prediction drift | PSI > 0.1 | Flag for review; retrain if drift persists 3 consecutive batches |
| Feature drift | KS p < 0.01 for any feature | Investigate feature pipeline; retrain if data quality confirmed |
| Performance regression | AUC-ROC drop > 0.02 vs baseline | Rollback to previous model version; retrain with expanded dataset |
| New data source | Connector added in `finance/ingestion/` | Manual trigger: rebuild training set with new features |

### Model Registry Schema

```python
# finance/ml/registry.py (proposed)

class ModelMetadata(BaseModel):
    """Metadata for a registered model version.

    Follows the same structured-metadata pattern as
    ``DatasetMetadata`` in ``finance/evaluation/dataset.py``.
    """

    model_id: str
    version: str  # semver
    algorithm: str  # "xgboost", "isolation_forest", "lightgbm", etc.
    training_start: datetime
    training_end: datetime
    training_rows: int
    feature_count: int
    feature_names: list[str]
    target_column: str
    metrics: dict[str, float]  # {"auc_roc": 0.94, "f1": 0.87, ...}
    artifact_path: str  # filesystem or S3 path to serialised model
    framework_version: str  # "xgboost==2.1.0"
    deployed_at: datetime | None
    retired_at: datetime | None
```

---

## Deployment Path

### Phase 1 — Docker (Current)

All models run in the same Docker container as the backend. The `InferenceRegistry` is populated at startup:

```python
# pseudo-startup sequence

from finance.ml.providers import (
    XGBoostVendorRiskProvider,
    IsolationForestAnomalyProvider,
    LightGBMLatePaymentProvider,
)
from finance.ml.registry import InferenceRegistry

registry = InferenceRegistry()
registry.register("vendor_risk", XGBoostVendorRiskProvider.load_latest())
registry.register("payment_anomaly", IsolationForestAnomalyProvider.load_latest())
registry.register("late_payment", LightGBMLatePaymentProvider.load_latest())

# registry is injected into agent tool context at app startup
# (same pattern as engine injection in the existing codebase)
```

Model artifacts are stored on disk within the container (for development) or on a mounted volume (for production). The Ryzen 5 3600 runs all models with P95 inference latency under 50ms per prediction.

**Training** runs as a separate CLI command (not in the API container):

```bash
# Train all models and save artifacts to /app/models/
uv run python -m finance.ml.train_all

# Train a specific model
uv run python -m finance.ml.train --model vendor_risk --data-period 2026-06
```

### Phase 2 — Modal (Serverless Inference)

When the organisation needs elastic scaling (e.g., month-end close spikes), the same `RiskProvider` interface deploys to Modal with zero code changes:

```python
# deploy/modal_provider.py (proposed)

import modal

app = modal.App("finsight-ml")
image = modal.Image.debian_slim().pip_install(
    "scikit-learn", "xgboost", "lightgbm", "polars"
)


@app.cls(
    image=image,
    gpu=None,           # CPU inference — no GPU needed
    concurrency_limit=20,
    container_idle_timeout=300,
)
class ModalRiskProvider:
    """Modal-hosted RiskProvider. Same interface as the Docker version."""

    def __init__(self, model_name: str) -> None:
        from finance.ml.registry import InferenceRegistry
        self._provider = InferenceRegistry().get(model_name)

    def evaluate(self, context: dict) -> dict:
        result = self._provider.evaluate(context)
        return result.model_dump()
```

**Migration strategy:** The `InferenceRegistry` abstracts the deployment target. In Docker, it loads providers from disk. In Modal, the registry is a client that calls the remote Modal function. The agent code never changes.

```
Docker (Phase 1):
  registry.get("vendor_risk") → local XGBoost model in memory

Modal (Phase 2):
  registry.get("vendor_risk") → Modal function call (same protocol)
```

### Model Storage

| Environment | Artifact Location | Training Data |
|-------------|-------------------|---------------|
| Development | `models/` in Docker volume | Local CSV + seed data |
| Production (Docker) | Mounted volume `/app/models/` | PostgreSQL via `finance/ingestion/` |
| Production (Modal) | Modal volume or S3 | PostgreSQL (via VPN) or S3-parquet |

---

## File Structure (Proposed)

```
finance/ml/                    # NEW: ML module
├── __init__.py
├── protocol.py                # RiskProvider, RiskEvaluation, ModelMetadata
├── registry.py                # InferenceRegistry
├── providers/                 # Model implementations
│   ├── __init__.py
│   ├── base.py                # BaseMLProvider (serialisation, versioning)
│   ├── vendor_risk.py         # XGBoostVendorRiskProvider
│   ├── duplicate_invoice.py   # IsolationForest + similarity
│   ├── payment_anomaly.py     # IsolationForestAnomalyProvider
│   ├── late_payment.py        # LightGBMLatePaymentProvider
│   ├── cash_flow.py           # LightGBMCashFlowProvider
│   └── duplicate_vendor.py    # HDBSCAN clustering
├── features/                  # Feature engineering (Polars transforms)
│   ├── __init__.py
│   ├── vendor_features.py
│   ├── invoice_features.py
│   ├── payment_features.py
│   └── cash_flow_features.py
├── train_all.py               # CLI entry point for batch training
└── schemas.py                 # Pydantic schemas for training configs

tests/
├── unit/
│   └── ml/
│       ├── test_protocol.py
│       ├── test_registry.py
│       ├── test_vendor_risk.py
│       └── test_features.py
└── integration/
    └── ml/
        └── test_model_evaluation.py
```

### Dependency Rules

This module follows the same layered architecture as the rest of the codebase:

- `finance/ml/` depends on `shared/` (for base models, `MoneyDecimal`, `ToolResult`)
- `finance/ml/` may depend on `finance/evaluation/` (for `GoldenDataset`, `EvaluationRunner`)
- `finance/ml/` does NOT depend on `agents/` or `apps/`
- Third-party ML packages (`scikit-learn`, `xgboost`, `lightgbm`, `polars`) are optional dependencies — the `RiskProvider` protocol works without them
- Agents access ML through the `InferenceRegistry` only — no direct ML imports in agent code

---

## Relationship to Other Platform Layers

```
                    ┌────────────────────────┐
                    │       AgentOps          │
                    │  (calls RiskProvider    │
                    │   via InferenceRegistry)│
                    └──────────┬─────────────┘
                               │
                    ┌──────────▼─────────────┐
                    │        LLMOps           │
                    │  (separate — LLM        │
                    │   routing, prompts)     │
                    └──────────┬─────────────┘
                               │
                    ┌──────────▼─────────────┐
                    │        MLOps            │ ◄── YOU ARE HERE
                    │  (model training,       │
                    │   inference, monitoring)│
                    └──────────┬─────────────┘
                               │
                    ┌──────────▼─────────────┐
                    │       DataOps           │
                    │  (feature pipelines,    │
                    │   training data, drift) │
                    └──────────┬─────────────┘
                               │
                    ┌──────────▼─────────────┐
                    │      DevSecOps          │
                    │  (CI/CD, artifact       │
                    │   storage, infra)       │
                    └────────────────────────┘
```

**Key boundary:** MLOps owns model logic and inference. DataOps owns the feature pipelines that feed training and inference. The two layers coordinate through the `InferenceRegistry` and shared schemas — MLOps defines the feature schema, DataOps guarantees it is populated.

---

## References

- **Existing evaluation framework:** `finance/evaluation/` — `EvaluationRunner`, `Comparator`, `RegressionRunner`, golden datasets. ML eval extends this, does not replace it.
- **Existing typed assertions:** `shared/models/assertions.py` — the `Assertion` model pattern (typed, evidence-backed, confidence-scored) informs the `RiskEvaluation` model.
- **Existing deterministic engines:** `finance/formula_engine/`, `finance/variance_engine/`, `finance/driver_engine/` — these are the non-negotiable deterministic core. ML supplements them where rules cannot reach.
- **PRD non-goal §14:** "No custom ML model training" referred to fine-tuned LLMs, not classical ML on structured finance data. This document addresses the classical ML gap.
- **PRD §8 risk register:** "Model drift / performance regression" — Medium likelihood, Medium impact. Mitigated by continuous eval with regression detection (this document's evaluation strategy).