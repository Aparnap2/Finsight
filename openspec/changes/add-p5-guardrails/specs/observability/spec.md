## ADDED Requirements

### Requirement: Observability as Evaluation Layer Only

Agent observability (including any Langfuse integration) SHALL be an observability and evaluation layer only. It MUST NOT become authorization, policy, execution, financial truth, state management, or an agent authority. Deterministic code SHALL remain the source of truth for all financial facts even when tracing is enabled, disabled, or unreachable.

#### Scenario: Trace outage does not change authority

- **WHEN** the tracing backend is unavailable or its API is rate-limited
- **THEN** deterministic authorization, policy, execution, and verification still succeed and the failure is recorded only as an observability warning, never as a financial or approval outcome

### Requirement: Observability Integration Boundary

The system SHALL define the observability integration boundary: the agent layer invokes a `TracerProtocol`-typed tracer through `create_tracer()` (`shared/tracing/factory.py`), never bare Langfuse SDK calls. The tracer SHALL support per-case traces whose spans include at minimum `context assembly`, `planner`, `LLM generation`, `verifier`, `tool call` (with `tool result`), `replan`, `evidence synthesis`, `proposal candidate`, `policy`, `HITL`, `execution`, `verification`. Payloads SHALL be length-bounded (100 chars per value via `_truncate`) and credential-free.

#### Scenario: Per-case trace is emitted without leaking secrets

- **WHEN** an exception case is investigated end-to-end with tracing enabled via environment
- **THEN** a single trace for that case contains the ordered span chain above with bounded, redacted payloads, and no `api_key`, token, or authorization header appears in any span

### Requirement: Observability Payload Discipline

The system SHALL emit no unrestricted financial, PII, or credential payload to observability. Secrets (API keys, access tokens, refresh tokens, authorization headers, provider secrets) MUST never be emitted. Money payloads and evidence content MUST be emitted only via declared allowlisted fields or hashed placeholders after the PII/secret boundary (see `grounding` capability). Violation SHALL be caught by `tests/unit/tracing/test_observability_payload.py`.

#### Scenario: Unsafe payload is redacted before emission

- **WHEN** a tracing span references evidence containing credential-bearing or PII fields
- **THEN** the emitted span carries only the allowlisted/redacted projection and the original sensitive value is not present in the payload

### Requirement: Graceful Degradation of Observability

The system SHALL degrade gracefully when observability is disabled or degraded: `TracerProtocol` `NoOp` fallback SHALL be a singleton incurring no Langfuse import; failures to create or flush traces SHALL NOT raise to callers and SHALL NOT alter proposal, approval, execution, or closure outcomes.

#### Scenario: Disabled observability is invisible to the control plane

- **WHEN** tracing is not configured (no `LANGFUSE_*` env) or the tracer health check reports unavailable
- **THEN** the control plane executes the investigation, policy, and execution with identical deterministic outcomes and no unhandled tracing exception
