# ADR-014: Minimal ML Strategy — Lock Three MVP Models (M1–M3) with BGE Embeddings

**Status:** Accepted  
**Date:** 2026-08-03  
**Deciders:** Architecture Team (decision-maker confirmation of decisions D5, D6)  

---

## Context

`docs/09-platform/mlops.md` inventories **six candidate models** (vendor risk XGBoost, payment anomaly IF, late payment LightGBM, cash-flow LightGBM, duplicate invoice, duplicate vendor HDBSCAN). Building and operating all six for MVP would spread evaluation, monitoring, and retraining too thin on CPU-only hardware (Ryzen 5 3600 in Docker; no GPU). The embedding model for duplicate detection was also unpinned.

Decision-maker (D5): lock **exactly 3 models** for MVP — **M1 Anomaly Detection (Isolation Forest), M2 Cash Forecast (LightGBM), M3 Duplicate Invoice (hybrid)**. Vendor risk / late payment / duplicate vendor are **stretch, not MVP**.

Decision-maker (D6 — override): **BAAI/bge-small-en-v1.5** (or bge-base-en-v1.5) instead of all-MiniLM-L6-v2 — better retrieval quality, strong open benchmarks, CPU-friendly, excellent with pgvector.

## Decision

### 1. MVP model set is exactly three (D5)

All CPU-only, all consumed through the `RiskProvider` protocol via the Inference Registry (`finance/ml/providers/`, `finance/ml/registry.py`):

| # | Model | Problem type | Algorithm |
|---|-------|--------------|-----------|
| **M1** | **Anomaly Detection** | Unsupervised anomaly | **Isolation Forest** on engineered features (amount Z-score, inter-payment interval, hour-of-day entropy) |
| **M2** | **Cash Flow Forecast** | Time-series regression | **LightGBM** with lag features (28d, 56d, 90d, YoY) + calendar regressors |
| **M3** | **Duplicate Invoice** | Hybrid | Rules first (exact vendor+amount) → embedding cosine similarity (pgvector) + amount proximity → Isolation Forest outlier rejection |

This numbering (**M1 = Anomaly, M2 = Cash Forecast, M3 = Duplicate Invoice**) is authoritative and supersedes earlier drafts that ordered M1 = Cash Forecast.

### 2. Stretch goals are NOT MVP

Vendor risk (XGBoost), late payment (LightGBM), and duplicate vendor (HDBSCAN) remain **candidate models only**. They are deferred, feature-flag gated (`features.ml`), post-MVP, and never default-on. `mlops.md`'s six-model inventory is superseded for MVP scope; the three deferred models remain documented for the stretch roadmap.

### 3. Embedding model (D6)

Use **BAAI/bge-small-en-v1.5** as the default embedding model (with **BAAI/bge-base-en-v1.5** as the larger alternative where retrieval quality justifies the size), via `sentence-transformers`, pinned in `ModelMetadata.framework_version`.

Rationale versus all-MiniLM-L6-v2:

- **Better retrieval quality.** bge-small-en-v1.5 leads MiniLM on MTEB retrieval/STS benchmarks with comparable latency.
- **CPU-friendly.** bge-small (~33M parameters, 384-dim) runs comfortably on the CPU-first target; bge-base (768-dim) remains viable.
- **Excellent pgvector fit.** Fixed-size dense vectors map directly to pgvector `vector` columns (ADR-013) with RLS + `tenant_id` filtering.
- **Strong open benchmarks and wide adoption.**

## Consequences

### Positive

- **Focus.** Three models to build, evaluate (`predictive_models` datasets), monitor, and retrain — not six.
- **Lower compute and ops burden** on CPU-only hardware.
- **Stretch models stay viable as a roadmap**, feature-flag gated, without MVP risk.
- **BGE embeddings materially improve duplicate-invoice retrieval** and are a better foundation for any future RAG (still disabled by default — ADR-015).

### Negative

- **Fewer predictive capabilities at MVP**: no vendor risk, late-payment, or duplicate-vendor scoring until stretch.
- **BGE model download + pinning** adds a deployment artifact; the model version must be frozen for reproducibility.
- **Embedding inference adds latency** to M3 at batch time (CPU-bound).
- **All-MiniLM references in earlier docs are superseded**; readers must follow BGE.

## Compliance

1. The Inference Registry registers exactly M1–M3 for MVP; stretch models (`vendor_risk`, `late_payment`, `duplicate_vendor`) are not registered by default.
2. The embedding model is BAAI/bge-small-en-v1.5 (default) or bge-base-en-v1.5; recorded in `ModelMetadata.framework_version` together with the `sentence-transformers` version.
3. All three models are CPU-only and consumed via `RiskProvider`; agents never import ML packages.
4. Predictive evaluation datasets cover exactly M1–M3 for MVP.
5. Stretch models are feature-flag gated (`features.ml`) and never default-on.

**References:** `docs/09-platform/mlops.md` (six-model inventory — superseded on MVP scope), `docs/07-ai-runtime/ai-architecture-guide.md` §5, ADR-013 (pgvector embeddings), plan v3 (CPU-first, scikit-learn optional).
