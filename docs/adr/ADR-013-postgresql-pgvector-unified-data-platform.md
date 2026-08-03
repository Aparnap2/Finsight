# ADR-013: PostgreSQL + pgvector Unified Data Platform — One Database, Same RLS, Same Backup

**Status:** Accepted  
**Date:** 2026-08-03  
**Deciders:** Architecture Team (decision-maker confirmation of decisions D3, D4)  

---

## Context

Two data-platform questions were open:

1. **Vector store (D3).** Plan v3 §4b (`docs/14-platform/implementation-plan.md`) locks "PostgreSQL 17 + RLS + pgvector"; `docs/09-platform/devsecops.md` docker-compose topology includes a **Qdrant** container (with `tenant_id` metadata filters, `qdrant_url` in settings, and a degraded mode when Qdrant is down). The two documents conflicted on where vector embeddings live.
2. **Feature store (D4).** `finance/feature_store/` is new; the plan locks Polars/DuckDB for data and Postgres for persistence but not the store layout. **Feast** was a candidate for feature serving.

Decision-maker: **pgvector.** Single DB: same transaction boundary, same RLS, same backup, simpler deployment. Qdrant explicitly out of MVP (only for billions of vectors / hybrid search). Feature store formalized: Offline = Parquet → DuckDB → training snapshots; Serving = Postgres materialized views → inference. Do **NOT** build Feast.

## Decision

### 1. Unified data platform on PostgreSQL 17 + pgvector (D3)

All transactional data, vector embeddings, materialized serving views, and audit data live in **one PostgreSQL instance with pgvector**:

- **Same transaction boundary.** Embedding writes and the source rows they describe commit atomically.
- **Same RLS.** Embeddings tables carry `tenant_id` and are protected by the same RLS policies (`app.tenant_id` session variable — see ADR-0001); retrieval filters by `tenant_id` at query time. Tenant A memory ≠ Tenant B memory.
- **Same backup.** One backup/restore story; no second datastore to operate.
- **Simpler deployment.** No Qdrant container in the MVP topology.
- **Qdrant is out of MVP.** Revisit only at billions-of-vectors scale or if hybrid vector + lexical search becomes a product requirement — a future decision, not a default.

### 2. Feature store: Offline/Serving two-plane design (D4)

Do not build Feast. Formalize the two-plane store:

- **Offline plane:** Parquet files → DuckDB → point-in-time **training snapshots** (Polars transforms, no leakage). `finance/feature_store/training.py` extracts training windows; snapshots are recorded in `ModelMetadata.training_start/end` so a model version can be rebuilt.
- **Serving plane:** Postgres **materialized views** → point-in-time inference features via `finance/feature_store/serving.py`. The same transforms as training, evaluated "as of" inference time; tenant-scoped by RLS.
- **Staleness:** per-feature-group `max_age` thresholds (vendor daily, cashflow hourly, invoice per batch, anomaly per batch) feed `DataQualityReport` freshness checks and the `STALE_SOURCE` degraded mode.

### 3. Execution Runtime: Backend ≠ Compute (compute-runtime rationale)

`apps/compute` is a **separate Execution Runtime** (FastAPI, separate Docker image and lifecycle) behind the Job Dispatcher (Dramatiq/Redis). The backend orchestrates and never manipulates dataframes; Python computes. Rationale:

- **Isolation.** Compute jobs run outside the API process; a runaway job cannot destabilize the web tier.
- **Security.** The dispatcher owns permissions/queue/retry/timeout; the runtime receives authorized datasets (storage paths `tenant/<id>/artifact/<version>/`), never raw files (plan v3 principle 7).
- **Scaling.** The execution tier scales independently of the API.
- **Deterministic execution.** Job-oriented (`POST /jobs` → 202 + `job_id` → `GET /jobs/:id`), reproducible `Job → Task → Artifact`; identical inputs produce identical outputs (NFR-02).
- **Docker.** Separate container in compose with isolated resource limits.
- **Future Modal migration.** Serverless execution is possible with zero agent changes because the Inference Registry abstracts transport (ADR-014 model providers are transport-agnostic).

## Consequences

### Positive

- **One database** = single transaction boundary, single RLS model, single backup — dramatically simpler operations and a smaller attack surface.
- **pgvector gives tenant-scoped similarity search** without a second datastore.
- **Feature store avoids Feast complexity**; Parquet/DuckDB snapshots are reproducible and cheap.
- **Materialized serving views** keep inference fast and consistent with training definitions (no train/serve skew).
- **Compute isolation** improves security, determinism, and independent scaling.

### Negative

- **pgvector scales less far** than a dedicated vector DB at extreme scale (billions of vectors, hybrid search) — explicitly deferred, revisit condition documented.
- **Materialized views have refresh latency**; staleness is handled by DataOps freshness checks and degraded modes, not by the store.
- **One Postgres instance carries more load** (transactional + vector + serving views); monitoring and capacity planning must account for it.
- **Feature store still needs implementation** (Parquet/DuckDB pipeline, serving views, staleness config).
- **devsecops.md compose topology is superseded** on the vector-store point (Qdrant container).

## Compliance

1. No Qdrant in the MVP deployment topology (compose, settings, tooling); embeddings live in pgvector tables with `tenant_id` + RLS.
2. Training snapshots are produced only from the offline plane (Parquet → DuckDB), never from serving views.
3. Serving features come from Postgres materialized views via `serving.py`, tenant-scoped.
4. Every embedding row carries `tenant_id`; retrieval filters by `tenant_id` at query time.
5. `apps/compute` remains a separate service; the API never imports dataframe/ML libraries.

**References:** `docs/14-platform/implementation-plan.md` §4b (locked stack), `docs/09-platform/devsecops.md` (superseded on Qdrant), `docs/09-platform/compute-runtime.md` (pre-dates the `python_runtime/ → apps/compute` rename), ADR-0001 (RLS `app.tenant_id`), ADR-008 (layered architecture).
