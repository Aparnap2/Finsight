# ADR-015: AI Trust Boundary — Verified Assertions In, Language Out; Audit Before AI

**Status:** Accepted  
**Date:** 2026-08-03  
**Deciders:** Architecture Team (decision-maker confirmation of decisions D7, D8)  

---

## Context

ADR-001 established the hybrid architecture: deterministic engines own all math; the LLM renders language. ADR-007 hardened it: the LLM never performs arithmetic. Two decisions remained open:

1. **RAG in MVP (D7).** Whether retrieval-augmented generation is needed at all, and under what conditions it may be enabled.
2. **Audit ordering (D8).** When the audit layer must land relative to AI capabilities, and the pipeline ordering guarantee.

Decision-maker (D7): RAG **disabled by default**; enable only after prompt-injection evaluation, retrieval benchmarks, grounding tests, and golden datasets pass. Existing structured data (Sheets, finance ontology, formula registry, business rules) does **NOT** require RAG.

Decision-maker (D8): **non-negotiable ordering** — **Import → Validation → Audit → AI → Recommendation**; NEVER **AI → Audit**. Audit must land before any ML/LLM capability reaches `production`.

## Decision

### 1. The hard Trust Boundary

```
 Business Data ──► Validation ──► Compute Runtime ──► Verified Assertions
                                                            │
                                                     ┌─────┴──────┐
                                                     │   TRUST    │
                                                     │  BOUNDARY  │  (hard — the LLM never crosses)
                                                     └─────┬──────┘
                                                           │
                                                           ▼
                                        LLM ──► Natural Language ──► Recommendation ──► Human
```

- Everything **left** of the boundary is deterministic: raw business data is validated (`finance/validation/`), computed by the Compute Runtime (`apps/compute`, `finance/` engines), and converted into typed, evidence-backed `Assertion` objects.
- Everything **right** of the boundary is language-only: the LLM explains, summarises, or recommends — it never computes.
- **The LLM never crosses the boundary.** It never receives raw business data and never computes EBITDA, cash flow, variances, KPIs, or ratios — it only explains, summarises, or recommends from verified assertions.
- **Enforcement.** Pipeline ordering (ADR-012: Planner → Executor → Verifier → Reflection), CI arithmetic gate, `finance/` no-LLM dependency rule, `validate_commentary_claims()` cross-check, and exactly-2-LLM-calls telemetry.
- **Continuity.** This ADR makes the ADR-001 hybrid boundary and the ADR-007 no-math rule explicit and structurally enforceable.

### 2. RAG is disabled by default (D7)

- `features.rag: false` in `tenant.yaml`; RAG is a per-tenant opt-in, never a default.
- **Existing structured data does NOT require RAG:** Google Sheets (ADR-002), the finance ontology / domain model (ADR-010), the formula registry, and business rules are served by deterministic engines and registries. Retrieval would add cost and attack surface without benefit.
- A tenant may enable RAG **only after** the evaluation suite passes: prompt-injection evaluation dataset, retrieval benchmarks, grounding tests, and golden datasets (governance) — all gated in CI (`docs/08-evaluation/`, `docs/09-platform/llmops.md` §Evaluation).
- Even when enabled, retrieved content is converted into evidence/assertions **before** crossing the boundary (rule B3); the LLM never receives raw retrieved documents.

### 3. Audit before AI (D8)

- **Non-negotiable ordering:** **Import → Validation → Audit → AI → Recommendation**. NEVER **AI → Audit**.
- **Audit** = the 10-question completeness (Who? Tenant? Role? Policy? Tool? Prompt? Evidence? Decision? Timestamp? Version?) captured in `AuditLog` plus enrichment (role, policy decision, tool, prompt version, evidence IDs — plan v3 Phase 6).
- **Audit must land before any ML/LLM capability reaches `production`.** Capability rollout (AI architecture guide §8.6) cannot promote an AI capability to `production` until its audit chain answers all 10 questions.
- This sequencing makes audit enrichment an **MVP gate for AI features**, not a post-MVP nicety.

## Consequences

### Positive

- **Numerical correctness never depends on a stochastic model** — the trust boundary makes this structural, not procedural.
- **Prompt-injection defense is architectural.** The LLM never sees raw data, so it cannot be steered by data.
- **RAG stays out of MVP** — no retrieval pipeline, no injection surface, lower cost.
- **Audit-before-AI** guarantees every production AI output is auditable from day one.
- **Continuity with ADR-001/007** — the boundary is now explicit and enforceable.

### Negative

- **Boundary enforcement is a permanent discipline**: CI gates, code review, and orchestration ordering must be maintained forever.
- **No RAG for unstructured-corpus questions at MVP** (accepted — structured data covers the product need).
- **Audit enrichment must be sequenced before AI promotion**, which may delay AI capability rollouts that would otherwise ship early.
- **Enabling RAG later requires building the full evaluation gate first** (prompt-injection, retrieval, grounding, golden datasets).

## Compliance

1. The LLM never receives raw business data — verified assertions only. Enforced by grep + code review; `finance/` has no LLM client import.
2. CI arithmetic gate blocks arithmetic keywords in prompts; EBITDA/cash-flow/variance/KPI/ratio computation is never requested of the LLM.
3. `features.rag` defaults to false; enabling requires the evaluation gates (prompt-injection, retrieval, grounding, golden datasets) to pass.
4. Pipeline ordering is Import → Validation → Audit → AI → Recommendation; any route that runs AI before Audit fails review/CI.
5. No ML/LLM capability is promoted to `production` until its audit chain answers all 10 questions.

**References:** ADR-001 (hybrid architecture), ADR-007 (no LLM calculations), ADR-005 (context packs — the only way data reaches the LLM), ADR-012 (custom cognitive runtime ordering), `docs/09-platform/llmops.md` (boundary rules, §Evaluation), `docs/12-database/audit.md`, plan v3 principles 5–6 (LLM never sees raw data; audit answers 10 questions).
