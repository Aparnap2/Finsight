## ADDED Requirements

### Requirement: Spec Conformance Keywords
The whole FinSight v2 spec SHALL use RFC 2119 conformance keywords with the following legend:

- **MUST / MUST NOT**: absolute requirement. A non-conformant implementation is in violation of the spec.
- **SHOULD / SHOULD NOT**: strong recommendation. Valid only with documented justification and compensating control when not followed.
- **MAY**: optional permission. Implementations MAY choose to include or omit the behavior without violating conformance.

#### Scenario: Unambiguous conformance interpretation
- **WHEN** a requirement uses MUST, SHOULD, or MAY
- **THEN** conformance is evaluated per the legend above and no runtime code is implied by the wording alone

### Requirement: LLM Allowed Acts Are a Closed Set of Typed-Candidate Producers
The system MUST restrict all LLM domain behavior to exactly the following five allowed acts, and each act MUST produce typed-candidate output only with no direct state effect, no provider call, and no verdict:

- **Semantic interpretation:** MUST produce a candidate reading of ambiguous reconciliation / exception text grounded to supplied evidence, never an authoritative determination.
- **Hypothesis generation:** MUST produce ranked candidate explanations for a variance or exception, each marked as unproven hypothesis, never as verified root cause.
- **Investigation planning:** MUST produce a candidate ordered plan of deterministic investigation steps referencing allowlisted capabilities, never execute them.
- **Capability selection from allowlist only:** MUST produce a candidate reference to one or more capabilities drawn exclusively from the frozen allowlist, never invent, import, or invoke a capability.
- **Evidence synthesis:** MUST produce a candidate summary that cites `evidence_ids` for every factual claim, never declare `EVIDENCE_VERIFIED`.

The system SHOULD attach rationale and calibrated confidence to each candidate. The system MAY order or filter candidates deterministically before verification.

#### Scenario: Semantic interpretation yields candidate only
- **WHEN** the LLM interprets an ambiguous memo attached to a frozen reconciliation break
- **THEN** the output MUST be a typed interpretation-candidate referencing source `evidence_ids`, and the authoritative amount and reconciliation state MUST remain unchanged

#### Scenario: Hypothesis generation stays unproven
- **WHEN** the LLM proposes candidate causes for an exception
- **THEN** each cause MUST be labeled hypothesis with confidence below the VERIFIED threshold, MUST cite `evidence_ids`, and MUST NOT set `EVIDENCE_VERIFIED` or `EXECUTION_VERIFIED`

#### Scenario: Investigation planning does not execute
- **WHEN** the LLM emits an investigation plan naming allowlisted capabilities in order
- **THEN** no capability SHALL run until the deterministic verifier and the P3 proposal / approval / execution path authorize and execute it

#### Scenario: Capability selection outside allowlist is rejected
- **WHEN** the LLM candidate names a capability not on the allowlist
- **THEN** the deterministic verifier MUST reject the output, audit the rejection, and return for re-plan without any capability execution

#### Scenario: Sixth act attempted is rejected
- **WHEN** the LLM output attempts any act outside the five (e.g., decides an amount, approves, closes, mutates, verifies)
- **THEN** the output MUST be rejected as out-of-scope, audited, cause no mutation, and count against the bounded re-plan budget

### Requirement: Formal Handoff — Typed LLM Output Is Input to Deterministic Validation, Not an Authorization
The system MUST enforce the formal handoff principle: *"A typed LLM output is an input to deterministic validation, not an authorization."* Every LLM output MUST traverse the full deterministic chain — schema validation → authorization check → capability execution → evidence verification → policy check → existing P3 `ResolutionProposal` / approval / execution path — before any observable effect, provider mutation, state transition, or `CLOSED` emission. P4 MUST plug INTO the frozen reconciliation and exception-ops specs; it MUST NOT bypass, duplicate, or shadow them. LLM access MUST go through `LLMProvider` thin direct SDKs only.

#### Scenario: Happy-path handoff through P3
- **WHEN** the LLM emits a schema-valid synthesis candidate with grounded `evidence_ids`
- **THEN** the system MUST still pass it through authorization, deterministic capability execution, evidence verification, and policy before constructing a P3 `ResolutionProposal`, and no effect SHALL occur before that path completes

#### Scenario: Direct effect without P3 path blocked
- **WHEN** an LLM output or caller attempts to apply a state change, emit `CLOSED`, or call a provider directly from LLM output
- **THEN** the system MUST block the effect, reject the output, audit the attempt, and leave P3 reconciliation and exception state untouched

#### Scenario: Authorization skipped is denied
- **WHEN** a well-formed LLM candidate arrives without a passing authorization check
- **THEN** the system MUST NOT execute any capability or advance any `ResolutionProposal`, and MUST record an authorization-denied audit event

#### Scenario: Framework bypass via non-Provider path rejected
- **WHEN** any domain path attempts LLM invocation outside `LLMProvider` or via LangChain / LiteLLM
- **THEN** the system MUST reject the call at the boundary, since only thin direct SDKs behind `LLMProvider` are permitted in domain

### Requirement: Frozen LLM-Never Set — 14 Prohibited Deterministic Authorities
The system MUST freeze the following 14 prohibitions on the LLM. The LLM MUST NEVER perform them, authorize them, or declare them complete: (1) determining authoritative amounts, (2) performing financial calculations, (3) changing financial state, (4) executing provider mutations, (5) approving proposals, (6) applying state transitions, (7) emitting CLOSED authoritatively, (8) bypassing policy / approval, (9) choosing idempotency keys, (10) overriding idempotency keys, (11) declaring evidence VERIFIED, (12) declaring execution VERIFIED, (13) overriding authorization, (14) selecting prod / sandbox mode. Any output attempting one MUST be rejected by the deterministic verifier, audited with the offending output preserved, and cause zero mutation.

The system SHOULD surface a machine-readable `never_violation` reason naming the violated item. The system MAY trigger re-plan for recoverable violations up to the bounded budget, else escalate to HITL.

#### Scenario: Authoritative amount declared is rejected
- **WHEN** LLM output states the authoritative break amount or ledger balance
- **THEN** the verifier MUST reject it, audit it, and retain the P3 deterministic amount as sole authority

#### Scenario: Financial calculation presented is rejected
- **WHEN** LLM output presents a computed total, variance, tolerance, or derived financial figure as authoritative
- **THEN** the verifier MUST reject it and require recomputation by the deterministic reconciliation engine

#### Scenario: State change asserted is rejected
- **WHEN** LLM output asserts or instructs a ledger, balance, or reconciliation record change
- **THEN** the system MUST reject it with no state write and no `ResolutionProposal` mutation

#### Scenario: Provider mutation commanded is rejected
- **WHEN** LLM output calls, commands, or claims to have called a bank / ERP / payment provider mutation
- **THEN** the system MUST reject it, perform no provider call, and audit the attempt

#### Scenario: Approval claimed is rejected
- **WHEN** LLM output approves or claims approval of a `ResolutionProposal`
- **THEN** the system MUST reject it, since approval belongs exclusively to the P3 approval path, and the proposal MUST remain unapproved

#### Scenario: State transition directed is rejected
- **WHEN** LLM output applies or directs a reconciliation or exception state transition
- **THEN** the system MUST reject it and leave reconciliation and exception-ops state machines unchanged

#### Scenario: CLOSED emitted is rejected
- **WHEN** LLM output emits, asserts, or implies `CLOSED` for a case or exception
- **THEN** the system MUST reject it, since only the P3 deterministic execution path may emit `CLOSED` after `EXECUTION_VERIFIED`

#### Scenario: Policy or approval bypass instructed is rejected
- **WHEN** LLM output instructs skipping, fast-tracking, or overriding policy or approval gates
- **THEN** the system MUST reject it, enforce the frozen policy path, and audit the bypass attempt

#### Scenario: Idempotency key invented or overridden is rejected
- **WHEN** LLM output invents, selects, replaces, or reuses an idempotency key
- **THEN** the system MUST reject it with no key change and audit the attempt, since keys are assigned deterministically outside LLM authority

#### Scenario: VERIFIED declared is rejected
- **WHEN** LLM output declares evidence `EVIDENCE_VERIFIED`, declares execution `EXECUTION_VERIFIED`, or claims a fix is confirmed
- **THEN** the system MUST reject it, since only deterministic verification may set verified flags, and `ResolutionProposal != Execution` MUST hold

#### Scenario: Authorization overridden is rejected
- **WHEN** LLM output grants permission, elevates scope, or overrides a denial
- **THEN** the system MUST reject it, uphold the deterministic authorization decision, and audit the override attempt

#### Scenario: Execution mode selected is rejected
- **WHEN** LLM output selects, switches, or asserts production versus sandbox execution mode
- **THEN** the system MUST reject it, retain the deterministically configured mode, and perform no mode change

### Requirement: Deterministic Verifier Gates Every LLM Output
The system MUST pass every LLM output through a deterministic verifier before any P3 effect. The verifier MUST enforce: (a) schema validation against the frozen typed-candidate schema; (b) grounding check requiring every factual claim to cite valid `evidence_ids`; (c) confidence caps under which causal or verification claims can never achieve `EVIDENCE_VERIFIED` or `EXECUTION_VERIFIED` by confidence alone. On pass, the verifier MUST forward the candidate into the P3 proposal / approval / execution path; on fail, it MUST return for bounded re-plan of at most N rounds and then escalate to HITL with full audit trail. N MUST be a configured bound and SHOULD default conservatively.

#### Scenario: Schema failure returns for re-plan
- **WHEN** LLM output violates the typed-candidate schema (missing fields, wrong types, unknown act)
- **THEN** the verifier MUST reject it, record a schema-failure audit, make no P3 effect, and return for re-plan within budget

#### Scenario: Grounding failure on uncited factual claim
- **WHEN** LLM output contains a factual claim without a valid cited `evidence_ids` entry
- **THEN** the verifier MUST reject it as ungrounded, audit the missing citation, and return for re-plan with no capability execution

#### Scenario: Causal claim never VERIFIED by confidence alone
- **WHEN** the LLM asserts a causal explanation with maximum confidence but without deterministic evidence verification
- **THEN** the verifier MUST cap it below `EVIDENCE_VERIFIED`, MUST NOT promote it to `EXECUTION_VERIFIED`, and MUST require deterministic verification before any P3 `ResolutionProposal` advances

#### Scenario: High confidence does not authorize execution
- **WHEN** a grounded, schema-valid candidate carries very high LLM confidence and requests execution
- **THEN** the system MUST still withhold execution until authorization, capability execution, evidence verification, policy, and the P3 approval path succeed

#### Scenario: Bounded re-plan then HITL
- **WHEN** verifier failures exhaust the bounded re-plan budget of at most N rounds
- **THEN** the system MUST stop re-planning, freeze the case without mutation, preserve all attempts and audits, and escalate to HITL for human decision

### Requirement: Closed Read-Only Capability Allowlist
The system MUST restrict LLM capability selection to exactly: `get_stripe_payment`, `get_stripe_refunds`, `get_qb_transaction`, `get_expected_state`, `search_gmail`.

- The system MUST reject any plan referencing tools outside the allowlist (including `read_database`, `write_database`, `execute_sql`, `call_api`): zero capabilities execute, rejection recorded.
- Each allowlisted capability MUST declare typed inputs/outputs returning `ToolResult`-shaped evidence with `source`, `source_record_id`, `retrieved_at`, `content_hash`.
- Capability execution MUST occur only in the deterministic executor: an LLM proposal alone MUST NOT trigger any capability call.
- No allowlisted capability MUST perform a write, mutation, or side effect.
- Each capability SHOULD declare bounded-input schemas so unscoped enumeration is impossible. The allowlist snapshot attached to a request MAY carry per-capability versions for audit.

#### Scenario: Allowlisted plan accepted
- **WHEN** the LLM emits a plan referencing only `get_stripe_payment` and `get_qb_transaction` in order
- **THEN** plan validation SHALL accept the capability-selection step and forward the plan to deterministic execution

#### Scenario: Arbitrary tool rejected
- **WHEN** the LLM emits a plan containing `read_database` or any name outside the five
- **THEN** plan validation SHALL reject the entire plan, execute zero capabilities, and record the rejection with model/cost metadata

#### Scenario: Capability returns non-evidence shape quarantined
- **WHEN** a capability result lacks any of `source` / `source_record_id` / `retrieved_at` / `content_hash`
- **THEN** the deterministic executor SHALL quarantine the result as unverified and it SHALL NOT satisfy any `evidence_required` entry

### Requirement: LLM Input Contract InvestigationRequest Is Deterministic and Bounded
The system MUST fully populate every `InvestigationRequest` in deterministic code before any LLM call, with fields: `exception_id`, `exception_type`, `evidence_ids[]` (restricted to `EVIDENCE_VERIFIED` evidence), bounded context window, capability allowlist snapshot, and round budget.

- The LLM MUST NOT receive full DB access, live connection handles, credentials, or unscoped history beyond the bounded context window.
- Unverified, quarantined, or pending evidence MUST be excluded from LLM input.
- The allowlist snapshot in the request MUST be the enforcement source for that round's validation.
- The round budget MUST bound LLM proposal rounds; the orchestrator MUST stop calling the LLM once exhausted.
- The context window SHOULD be minimal. The request MAY include P3-plane template identifiers for narrative alignment.

#### Scenario: Well-formed deterministic request proceeds
- **WHEN** deterministic code assembles a complete `InvestigationRequest` with verified evidence, bounded context, allowlist snapshot, and round budget
- **THEN** the LLM call SHALL proceed and the request SHALL be logged with model/cost metadata sans credentials

#### Scenario: Unscoped input fails closed
- **WHEN** a proposed input includes full-table dumps, unscoped history, connection strings, or unverified evidence
- **THEN** request construction SHALL fail closed, the LLM SHALL NOT be invoked, and the run SHALL degrade to the P3-plane template path

#### Scenario: Round budget exhausted halts LLM calls
- **WHEN** the round budget reaches zero without an accepted plan
- **THEN** deterministic code SHALL halt LLM calls and reconcile via P3 templates with no change to verified-state semantics

### Requirement: Typed Output Contracts InvestigationPlan and InvestigationResult With Strict Validation
All LLM output MUST conform to strict Pydantic contracts with unknown fields rejected, preserving `ResolutionProposal != Execution`.

- An `InvestigationPlan` MUST contain exactly: hypothesis text, ordered capability calls, `evidence_required` list, escalation flag.
- An `InvestigationResult` MUST contain per-claim records of exactly: statement, `evidence_ids`, confidence, `claim_kind` of `FACTUAL | HYPOTHESIS`.
- Causal claims MUST never be `VERIFIED`; any causal assertion MUST be at most `HYPOTHESIS` and MUST NOT satisfy verified flags on its own.
- Every `FACTUAL` claim MUST cite at least one verified `evidence_id`; uncited factual claims MUST be rejected.
- LLM output MUST be treated as a proposal only; no plan or result MUST mutate reconciliation state without deterministic validation and execution.
- Confidence SHOULD be calibrated and bounded (0–1). The escalation flag MAY force human review without altering verified-state flags.

#### Scenario: Valid plan and grounded result accepted as proposal
- **WHEN** the LLM returns a strict-schema plan plus a result whose `FACTUAL` claims each cite verified `evidence_ids`
- **THEN** validation SHALL accept the proposal and hand it to the deterministic executor, which alone decides execution and verified-state transitions

#### Scenario: Unknown fields or missing citations rejected
- **WHEN** LLM output contains unknown fields, omits `evidence_required`, emits an uncited `FACTUAL` claim, or marks a causal claim as verified
- **THEN** validation SHALL reject the output, execute nothing, leave verified flags unchanged, and log the rejection with model/cost metadata

#### Scenario: Escalation requested routes to human review
- **WHEN** a schema-valid result sets the escalation flag
- **THEN** the deterministic layer SHALL route to human review / P3-template narrative and SHALL NOT auto-advance

### Requirement: Provider Seam LLMProvider Protocol With Deterministic Fallback
All LLM calls MUST cross the `LLMProvider` protocol exposing `generate_structured` / `health_check` / `model_metadata` — no direct SDK imports at call sites.

- `GroqProvider` MUST be the default, with `OpenRouter` and `Local` as interchangeable implementations behind the same protocol.
- A deterministic fallback MUST exist such that the no-LLM path still reconciles via P3 templates; P4 unavailability MUST degrade to P3 with no loss of reconciliation coverage.
- Every provider call MUST be logged with model and cost metadata; NO credentials, API keys, or secrets MUST appear in code, logs, or request / plan / result payloads.
- Implementations MUST use thin direct SDKs only — no autonomous-agent or tool-execution frameworks in the provider layer.
- `health_check` SHOULD gate invocation so unhealthy providers trigger immediate P3 fallback without consuming round budget. `model_metadata` MAY expose version / pricing identifiers for cost auditing.

#### Scenario: Default provider serves structured output
- **WHEN** `GroqProvider.generate_structured` returns schema-valid output
- **THEN** the run SHALL proceed through validation and the call SHALL be logged with model/cost metadata and `model_metadata` recorded

#### Scenario: Provider unhealthy or call fails degrades to P3
- **WHEN** `health_check` fails or `generate_structured` errors / times out
- **THEN** the orchestrator SHALL skip remaining LLM rounds, reconcile deterministically via the P3 plane, and leave verified-state semantics unchanged

#### Scenario: Credential hygiene audit passes
- **WHEN** any provider call, log entry, or persisted artifact is inspected
- **THEN** it SHALL contain model/cost metadata and contain zero credentials, keys, or secrets
