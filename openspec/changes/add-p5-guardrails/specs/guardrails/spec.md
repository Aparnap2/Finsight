## ADDED Requirements

### Requirement: Trust Domains

The system SHALL enforce three trust domains on every code path. Trusted: deterministic financial engine, PostgreSQL constraints, policy engine, authorization layer, verified external state, immutable evidence, execution service, post-execution verifier. Conditionally trusted: Razorpay, QuickBooks, legacy financial system, Google Sheets, Gmail, Slack — each authoritative for particular facts but never for arbitrary instructions. Untrusted: LLM-generated text, LLM-generated tool arguments, Gmail content, spreadsheet free text, retrieved documents, customer-provided text, Slack free text, tool-result free text. The LLM MUST NOT elevate untrusted content into authorization.

#### Scenario: Trusted state is the only financial truth

- **WHEN** a deterministic financial fact (amount, tolerance, materiality, reconciliation result) is present alongside a conflicting LLM text claim
- **THEN** the system treats the deterministic fact as authoritative and rejects the conflicting LLM claim with an audit record

#### Scenario: Conditionally trusted external fact requires verification before promotion

- **WHEN** a Gmail or Sheets retrieval returns an amount for one exception
- **THEN** the amount is treated as data and is not promoted to authoritative state until it passes canonical validation, evidence bundling, and post-execution verification

#### Scenario: Untrusted content never becomes authorization

- **WHEN** untrusted content (LLM output, Gmail content, sheet free text, tool-result free text) contains authorization language
- **THEN** the system preserves it as data and denies any authorization, policy override, or tool-instruction derived solely from it

### Requirement: Guardrail Taxonomy Coverage

The system SHALL implement guardrails under six categories — Input, Tool, Reasoning, Output, Execution, Post-execution — as defined in the taxonomy. Each category SHALL have machine-testable invariants with at least one positive, one negative, and (where practical) one adversarial test.

#### Scenario: Taxonomy present and testable

- **WHEN** the P5 taxonomy is evaluated
- **THEN** each of the six categories exposes at least one invariant with positive, negative, and adversarial coverage

### Requirement: Input Guardrails

The system SHALL validate tenant, case, user authorization, context size, data classification, untrusted-content boundaries, and allowed investigation scope before planning or LLM invocation. Violation SHALL be rejected before any LLM call, with an audit record and no state mutation.

#### Scenario: Unauthorized or oversized input is rejected before the LLM

- **WHEN** an investigation request arrives with a non-authorized actor, a mismatched tenant/case pair, or a context size exceeding the declared maximum
- **THEN** the request is rejected before LLM invocation, no evidence is collected, and the rejection is audited with actor, tenant, case, and reason

#### Scenario: Investigation respects per-type allowed scope

- **WHEN** a plan requests a capability outside the allowed investigation scope for its exception type
- **THEN** the plan is rejected by the verifier/output guardrail and counts against the bounded replan budget

### Requirement: Tool Guardrails

The system SHALL enforce a closed capability allowlist drawn only from the frozen vocabulary, with per-call tenant binding, argument schema validation, input-size and output-size limits, timeouts, duplicate-call detection, URL restriction, credential isolation, and explicit denial of arbitrary SQL, arbitrary network access, and credential disclosure.

#### Scenario: Allowlisted tool with valid tenant-bound args executes

- **WHEN** a capability call names a frozen-allowlist entry with tenant-bound, schema-valid, size-bounded arguments
- **THEN** the capability executes via the deterministic executor and the result is bounded and audited

#### Scenario: Tool outside allowlist or with forbidden surface is rejected

- **WHEN** a capability call names a capability outside the frozen allowlist, supplies invalid arguments, exceeds size/timeout/duplication limits, requests an arbitrary URL or SQL, or would expose credentials
- **THEN** the call is rejected before execution with an audit event and no provider mutation

### Requirement: Reasoning Guardrails

The system SHALL enforce typed output, hypothesis-vs-factual-claim separation, evidence requirements, confidence caps, bounded replanning, deterministic termination, and the prohibition on authority or authorization claims. Guardrails MUST NOT rely solely on prompt wording.

#### Scenario: Hypothesis stays hypothesis until proven

- **WHEN** the LLM emits a ranked candidate explanation for a variance
- **THEN** each explanation is labeled hypothesis, carries confidence below the verified threshold, cites evidence_ids, and causes no state change

#### Scenario: Bounded replanning terminates

- **WHEN** successive LLM outputs are verifier-rejected up to the bounded budget (max 2 replans, confidence cap 0.85)
- **THEN** the orchestrator terminates with exhaustion and routes to HITL rather than looping indefinitely

### Requirement: Output Guardrails

The system SHALL validate output schema, evidence references, claim grounding, financial amount provenance, resolution type, target system, absence of unauthorized instructions, and absence of unsupported causal claims. Every factual claim SHALL cite evidence_ids whose bundles belong to the case tenant.

#### Scenario: Output without grounding is rejected

- **WHEN** a synthesis names a financial amount or causal claim without citing evidence_ids that resolve to the case tenant's verified evidence bundles
- **THEN** the output is rejected, audited, and causes no proposal construction

### Requirement: Execution Guardrails

The system SHALL validate policy, approval, proposal identity (`proposal_id + version + content_hash`), proposal version/hash integrity, idempotency key storage, state (not CLOSED/terminal), financial limits, target-system authorization, and execution state before any financial mutation. Rejected execution SHALL perform no provider call.

#### Scenario: Stale or tampered proposal cannot execute

- **WHEN** execution is requested with a proposal identity whose version or content_hash does not exactly match the live proposal triple, or whose amount drifts from the stored hash
- **THEN** execution is denied before any adapter call, no mutation occurs, and the denial is audited with both triples

### Requirement: Post-Execution Guardrails

The system SHALL validate authoritative provider state and, when applicable, the legacy result file, re-reconcile expected vs actual mutation, and only then mark closure conditions; unknown provider state SHALL require reconciliation, never silent close.

#### Scenario: Post-execution verification gates CLOSED

- **WHEN** an execution completes and authoritative provider state is re-read
- **THEN** the system marks CLOSED only if the expected mutation is proven; otherwise it marks FAILED/ESCALATED or UNKNOWN awaiting reconciliation
