# FinSight Implementation Playbook

## Engineering Decisions, FAQs, Constraints and Execution Rules

**Status:** Approved execution guidance
**Applies to:** P2–P7 and remaining deslop slices
**Product:** FinSight — three-source payment reconciliation for B2B SaaS companies

---

# 1. Mission and product boundaries

## Q1. What exactly are we building?

A payment reconciliation application for B2B SaaS finance teams. It connects
invoice register, Stripe transactions, and bank deposits. It normalizes the
data, performs deterministic reconciliation, identifies discrepancies, supports
human exception resolution, provides evidence-grounded AI explanations, and
produces auditable reports.

## Q2. Are we building an enterprise SaaS platform?

No. We are building a production-quality portfolio application demonstrating
sound engineering, financial correctness, security boundaries, and a complete
working business workflow. Do not implement enterprise capabilities merely
because enterprise applications commonly have them.

## Q3. What is the primary success criterion?

A developer can clone the repository, start the application, load demo data,
and complete the reconciliation workflow reliably. The workflow must be
demonstrable end to end without direct database manipulation or CLI
intervention during normal operation.

## Q4. What is explicitly out of scope?

General accounting software, GST/TDS processing, Tally/Zoho integrations,
accounts payable automation, vendor OCR, general ledger categorization,
autonomous money movement, traditional ML, generic multi-agent platforms,
Kubernetes, multi-region infrastructure, enterprise SSO, generic ETL
platforms, generic workflow engines, subscription and billing infrastructure.
Do not reopen these decisions without new evidence and explicit authorization.

---

# 2. Architecture and reuse decisions

## Q5. Should I create a new module?

First inspect existing implementation, runtime consumers, imports, tests,
configuration, database models, and CI workflows. If an existing component
already handles the requirement, reuse it. Only create a new module when the
existing implementation cannot reasonably satisfy the requirement. Document
the reason.

## Q6. Should I introduce a new framework?

Default answer: no. Prefer existing FastAPI, NiceGUI, PostgreSQL, Alembic,
SQLAlchemy, tenant middleware, RLS, LLM provider framework, S3 adapter, and
safety utilities. A new framework requires concrete evidence that existing
infrastructure is insufficient.

## Q7. Should I create a generic repository abstraction?

No. Use plain functions for reconciliation persistence. Do not introduce
generic repository base classes, CRUD frameworks, unit-of-work frameworks,
service locator patterns, or additional dependency injection systems.

## Q8. Should I create another service or process?

No, not for the current workflow. Use the existing application process. A
separate worker or queue requires a demonstrated workload or reliability
requirement.

## Q9. Should I refactor unrelated code while implementing a feature?

No. Make focused changes. If unrelated problems are discovered, determine
whether they block the current task; if not, record them and do not expand
the current implementation.

## Q10. What if the architecture specification differs from the existing implementation?

Determine whether the difference is an approved implementation adaptation, a
documented technical constraint, an actual specification contradiction, or an
existing implementation defect. Do not silently change the contract. Small
implementation adaptations may proceed when they preserve the approved
behavior. Material contract changes require explicit review.

---

# 3. Financial correctness

## Q11. Which component owns financial decisions?

The deterministic reconciliation engine. It owns financial arithmetic,
normalization rules, matching, fee calculations, refund handling, duplicate
detection, allocation, tolerance, and reconciliation outcomes. The LLM cannot
override these decisions.

## Q12. Can I use float for money?

No. Use Decimal for financial amounts. Avoid binary floating-point arithmetic,
implicit precision conversion, silent rounding, and unspecified currency
assumptions.

## Q13. Should ambiguous records be automatically matched?

No. Ambiguity must remain explicit. Do not invent matching rules merely to
increase the match rate.

## Q14. Can the AI resolve financial exceptions automatically?

No. AI may investigate, summarize, and explain. A human must make
consequential exception decisions.

## Q15. Can I change the reconciliation engine to make P2 easier?

Not casually. The existing engine is protected. If a defect is discovered:
reproduce it, identify the affected invariant, add an independent regression
test, propose the smallest correction, verify golden evidence and all
protected reconciliation tests. Do not rewrite the engine.

## Q16. What happens when financial data is incomplete?

Return explicit validation issues or unresolved outcomes. Never silently
discard financial records. Preserve source references so an operator can
identify the problematic input.

---

# 4. P1 source ingestion

## Q17. Is CSV the product's only supported input?

No. CSV is the initial adapter, not the product architecture. The ingestion
layer is source-independent.

## Q18. Should I implement Google Sheets now?

No. Google Sheets is a possible future adapter. Do not add OAuth or external
integrations before the core reconciliation workflow works.

## Q19. Should I implement Excel support?

No. Defer it.

## Q20. Should I implement direct Stripe and bank integrations?

No. Defer them. The current workflow can use supplied source data.

## Q21. Should I implement AI-powered column mapping?

No. Use deterministic header mapping and explicit validation.

## Q22. What if two sources contain equivalent data?

They should normalize to equivalent canonical records, subject to the defined
source semantics. Test this behavior independently.

## Q23. What must ingestion preserve?

Source type, source reference, original row reference, content digest where
appropriate, canonical normalized values, validation issues, duplicate versus
conflict classification, and financial precision. Do not pollute canonical
financial domain models with transport-specific metadata unnecessarily.

---

# 5. P2 — Persistence and API

## Q24. Which database should I use?

Existing PostgreSQL. Do not introduce another database.

## Q25. Should I create a new database layer?

No. Reuse existing SQLAlchemy Base, PostgreSQL engine and bounded connection
pool, Alembic migration chain, tenant authentication middleware, RLS context,
and safety utilities.

## Q26. How should persistence be implemented?

Use `finance/reconciliation/persistence.py` with plain functions:
create_import_session, get_import_session, upload_source_file,
persist_ingestion_report, start_reconciliation, get_run, list_exceptions,
record_decision, get_audit_events. Keep functions focused and tenant-scoped.
Do not create a generic persistence framework.

## Q27. Should run results be persisted in one transaction?

Yes. Persist run, matches, payout allocations, allocation legs, exceptions,
and completed state together. Commit them together. If any persistence step
fails, roll back the entire transaction.

## Q28. Should reconciliation computation occur inside the database transaction?

Prefer no. Sequence: load and validate canonical inputs, execute deterministic
reconciliation, open persistence transaction, persist the complete output,
commit. Do not hold database locks while performing expensive computation.

## Q29. What if reconciliation computation crashes?

No completed run should be persisted. A retry can recompute from the same
canonical inputs.

## Q30. How should idempotency work?

Use existing idempotency infrastructure and database uniqueness constraints.
Application-level checking alone is insufficient. For concurrent identical
requests, one claims the operation and the other receives the existing result
or the documented conflict response. Never silently return an unrelated
previous result.

## Q31. Should raw uploaded files be stored?

Only where necessary for source retention and reproducibility. Reuse the
existing S3 adapter. Do not build a new object-storage abstraction. Use
content digests to identify identical content.

## Q32. Should every import be retained forever?

Do not introduce a retention policy beyond the approved requirements. Preserve
sufficient source evidence and provenance for reproducibility.

## Q33. Should every API operation be generic CRUD?

No. Expose only the workflow operations required by the product. Prefer
explicit endpoints over generic database-shaped APIs.

## Q34. What tenant ID should API requests use?

Tenant identity must be established by the existing server-side authentication
and tenant context mechanisms. Never treat a request-body tenant ID as
authorization. The current header-based demo identity is not production
authentication.

## Q35. Are seeded demo tenants authenticated users?

No. Demo tenant rows provide deterministic test identities and tenant records.
Their existence does not prove user authentication. Real authentication remains
a separately scoped production-readiness requirement.

## Q36. How should RLS be handled?

Reuse existing RLS mechanisms. Every tenant-scoped table must have the required
isolation policy. Test: Tenant A cannot read Tenant B's records, Tenant A
cannot mutate Tenant B's records, missing tenant context fails closed, pooled
connections do not leak tenant context. Do not bypass RLS using privileged
database access in normal request handling.

## Q37. Should I implement full audit functionality?

Implement the minimum audit behavior needed to establish traceability. Audit
consequential operations: import, reconciliation execution, exception
decisions, investigation results where appropriate, export generation.
Preserve append-only behavior. Use tenant-scoped retrieval. Do not build a
general enterprise audit analytics platform.

---

# 6. P3 — Exception lifecycle

## Q38. Who owns exception resolution?

A human operator. The application records and enforces the decision. AI does
not resolve exceptions autonomously.

## Q39. Can I invent additional exception statuses?

No. Use the approved state machine. If an essential transition is missing,
report the gap before changing the contract.

## Q40. What information should a human decision preserve?

At minimum: decision, actor, timestamp, reason, related exception, relevant
evidence or provenance. Preserve decision history. Do not overwrite historical
decisions.

## Q41. Can an operator resolve the same exception twice?

Enforce valid state transitions and concurrency protection. Duplicate requests
must not create contradictory history.

## Q42. Should I build configurable approval workflows?

No. A straightforward exception lifecycle is sufficient.

---

# 7. P4 — AI investigation

## Q43. What is AI allowed to do?

AI may explain discrepancies, summarize relevant evidence, identify
conflicting evidence, explain plausible causes with appropriate qualification,
identify missing evidence, and recommend what an operator should inspect next.

## Q44. What is AI forbidden from doing?

AI must not invent financial values, recalculate authoritative financial
outcomes, modify reconciliation results, change exception state autonomously,
execute money movement, override deterministic matching, or treat unsupported
assumptions as facts.

## Q45. Should I introduce multiple agents?

No. Use the existing shared LLM infrastructure. One bounded investigation
workflow is enough.

## Q46. What if the LLM provider is unavailable?

The deterministic application must continue working. AI investigation should
fail independently and safely. An unavailable LLM must not prevent
reconciliation, match inspection, exception retrieval, human decisions, or
report export.

## Q47. What if evidence is insufficient?

Abstain. Return an explicit insufficient-evidence result. Do not fabricate a
likely explanation.

## Q48. How should AI results be stored?

Preserve investigation identifier, associated exception, evidence references,
model/provider metadata where available, structured findings, abstention
status, timestamp, and relevant provenance. Follow the approved domain model
and privacy boundary.

## Q49. Do we need traditional ML?

No. Traditional ML is explicitly out of scope. Deterministic analytics and
bounded LLM investigation are sufficient.

---

# 8. P5 — User interface

## Q50. Should I migrate to React or Next.js?

No. Keep NiceGUI.

## Q51. Should I redesign the entire application?

No. Build only the reconciliation workflow.

## Q52. What screens are required?

Reconciliation overview, source import and validation preview, reconciliation
execution, match and payout allocation inspection, exception list, exception
investigation, human decision interface, report export. Combine screens where
it improves usability without obscuring the workflow.

## Q53. Should I build a complex design system?

No. Reuse existing UI conventions. Prioritize clear financial values, visible
reconciliation status, explainable discrepancies, source evidence, actionable
validation messages, and clear exception decisions.

## Q54. Should the UI calculate reconciliation outcomes?

No. The backend deterministic engine owns financial decisions. The UI
presents backend results.

---

# 9. P6 — Integration, reliability and staging

## Q55. What must the end-to-end test prove?

Starting from an empty or clean demo environment: import invoice data, import
Stripe transactions, import bank deposits, validate and normalize, run
reconciliation, retrieve matches and allocations, inspect exceptions, record
human decisions, retrieve audit history, export the report. Verify persisted
results survive an application restart.

## Q56. Do we need a distributed queue?

No. The current workload does not justify it.

## Q57. Do we need Kubernetes?

No.

## Q58. Do we need cloud deployment?

Not for the portfolio release. A reproducible local Docker Compose environment
is sufficient.

## Q59. Do we need full observability infrastructure?

No. Retain useful structured logs, request IDs, readiness checks, and the
minimum metrics required to diagnose the application. Do not introduce a
complete monitoring platform.

## Q60. What about the /metrics endpoint?

Follow the observability specification and inspect existing capabilities
first. Implement the smallest compatible solution. Do not create a second
metrics system.

## Q61. What about staging Make targets?

Implement only the documented staging targets needed for the actual local
workflow. Do not create decorative or unused commands.

## Q62. What about backups and disaster recovery?

Demonstrate the required persistence and restart behavior. Do not build
enterprise backup orchestration. Document backup and restore limitations
honestly.

---

# 10. P7 — Portfolio release

## Q63. What makes FinSight ready for portfolio release?

A clean clone can: install dependencies, start the application, initialize
PostgreSQL, apply migrations, load demo data, execute the full workflow,
inspect results and exceptions, view audit history, export results, run the
relevant test suites. The documentation must clearly state security and
deployment limitations.

## Q64. Do we need a live production cloud deployment?

No. Do not spend time on cloud deployment unless specifically authorized.

## Q65. Do we need billing, subscriptions or customer onboarding?

No.

## Q66. Do we need enterprise compliance certification?

No. Do not claim certifications or security guarantees that have not been
independently verified.

---

# 11. Testing standards

## Q67. Is a passing test suite enough?

No. Tests must verify actual behavior. Follow the anti-slop testing standard
in AGENTS.md.

## Q68. What types of tests are expected?

Use the smallest relevant combination of: unit tests, contract tests,
integration tests, HTTP end-to-end tests, database/RLS tests,
failure-injection tests, metamorphic tests, mutation tests where risk
justifies them, property-based tests for high-value financial invariants. Do
not add a test category solely for its name.

## Q69. Can I remove a failing test?

Only if the test is demonstrably obsolete or invalid. Explain why. Never
remove a test merely because implementation does not satisfy it.

## Q70. Can I weaken assertions to make CI green?

No.

## Q71. Can I update golden evidence?

Only when a legitimate behavioral change is approved and independently
justified. Do not regenerate expected outputs simply to match a broken
implementation.

## Q72. What if the baseline already has type errors?

Compare against the recorded baseline. Do not claim zero errors when there are
existing errors. Report new errors separately.

## Q73. What if a test is flaky?

Reproduce it, identify the cause, and fix the underlying issue. Do not
silently skip it or retry indefinitely.

---

# 12. Migrations and database questions

## Q74. Should I modify an already-applied migration?

No. Create a new migration.

## Q75. Should migrations be reversible?

Where practical, yes. Test upgrade and downgrade behavior. If a destructive
downgrade cannot preserve data, document the limitation.

## Q76. Can a migration seed demo tenants?

Yes, using deterministic reviewed seed definitions. Do not overwrite existing
tenant data. Do not use arbitrary mutable filesystem data as a migration-time
source of truth.

## Q77. Should every table have tenant_id?

Not necessarily. Follow the approved schema. Every tenant-owned record must
have an enforceable tenant ownership relationship and isolation boundary.

## Q78. Should I add indexes everywhere?

No. Add indexes based on actual query patterns, foreign keys, uniqueness
requirements, tenant-scoped retrieval, and demonstrated performance needs.
Avoid speculative indexing.

---

# 13. Security and data handling

## Q79. Can I trust user-provided filenames or metadata?

No. Validate and constrain them. Never use raw user-controlled paths for
filesystem access.

## Q80. Can I log financial source records?

Avoid logging raw financial data. Log identifiers, request IDs, outcomes, and
safe diagnostics. Follow the existing privacy boundary.

## Q81. Can I expose S3 object URLs directly?

Only if the existing security design explicitly permits it. Prefer controlled
server-side access. Never expose credentials or unrestricted object locations.

## Q82. Should I implement rate limiting?

Only where the existing architecture or actual threat model requires it. Do
not build a comprehensive API gateway.

## Q83. Should I implement production authentication immediately?

No, unless required by the current task. The portfolio workflow may use the
existing demo identity mechanism, but documentation must not misrepresent it
as real authentication. Production authentication remains an explicit
limitation.

---

# 14. Error handling and operational behavior

## Q84. Should errors expose internal exceptions?

No. Return safe, structured API errors. Keep detailed diagnostics in
protected server logs.

## Q85. Should the system silently retry every failure?

No. Retry only operations that are safe to retry. Respect idempotency. Do not
retry deterministic validation errors as though they were transient
infrastructure failures.

## Q86. What happens when PostgreSQL is unavailable?

The application must report unavailable readiness and avoid pretending that
writes succeeded.

## Q87. What happens when object storage is unavailable?

Follow the defined raw-file retention behavior. Do not claim source retention
succeeded when it did not. Keep the reconciliation engine independent of
storage-provider availability where the required canonical input is already
available.

---

# 15. Deslop slices 8–10

## Q88. Can I delete a module because it looks unused?

No. Verify direct imports, indirect imports, dynamic imports, entry points,
tests, CI workflows, configuration, runtime references, and documentation
references. Then classify the module.

## Q89. What must Slice 8 preserve?

All live finance capabilities required by the target reconciliation product
and its supporting runtime. Do not delete shared financial functionality
simply because it belongs to an FP&A-oriented directory.

## Q90. What must Slice 9 preserve?

Normative product and architecture specifications, implementation guidance,
and essential release documentation. Remove obsolete or duplicated
documentation only after checking references.

## Q91. What must Slice 10 prove?

The actual runtime boundary matches the intended product boundary. Use
computed evidence, not manually maintained claims. Preserve the
reconciliation engine and protected tests.

---

# 16. Dependencies and new technology

## Q92. Can I add a new Python dependency?

Only when the existing standard library or installed dependencies cannot
reasonably satisfy the requirement. Before adding: check whether an existing
dependency already provides the functionality, evaluate maintenance and
security implications, add only the minimum dependency, update lockfiles,
verify licensing and compatibility, run the complete relevant test suite.

## Q93. Can I introduce Redis?

No, not without a demonstrated requirement.

## Q94. Can I introduce Celery, Kafka or RabbitMQ?

No, not for the current workflow.

## Q95. Can I add another ORM or database abstraction?

No. Use the existing SQLAlchemy infrastructure.

## Q96. Can I add a second LLM provider framework?

No. Reuse shared/llm.

---

# 17. Git, CI and delivery

## Q97. Should I work on the approved feature branch?

Yes. Target branch: `feat/reconciliation-three-source-workflow`. Do not
accidentally implement features on main or another branch.

## Q98. Can I merge PR #129?

No. It remains draft and requires the separately mandated non-author
CI-owner approval. Do not bypass verification policy.

## Q99. Can I commit changes automatically?

Normal task-level commits are allowed within the approved workstream. Use
clear, scoped commit messages. Do not rewrite shared history or force-push
without authorization.

## Q100. Can I proceed if CI is green?

Yes, if the task's completion criteria are met and no pause condition
applies. Green CI alone does not prove production readiness.

## Q101. What if a CI failure is unrelated to my changes?

Verify it against the baseline. Do not hide, skip, or weaken the gate.
Report the evidence and proceed only if the failure is genuinely unrelated and
the standing verification policy permits it.

---

# 18. Autonomous decision-making

## Q102. When should I make a decision without asking?

Make the decision independently when it is reversible, stays inside approved
scope, preserves financial behavior, follows existing architectural
conventions, does not introduce material security risk, and can be validated
through tests. Record material decisions in the implementation report.

## Q103. When must I stop and ask?

Pause only when product scope must change, an approved specification is
materially contradictory, financial correctness could be compromised, a
security boundary must be weakened, a destructive or irreversible action is
necessary, credentials or paid services or public data exposure are involved,
merge or release or deployment authorization is required, or a decision cannot
be made safely using existing evidence. Do not ask about routine naming,
function signatures, file organization, ordinary test design, or reversible
implementation details.

## Q104. What if the specification does not answer a minor question?

Use this priority: approved specification, existing implementation and
conventions, existing tests and behavioral contracts, this playbook, simplest
reversible implementation. Document the decision.

## Q105. What if two documents conflict?

Do not arbitrarily choose one. Use the normative specification and product
scope as the authority. Record the conflict and escalate if it affects
financial behavior, security, or externally visible contracts.

## Q106. What if a task turns out to be unnecessary?

Do not implement it merely because it appears in an old plan. Provide evidence,
record the disposition, and continue with the actual required workflow.

## Q107. What if I discover a better architecture?

Do not redesign the system during an implementation task. Compare the proposal
against the current approach. If the difference is material, document the
tradeoff and seek authorization.

---

# 19. Completion reporting

Every meaningful task or phase must produce a concise report containing:
commit SHA, files added/changed/removed, approximate LOC added and removed,
tests added/removed/executed, type-check results, CI results, database
migration results where applicable, security and tenant-isolation evidence
where applicable, specification deviations, remaining limitations, next task
and its authorization status. Distinguish clearly between implemented,
tested, verified, planned, deferred, and not applicable. Never claim
production readiness solely because tests pass.

---

# 20. Final definition of done

FinSight is complete when: the three-source workflow works end to end,
financial reconciliation remains deterministic and correct, imports and runs
persist reliably, tenant boundaries are demonstrated through tests, exceptions
support human resolution, AI provides bounded evidence-grounded explanations,
the NiceGUI interface supports the complete workflow, audit history and
exports work, restart and failure behavior are verified, a developer can
reproduce the demonstration from a clean checkout, relevant CI and behavioral
contracts pass, and limitations and deferred capabilities are documented.

Do not extend the project simply to increase feature count. The objective is
a complete, credible reconciliation application, not an imitation of every
capability found in enterprise financial software.

---

# Standing instruction

Execute the approved P2–P7 roadmap in dependency order. Continue through
routine tasks without requesting repeated approval. Prefer reuse, small
changes, and measurable outcomes. Stop for user input only at the explicit
pause conditions in this document. When the defined portfolio workflow is
complete, stop building and prepare the release evidence.

## Additional instructions for the coding agent

1. The playbook is not a replacement for the eight specifications. If
   implementation behavior is defined in `docs/specs/`, follow that
   specification.
2. The agent must inspect the actual repository at the current branch HEAD.
   Historical reports and earlier commit SHAs are not proof of current
   implementation.
3. Do not implement all P2–P7 in one giant change. Complete small vertical
   milestones, verify them, then continue.
4. Do not manufacture work to satisfy a roadmap. If an existing capability
   already satisfies a requirement, reuse it and provide evidence.
5. Do not interpret autonomous execution as permission to merge or deploy.
   Those remain separate authorization boundaries.

---

# Standing execution policy (from AGENTS.md)

Once a phase is authorized, execute its bounded tasks in dependency order
without requesting approval for every subtask. Make reversible, bounded
implementation decisions within approved specifications. Pause only for:
product scope or core architecture changes; material security or financial
correctness tradeoffs; irreversible destructive actions; contradictions in
approved specifications; external services, credentials, costs, or public data
exposure; merge, release, or deployment actions requiring explicit
authorization.

### Engineering standard

1. Reuse existing modules before building replacements.
2. Prefer plain functions and existing application patterns over new
   frameworks.
3. Build the smallest implementation that satisfies the requirement.
4. Do not introduce speculative infrastructure.
5. Keep deterministic financial computation authoritative.
6. Use Decimal for financial arithmetic.
7. Preserve tenant isolation, provenance, and auditability.
8. LLMs may explain evidence but cannot determine or mutate financial
   outcomes.
9. Distinguish implemented, planned, and verified capabilities.
10. Do not weaken existing tests or protected reconciliation invariants to
    make CI pass.

### Scope exclusions

No traditional ML, generic multi-agent platform, autonomous money movement,
Kubernetes, microservices, generic ETL framework, enterprise IAM, or
unrelated FP&A feature expansion unless separately authorized.

### Completion reporting

At each meaningful milestone report: commit SHA, files added/changed/removed,
approximate LOC added and removed, tests added/removed/executed, type-check
results, CI results, database migration results where applicable, security and
tenant-isolation evidence where applicable, specification deviations,
remaining limitations, next task and its authorization status.

### Engineering decisions, FAQs, constraints and execution rules

This document works alongside `AGENTS.md`. `AGENTS.md` establishes the rules;
this playbook answers the questions likely to arise while implementing P2–P7.
