## ADDED Requirements

### Requirement: Observability Boundary

The system SHALL capture agent traces as `case → context assembly → planner → LLM generation → verifier → capability call → capability result → replan → final candidate → policy → approval → execution → verification` with `correlation_id` (webhook `fingerprint`/`idempotency_key` → S3 `ObjectMeta.key` → LLM context → execution), `tenant-safe identifiers` (no PII beyond tenant/case), `case identifier`, `timestamp`, `latency`, `status`, and SHALL NOT capture unrestricted sensitive payloads (Gmail body, Sheets free text, legacy rejection, full provider JSON). Traces SHALL be queryable by `correlation_id` to reconstruct `CASE-1027 → agent → legacy batch → S3 → ingestion → reconciliation`.

#### Scenario: Correlation reconstructs the path

- **WHEN** webhook `CASE-1027` is ingested, an S3 legacy outbound file `tenant-a/CASE-1027/batch.csv` is processed, and the case is re-reconciled
- **THEN** a single `correlation_id=CASE-1027` trace contains spans for each hop with `tenant-safe` IDs and bounded `evidence_required` references, not raw Gmail bodies

### Requirement: Agent Trajectory Contract

The system SHALL provide a first-class trajectory harness recording `INPUT → MODEL OUTPUT → VERIFIER → TOOL/CAPABILITY SELECTION → TOOL ARGUMENTS → TOOL RESULT → NEXT MODEL OUTPUT → FINAL RESULT` in four modes: `Fake` (`FakeLLM`+Fake capabilities+Fake evidence), `Replay` (recorded LLM responses+real deterministic capabilities+real verifier), `Live` (real Groq+real local capabilities+real RAG/evidence+real guardrails), `E2E` (real app+real PostgreSQL+MiniStack where actual AWS seams exist+legacy boundary). Default `pytest -m "not live_llm"` SHALL stay green; live `FINSIGHT_ALLOW_LIVE_LLM=1 pytest -m live_llm` gated, budget-guarded, small representative scenarios, trajectories recorded for replay.

#### Scenario: Replay reproduces without live call

- **WHEN** a `Live` trajectory for `timing difference` is recorded (input, model output, verifier, tool selection, tool result, final)
- **THEN** `Replay` with the recorded `MODEL OUTPUT` and real `Verifier`+`CapabilityExecutor` reproduces the same `tool-selection precision` and `final candidate` without a Groq call

### Requirement: Langfuse Adapter Decision

The system SHALL evaluate `shared/tracing/` (`TracerProtocol`, `NoOpTracer`, `LangfuseTracer` lazy, `create_tracer()` env-driven, `Bearer redacted`) as the observability abstraction before making `Langfuse` a core dependency, with architecture `FinSight orchestration → observability abstraction → Langfuse adapter (optional)`, never `Langfuse → authorization → execution`. `Langfuse` is for `tracing/evaluation/LLM-tool telemetry/trajectory inspection/latency-cost/dataset experiments`, not `policy/financial truth/authorization/state/execution`. If `shared/tracing/` satisfies the trace schema, defer `Langfuse` adapter.

#### Scenario: Abstraction decouples core from Langfuse

- **WHEN** `LANGFUSE_HOST` is unset and `create_tracer()` returns `NoOpTracer`
- **THEN** the agent `case → ... → verification` flow completes with identical financial/policy outcomes and no `Langfuse` network call
