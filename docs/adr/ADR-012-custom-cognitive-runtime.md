# ADR-012: Custom Cognitive Runtime — Intentional Orchestration, Not a LangGraph Stopgap

**Status:** Accepted  
**Date:** 2026-08-03  
**Deciders:** Architecture Team (decision-maker rejection of LangGraph, decision D2)  

---

## Context

Plan v3 §4b (`docs/14-platform/implementation-plan.md`) locked "AI = LiteLLM + LangGraph". The platform already implements a custom orchestration runtime: `ReasoningHarness` in `finance/cognition/harness.py` drives a node pipeline with an iteration loop (max 5), per-action retry logic, escalation gates, and structured telemetry to `.reasoning_traces/` (`docs/09-platform/agentops.md`). The open question was whether to migrate this pipeline onto LangGraph or keep the custom runtime.

Decision-maker: **REJECT LangGraph.** Keep the custom cognitive runtime. Document as intentional: *"Custom Cognitive Runtime — inspired by LangGraph concepts, not dependent on the LangGraph runtime."* Pipeline: **Planner → Executor → Verifier → Reflection**. NOT a temporary stopgap.

## Decision

The orchestration layer is the **Custom Cognitive Runtime**, and this is a permanent architectural choice — not a temporary stopgap pending LangGraph adoption:

- **Pipeline:** Planner → Executor → Verifier → Reflection. Retrieval is an **executor concern** — data acquisition happens inside executor actions, not as a separate LLM-adjacent stage. (The older 5-node description with a standalone Retriever, in `docs/09-platform/agentops.md` and `docs/07-ai-runtime/Cognitive Runtime.md`, is superseded on this point.)
- **Inspired by, not dependent on:** the design reuses LangGraph's concepts (node graph, typed state, iteration loop) but imports no LangGraph runtime. `NodeRegistry` (`finance/cognition/registry.py`) provides node registration, pipeline ordering, and engine injection without a graph library.
- **Why:** the platform's orchestration is small and well-understood; deterministic-first pipelines (ADR-001/007) keep orchestration mostly linear; LangGraph would add a runtime dependency, checkpointing machinery, and an abstraction layer with no benefit at this scale; the evidence pipeline requires full control of iteration, retry, and escalation; zero migration risk.
- **Revisit condition:** LangGraph is reconsidered only if orchestration needs grow into dynamic multi-agent graphs, durable checkpointing across restarts, or human-in-the-loop workflows at scale — a future decision, not a pre-commitment.

## Consequences

### Positive

- **No new runtime dependency**; the supply chain stays lean.
- **Full control** of iteration, retry, escalation, and loop termination (max-iterations guard).
- **Deterministic, testable orchestration.** Golden datasets drive `EvaluationRunner` without a graph engine.
- **`NodeRegistry` already delivers LangGraph-like configurability** — register, reorder, inject engines — without the runtime.
- **Structured telemetry to `.reasoning_traces/`** continues unchanged.

### Negative

- **We maintain our own state machine.** Loop/stall edge cases (documented in agentops.md §Failure Modes) are our responsibility: the max-iterations guard exists; stall detection is a known improvement.
- **We forgo LangGraph's checkpointing, visualization, and community tooling.**
- **Plan v3 §4b's "LangGraph" text is superseded** for orchestration; readers must consult this ADR.
- **Future migration cost is non-zero** if orchestration later grows to LangGraph scale — the node protocol would need adaptation.

## Compliance

1. No `langgraph` (or `langchain`) import anywhere in `apps/`, `agents/`, `finance/`, or `shared/` — verified by grep in CI.
2. `NodeRegistry` is the single configuration point for pipeline shape and node injection.
3. The pipeline shape is Planner → Executor → Verifier → Reflection; retrieval is implemented as executor actions.
4. Orchestration remains LLM-boundary-safe: only the planner (LLM) and downstream commentary (LLM) touch the boundary; executor, verifier, and reflection make zero LLM calls (boundary rule B5).

**References:** `docs/09-platform/agentops.md` (custom runtime capabilities and failure modes), `docs/14-platform/implementation-plan.md` §4b (superseded on LangGraph), `finance/cognition/` (`harness.py`, `registry.py`, `nodes/`), ADR-003 (typed pipeline state), ADR-008 (layered architecture).
