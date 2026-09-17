# FinSight

### Agentic Financial Operations for a Realistic Legacy Enterprise

> **An internal financial resolution system built for a single hypothetical company — Meridian Commerce Pvt. Ltd. — that investigates settlement discrepancies across fragmented financial systems and drives them to an evidence-backed, authorized, and deterministically verified outcome.**

FinSight is a portfolio implementation of how a **Forward-Deployed Engineer (FDE)** can enter an existing company's environment, understand its business process and system constraints, integrate with heterogeneous systems, and build a narrowly scoped AI solution around the company's actual operational problem.

It is deliberately **not a generic AI CFO, accounting SaaS, or autonomous financial agent**.

---

## The Problem

Meridian Commerce is a hypothetical Indian B2B commerce/payment-enabled company.

Its finance operation already has the software it needs:

```text
                    MERIDIAN COMMERCE

      ┌─────────────┬─────────────┬──────────────┐
      │             │             │              │
      ▼             ▼             ▼              ▼
  Razorpay      QuickBooks    Google Sheets    Gmail
      │             │             │              │
      └─────────────┴─────────────┴──────────────┘
                         │
                         ▼
                   Finance Operations
                         │
                       Slack
                         │
                         ▼
              ┌──────────────────────┐
              │  LEGACY LEDGER       │
              │  COBOL / Batch       │
              │  Fixed-width files   │
              │  No HTTP / Internet  │
              └──────────────────────┘
```

The problem is not missing data.

The problem is **fragmented reasoning**.

A single settlement can appear under different identifiers and in different representations across payment, accounting, operational, communication, and legacy systems. Finance staff must manually correlate those sources, determine whether a discrepancy is legitimate, investigate its cause, decide what correction is appropriate, obtain authorization, execute it, and verify that the financial state was actually fixed.

FinSight addresses that specific workflow.

---

# What FinSight Does

FinSight takes a financial discrepancy from:

```text
DETECT
   ↓
RECONCILE
   ↓
INVESTIGATE
   ↓
CORRELATE EVIDENCE
   ↓
EXPLAIN SUPPORTED CAUSE
   ↓
PROPOSE RESOLUTION
   ↓
DETERMINISTIC VALIDATION
   ↓
POLICY DECISION
   ↓
HUMAN APPROVAL WHEN REQUIRED
   ↓
EXECUTE
   ↓
RECONCILE AGAIN
   ↓
AUTHORITATIVE VERIFICATION
   ↓
CLOSE
```

The objective is not to make the LLM "good at finance."

The objective is to make the **system capable of safely resolving a financial situation despite incomplete, heterogeneous, asynchronous, and partially unstructured evidence**.

---

# Core Thesis

## Financial systems contain facts.

## FinSight determines what financial situation those facts create, what evidence explains the situation, and what safe resolution follows.

The architecture deliberately separates **cognition from financial authority**.

```text
┌───────────────────────────────────────────────┐
│                 FINANCIAL TRUTH               │
│                                               │
│  Arithmetic · Matching · Policy · State      │
│  Authorization · Execution · Verification    │
│                                               │
│              DETERMINISTIC CODE               │
└───────────────────────┬───────────────────────┘
                        │
                        │ typed facts / capabilities
                        ▼
┌───────────────────────────────────────────────┐
│                COGNITIVE LAYER                │
│                                               │
│  Interpretation · Investigation · Hypotheses │
│  Evidence synthesis · Investigation planning │
│  Resolution proposal                          │
│                                               │
│                    LLM                        │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
              Deterministic validation
                        │
                        ▼
                 Human authority
                        │
                        ▼
                Controlled execution
                        │
                        ▼
            Authoritative verification
```

The LLM is a **bounded investigator**, not the financial authority.

---

# Why This Is an Agentic Problem

The hard problem is not calculating a number.

For example:

```text
What is the net settlement?
        → deterministic

Does ₹X equal ₹Y?
        → deterministic

Is the accounting period open?
        → deterministic

Why do the systems disagree?
        → potentially agentic

Which evidence should be investigated next?
        → potentially agentic

Which hypothesis best explains the available evidence?
        → potentially agentic

Is the available evidence sufficient to construct a proposal?
        → agentic + deterministic verification
```

The agent operates where the problem involves **semantic ambiguity, incomplete context, distributed evidence, and dynamic investigation paths**.

It does not replace deterministic computation or authorization.

---

# The Meridian Environment

| System        | Role                    | Authority                                                              |
| ------------- | ----------------------- | ---------------------------------------------------------------------- |
| Razorpay      | Payment provider        | Payments, refunds, settlements                                         |
| QuickBooks    | Accounting              | Accounting entries and account state                                   |
| Google Sheets | Operational intent      | Expected settlement and operational mappings                           |
| Gmail         | Human/business context  | Communication/context                                                  |
| Slack         | Human authority         | Approval and coordination                                              |
| COBOL ledger  | Legacy financial system | Legacy postings and batch results                                      |
| FinSight      | Reasoning/control layer | Cases, evidence, hypotheses, proposals, decisions, verification, audit |

FinSight does **not** replace these systems.

It operates across them as a reasoning and control layer.

---

# Flagship Case: FS-231

The primary end-to-end case is a settlement discrepancy spanning modern and legacy systems.

### Initial state

```text
Google Sheets expected       ₹10,00,000
Razorpay settlement          ₹ 9,72,500
QuickBooks                   ₹ 9,82,500
Legacy ledger                ₹ 9,82,500
```

The initial provider-to-accounting variance is:

```text
₹9,82,500 − ₹9,72,500 = ₹10,000
```

FinSight must **not** interpret the larger expected-to-provider difference as a missing amount. The provider settlement must first be decomposed into its financial components and correlated with downstream records.

Investigation identifies:

```text
Razorpay
├── Gross                  ₹10,00,000
├── Processing fee         ₹  7,500
├── Refund                 ₹  2,500
└── Settlement adjustment  ₹ 10,000

QuickBooks
├── Fee                    PRESENT
├── Refund                 PRESENT
└── Adjustment             ABSENT

Legacy batch
└── Adjustment             REJECTED
                           INVALID_ACCOUNT_CODE
```

The supported cause is:

> The ₹10,000 settlement adjustment was not posted downstream because the legacy batch rejected it.

FinSight then constructs a typed resolution proposal, passes it through deterministic validation and policy, obtains human authorization where required, executes through the controlled legacy boundary, and verifies the resulting authoritative state before closure.

---

# The Legacy Constraint

The legacy system is intentionally not a fake REST service.

It represents a realistic integration boundary:

```text
FinSight
   │
   ▼
Fixed-width outbound batch
   │
   ▼
Controlled transfer boundary
   │
   ▼
COBOL batch processor
   │
   ├── accepted records
   └── rejected records
   │
   ▼
Result files
   │
   ▼
FinSight ingestion
   │
   ▼
Canonical LegacyBatch / LegacyRecord
```

The modern application acts as an **anti-corruption boundary** around the legacy system.

It handles:

* fixed-width serialization
* schema validation
* control totals
* batch identity
* idempotency
* structured errors
* accepted/rejected records
* result ingestion

The agent never receives raw legacy file syntax as a domain capability.

---

# Architecture

```text
                         MERIDIAN SYSTEMS
                              │
        ┌───────────┬─────────┼─────────┬───────────┐
        ▼           ▼         ▼         ▼           ▼
    Razorpay    QuickBooks  Sheets    Gmail       Slack
        │           │         │         │           │
        └───────────┴─────────┴─────────┴───────────┘
                              │
                              ▼
                  ┌─────────────────────┐
                  │     FinSight Core    │
                  │                     │
                  │ Canonical Domain     │
                  │ Reconciliation      │
                  │ FinancialSituation  │
                  │ Evidence            │
                  │ Policy              │
                  │ Audit               │
                  └──────────┬──────────┘
                             │
                             ▼
                  ┌─────────────────────┐
                  │ Cognitive Runtime   │
                  │                     │
                  │ Investigation       │
                  │ Hypotheses          │
                  │ Evidence synthesis  │
                  │ Resolution proposal │
                  └──────────┬──────────┘
                             │
                             ▼
                  Deterministic Verifier
                             │
                             ▼
                     Human Authority
                             │
                             ▼
                    Controlled Actions
                       │           │
                       ▼           ▼
                  Financial     Legacy
                    APIs        Batch
                       │           │
                       └─────┬─────┘
                             ▼
                    Authoritative Readback
                             │
                             ▼
                     Reconciliation
                             │
                             ▼
                           CLOSE
```

---

# FinancialSituation

The central domain object is not a payment.

It is the **FinancialSituation**: the operational representation of a financial discrepancy and its lifecycle.

This lets the system reason about:

* what happened
* what systems disagree
* what evidence exists
* what hypotheses have been considered
* what resolution has been proposed
* what authorization exists
* what action occurred
* whether the resulting financial state is actually correct

The lifecycle is deterministic.

```text
DETECTED
   ↓
TRIAGED
   ↓
INVESTIGATING
   ↓
EVIDENCE_READY
   ↓
EVIDENCE_VERIFIED
   ↓
PROPOSED
   ↓
AWAITING_APPROVAL
   ↓
APPROVED
   ↓
EXECUTING
   ↓
POST_VERIFYING
   ↓
EXECUTION_VERIFIED
   ↓
CLOSED
```

Escalation and failure paths are first-class states/transitions rather than exceptional afterthoughts.

---

# Business-Outcome-First Engineering

FinSight does not treat a green test suite as proof that the business model is correct.

The engineering sequence is:

```text
Business outcome
       ↓
Business invariant
       ↓
Business state semantics
       ↓
Allowed / forbidden outcomes
       ↓
Acceptance scenarios
       ↓
Tests
       ↓
Implementation
```

Tests therefore exist to encode the **business contract**, not to justify an implementation that was written first.

For example:

> "A situation reached `CLOSED`."

is not a sufficient acceptance criterion.

The meaningful question is:

> **"Is the financial discrepancy actually resolved, and can the system prove why closure is justified?"**

This distinction is particularly important for financial workflows where a numerically plausible result can still represent an incorrect business outcome.

---

# Deterministic vs. Probabilistic Boundary

FinSight deliberately keeps the deterministic core large.

### Deterministic

* Money arithmetic
* Decimal handling
* Normalization
* Entity matching
* Reconciliation
* Financial state
* State transitions
* Business rules
* Authorization
* Policy evaluation
* Idempotency
* Action execution
* Post-action verification
* Auditability

### Agentic / probabilistic

* Interpretation of ambiguous business context
* Hypothesis generation
* Investigation planning
* Selecting the next bounded investigation
* Evidence synthesis
* Resolution proposal generation

The agent's output is **typed candidate data**, not authorization.

The deterministic control plane decides whether that candidate can proceed.

---

# Security and Trust Model

FinSight treats external content as **data, not instructions**.

Evidence can originate from:

* emails
* spreadsheets
* payment metadata
* accounting records
* legacy outputs
* operational notes

Untrusted content cannot modify:

* actor identity
* authorization
* capabilities
* tenant/company scope
* policy
* financial state
* tool permissions

The system maintains explicit boundaries between:

```text
Authenticated actor
        ↓
RBAC
        ↓
Case / evidence scope
        ↓
Business policy
        ↓
Approval
        ↓
Execution
```

Additional controls include:

* immutable evidence provenance
* content hashing
* deterministic grounding verification
* prompt-injection defenses
* secret/PII redaction
* idempotency
* concurrency protection
* audit lineage
* fail-closed behavior
* mandatory post-execution verification

---

# Human-in-the-Loop

Human approval is not a fallback for an unreliable AI.

It is an **authority boundary**.

The system prepares a decision-ready case containing:

```text
Financial situation
      +
Verified evidence
      +
Supported explanation
      +
Resolution proposal
      +
Deterministic validation
      +
Policy result
      +
Risk / authorization requirements
```

The human supplies:

* authority
* accountability
* business judgment

The system supplies the investigation and preparation work.

Consequential actions cannot be authorized merely because the model is confident.

---

# Failure Is Part of the Design

Financial systems cannot assume that distributed operations succeed cleanly.

FinSight explicitly models cases such as:

| Failure                               | Required behavior                              |
| ------------------------------------- | ---------------------------------------------- |
| Duplicate webhook                     | Deduplicate by provider event ID               |
| Provider timeout after action request | Mark `UNKNOWN`, query provider before retry    |
| Duplicate legacy batch                | Reject through idempotency/hash/control record |
| Partial legacy batch                  | Preserve per-record results                    |
| Late legacy result                    | Keep situation open until result arrives       |
| Conflicting authoritative records     | Escalate; do not guess                         |
| Unsupported account code              | Block legacy submission                        |
| Closed accounting period              | Block correction                               |
| Already-refunded payment              | Block second refund                            |
| Insufficient evidence                 | Escalate without executable proposal           |
| Unsupported model claim               | Prevent progression to verified state          |

These are business outcomes, not merely technical exceptions.

---

# Current Engineering Milestones

## P1 — Deterministic Reconciliation Core

**Complete**

Frozen generic reconciliation primitives provide the deterministic foundation.

---

## P4 — Bounded Agent Boundary

**Complete**

The LLM is constrained to:

* interpretation
* hypothesis generation
* investigation planning
* bounded capability selection
* evidence synthesis

The agent cannot directly mutate financial state.

---

## P5 — Trust & Security

**Complete**

Checkpoint:

```text
finsight-p5-security
071589b5460429700b9a75783d1ebbe8d0709b32
```

P5 established the trust, grounding, isolation, prompt-injection, secret-handling, trajectory, observability, legacy-protocol, and regression boundaries.

---

## P6-01 — Meridian Domain Contract

**Merged**

Defined:

* Meridian process model
* canonical domain concepts
* FinancialSituation aggregate
* reconciliation contract
* company-specific business rules
* integration contract matrix
* FS-231 fixtures

The implementation deliberately wraps the frozen P1 core rather than modifying it.

---

## P6-02 — Deterministic FinancialSituation Lifecycle

**In progress**

Scope:

* business-state semantics
* deterministic transitions
* lifecycle invariants
* persistence and aggregate behavior
* audit events
* invalid-transition handling
* concurrency semantics
* FS-231 lifecycle outcomes

Explicitly outside this slice:

* new LLM behavior
* AWS infrastructure
* new security abstractions
* financial mutations

The lifecycle is being evaluated from **business outcomes first**, with tests serving as executable business contracts.

---

# Planned Build Sequence

```text
P6-02
Deterministic FinancialSituation lifecycle
        ↓
P6-03
Reconciliation / discrepancy engine
        ↓
P6-04
Integration contracts + realistic adapters
        ↓
P6-05
Evidence-driven investigation
        ↓
P6-06
FS-231 complete investigation path
        ↓
P6-07
Controlled proposal / approval / execution
        ↓
P6-08
Legacy end-to-end execution
        ↓
P6-09
Failure / recovery / adversarial E2E
        ↓
P6-10
AWS production-shaped deployment
```

The exact phase boundaries may evolve as the business model is validated.

---

# Technology Direction

The implementation intentionally favors boring, explicit engineering where financial correctness matters.

### Core

* Python
* FastAPI
* Pydantic
* PostgreSQL
* Decimal-based financial representation
* deterministic domain services
* repository / adapter boundaries

### Agentic layer

* bounded LLM provider abstraction
* structured outputs
* constrained investigation plans
* typed capability registry
* evidence-grounded verification
* bounded replanning

### Legacy

* COBOL-style batch simulation
* fixed-width protocol
* controlled file boundary
* accepted/rejected records
* batch control totals
* idempotency and correlation

### Infrastructure

The production target is AWS.

Local infrastructure contracts are validated before introducing managed AWS dependencies.

---

# Observability

FinSight separates application instrumentation from observability vendors.

```text
Application
    ↓
FinSight TracerProtocol
    ↓
OpenTelemetry
    ↓
Observability backend
```

The observability layer must never determine financial outcomes.

If the tracing backend disappears:

```text
Financial result = unchanged
Authorization     = unchanged
Execution         = unchanged
State transition  = unchanged
```

Observability is evidence about system behavior, not part of the financial control path.

---

# What FinSight Is Not

FinSight is deliberately **not**:

* an accounting system
* a general ledger
* an ERP
* a payment gateway
* a generic AI CFO
* a financial chatbot
* a generic autonomous agent with unrestricted API access
* a forecasting platform
* an OCR/document-processing platform
* a configurable SaaS workflow builder
* a replacement for human financial authority

The project intentionally solves one bounded enterprise problem rather than creating a configurable platform.

---

# Why This Is an FDE Portfolio Project

The reusable artifact is not a generic SaaS product.

The reusable artifact is the **engineering approach**:

```text
Understand the company
        ↓
Understand the business process
        ↓
Map existing systems
        ↓
Identify authoritative sources
        ↓
Define the ontology
        ↓
Find the actual operational bottleneck
        ↓
Design around existing constraints
        ↓
Build deterministic foundations
        ↓
Introduce AI only where ambiguity exists
        ↓
Integrate with existing systems
        ↓
Control authority and risk
        ↓
Measure business outcomes
```

A different customer would not simply configure FinSight with dozens of switches.

An FDE would perform discovery again and build the appropriate solution around that customer's actual systems and process.

That is intentional.

---

# Success Metrics

FinSight is evaluated on **business outcomes**, not arbitrary AI activity metrics.

Primary metrics include:

* exception auto-resolution rate
* human touch rate
* median detection-to-verified-resolution time
* financial exposure resolved
* false resolution rate
* duplicate action rate
* verification success rate
* LLM calls per resolved case
* deterministic execution ratio

The primary proof is:

> **Did the financial situation reach the correct verified business outcome?**

Not:

> "Did the model produce a convincing answer?"

---

# Repository Philosophy

FinSight follows several engineering principles:

### 1. Business truth before implementation

Define the business outcome and invariants before writing the test or implementation.

### 2. Deterministic by default

If a rule can be expressed explicitly, encode it explicitly.

### 3. Probabilistic only where necessary

Use the LLM for ambiguity and investigation, not arithmetic or authority.

### 4. Evidence before claims

Material claims must be grounded in source-backed evidence.

### 5. Proposal is not authorization

An agent-generated proposal remains a candidate until deterministic validation and the required authority boundary are satisfied.

### 6. Execution is not verification

An external API or batch reporting success is not itself proof that financial state is correct.

### 7. Closure requires proof

A situation is closed only after its required business outcome has been independently verified.

### 8. Failure is a state

Timeouts, partial processing, conflicts, retries, and late results must have explicit semantics.

### 9. Existing systems remain authoritative

FinSight coordinates and reasons across systems; it does not silently replace their authority.

### 10. Narrow systems are easier to trust

The system is intentionally bounded to one company, one primary workflow, finite entities, finite capabilities, and finite policies.

---

# Project Status

**Current milestone: P6 — Domain → Deterministic Financial Execution**

```text
P1  Deterministic Core             ✓
P4  Bounded Agent Boundary         ✓
P5  Trust & Security               ✓
P6-01 Meridian Domain Contract     ✓
P6-02 FinancialSituation Lifecycle → In progress
```

---

## The One-Sentence Definition

> **FinSight is a single-company agentic financial operations system that investigates fragmented settlement discrepancies and turns them into evidence-backed, policy-controlled, human-authorized when necessary, and deterministically verified financial outcomes — without giving the LLM authority over financial truth.**
