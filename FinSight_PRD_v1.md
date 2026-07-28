# FinSight Product Requirements Document
## v1.0 — Autonomous FP&A Control System

---

## 1. Product Vision

FinSight is an event-driven autonomous vertical agentic AI system for Financial Planning & Analysis. It continuously monitors financial and operational data sources, detects material variances, investigates root causes through structured driver trees, drafts evidence-backed commentary and recommended actions, and routes findings through governed approval workflows. Upon human approval, it executes allowed actions: publishing management packs, creating owner tasks, and applying low-risk forecast assumption updates. Between close cycles, it monitors for threshold breaches, forecast drift, and data anomalies — initiating proactive investigation without waiting for human prompts.

FinSight does not assist with FP&A. It performs FP&A under policy and human governance.

---

## 2. Problem Statement

FP&A teams spend 60-70% of close time on mechanical work: importing actuals, reconciling sources, scanning for variances, chasing owners for explanations, writing repetitive commentary, and formatting reports. This leaves insufficient time for strategic analysis, scenario modeling, and decision support.

Existing AI tools in this space are copilots: they generate text when asked. They do not own the workflow, enforce data quality, validate claims against evidence, route decisions, or execute actions. They produce drafts, not outcomes.

FinSight solves this by becoming a governed digital operator that runs the variance-to-action loop autonomously within explicit boundaries.

---

## 3. Target Users

| Role | Primary Need | Interaction Mode |
|---|---|---|
| FP&A Analyst | Owns variance investigation and commentary | Reviews agent drafts, provides context, approves findings |
| FP&A Manager | Owns close process and team coordination | Sets policies, monitors progress, handles escalations |
| Controller / CFO | Owns published outputs and financial integrity | Final approval on packs, audit review, exception handling |
| Business Unit Leader | Owns operational drivers | Receives action tasks, provides driver explanations |
| Data / Finance Ops | Owns source data quality | Receives data quality alerts, manages connector health |

---

## 4. Core Capabilities

### 4.1 Sense Layer
- Continuous monitoring of ERP, CRM, accounting, HRIS, billing, spreadsheet, and manual upload sources
- Data quality validation: trial balance balance, FX rate presence, mapping completeness, source freshness, intercompany elimination
- Close readiness gate: block analysis until data passes all checks
- Threshold monitoring between closes: forecast drift, run-rate anomalies, metric breaches

### 4.2 Analyze Layer
- Deterministic variance computation: actual vs budget, actual vs forecast, actual vs prior period
- Materiality assessment: absolute threshold + percentage threshold + account sensitivity tier
- Bridge analysis: price/volume/mix, FX, one-time items, timing, scope changes
- Structured driver trees: variance → component drivers → operational metrics → evidence

### 4.3 Reason Layer
- Root-cause investigation with bounded tool access (read-only queries to internal APIs)
- Evidence graph: every claim linked to specific source records with verification hashes
- Alternative hypothesis generation: presents multiple explanations with confidence scores
- Uncertainty calibration: explicit acknowledgment of data gaps, incomplete evidence, or conflicting signals

### 4.4 Decide Layer
- Policy engine: confidence threshold + materiality + action type → auto-continue / human review / hard stop
- Routing: assigns investigations and approvals to correct owners by topic and materiality
- Exception handling: escalates blocked, timeout, or low-confidence cases

### 4.5 Act Layer
- Draft structured commentary with verified claims
- Create action items with owners, due dates, and impact estimates
- Propose forecast assumption updates (low-risk only, material changes require human)
- Publish management packs to designated repositories and distribution lists
- Update investigation status and close tracking

### 4.6 Learn Layer
- Track human override rate, rejected claims, forecast accuracy post-update
- Measure time-to-close improvement
- Refine thresholds and policies based on historical patterns

---

## 5. Autonomy Policy Matrix

| Action | Auto-Run | Human Review | Hard Block |
|---|---|---|---|
| Detect variance | Yes | No | — |
| Assess materiality | Yes | No | — |
| Run data quality checks | Yes | No | — |
| Investigate root cause | Yes | Optional if confidence < 0.7 | — |
| Draft commentary | Yes | No (before publish) | — |
| Propose actions | Yes | No (before execution) | — |
| Publish management pack | No | Always | — |
| Update forecast assumptions (low impact) | Yes | No | — |
| Update forecast assumptions (material) | No | Always | — |
| Create action items | Yes | No | — |
| Send notifications | Yes | No | — |
| Post to GL / ERP | Never | — | Always |
| Change budget | Never | — | Always |
| Approve spend / payments | Never | — | Always |
| Delete financial records | Never | — | Always |
| Modify source data | Never | — | Always |

**Rule:** Any action that writes to a system of record (ERP, GL, budget, payments) is permanently blocked from autonomous execution. FinSight only reads from these systems and writes to its own state, internal tasks, and approved forecast assumptions.

---

## 6. Canonical Workflow

```
[SENSE]
  ├─ Source snapshot arrives (event: source.snapshot.ready)
  ├─ Data quality validation
  ├─ If failed → create remediation task, alert owner, STOP
  └─ If passed → emit event: close.ready

[ANALYZE]
  ├─ Compute variances (deterministic engine)
  ├─ Assess materiality
  ├─ If no material variances → emit event: close.no_action
  └─ If material variances → emit event: variance.material

[REASON]
  ├─ Launch root-cause investigation per material variance
  ├─ Query evidence via read-only tools
  ├─ Build driver tree
  ├─ If evidence insufficient → emit event: evidence.insufficient
  │   └─ Create data request task, STOP
  └─ If evidence sufficient → emit event: investigation.completed

[DECIDE]
  ├─ Confidence assessment
  ├─ Policy check
  ├─ If confidence < 0.7 → route to human review
  ├─ If blocked by policy → route to human review
  └─ If approved by policy → emit event: commentary.ready

[ACT — DRAFT]
  ├─ Draft commentary with verified claims
  ├─ Propose actions with owners and impact
  ├─ Claim validation: every number verified against evidence
  ├─ If validation fails → emit event: commentary.blocked
  │   └─ Return to investigation with gaps
  └─ If validation passes → emit event: commentary.drafted

[ACT — REVIEW]
  ├─ Route to approver by materiality/topic
  ├─ Human reviews: approve / reject / request revision
  ├─ If rejected → emit event: approval.rejected
  │   └─ Return to investigation or commentary with feedback
  └─ If approved → emit event: approval.granted

[ACT — EXECUTE]
  ├─ Publish management pack
  ├─ Create action items
  ├─ Apply low-risk forecast assumption updates
  ├─ Notify stakeholders
  └─ Emit event: close.completed

[LEARN]
  ├─ Record actual vs predicted outcomes
  ├─ Track override rate and rejection reasons
  └─ Refine thresholds and policies
```

---

## 7. Domain Model

### Core Entities

| Entity | Definition | Key Attributes |
|---|---|---|
| **Tenant** | Isolated organization boundary | id, name, fiscal_calendar, currency, base_currency |
| **Period** | Fiscal time bucket | id, tenant_id, fiscal_year, fiscal_period, start_date, end_date, status |
| **Source** | External system connection | id, tenant_id, type (erp/crm/accounting/etc), config, last_sync_at |
| **Snapshot** | Point-in-time data extract | id, source_id, period_id, status, checksum, record_count |
| **FinancialFact** | Canonical normalized record | id, tenant_id, period_id, account_id, dimension_values, amount, currency |
| **Variance** | Deviation from plan | id, period_id, account_id, dimension_values, actual, budget, forecast, variance_amount, variance_pct, materiality_status |
| **Investigation** | Agent analysis session | id, variance_id, status, confidence, evidence_items, driver_tree, findings |
| **EvidenceItem** | Verified source record | id, investigation_id, source_table, record_id, field, value, verification_hash |
| **Commentary** | Structured explanation | id, investigation_id, sections, claims, status, approval_state |
| **Claim** | Specific assertion | id, commentary_id, text, value, evidence_ids, validation_status |
| **ActionItem** | Follow-up task | id, commentary_id, owner_id, description, impact, due_date, status |
| **Approval** | Human decision | id, commentary_id, approver_id, decision, comments, decided_at |
| **ForecastAssumption** | Planning input | id, tenant_id, period_id, driver, value, confidence, source |
| **ManagementPack** | Published output | id, period_id, format, url, distribution_list, published_at |
| **PolicyRule** | Autonomy boundary | id, tenant_id, action_type, condition, decision (auto/review/block) |

### State Machines

**PeriodRun:**
```
[initialized] → [data_validation] → [variance_analysis] → [investigation] → [commentary] → [review] → [approved] → [published] → [completed]
                    ↓                    ↓                  ↓              ↓           ↓
               [blocked] ← [remediation] ← [insufficient_evidence] ← [rejected] ← [revision]
```

**Investigation:**
```
[created] → [evidence_gathering] → [analysis] → [findings_ready] → [completed]
              ↓
           [blocked] → [escalated]
```

**Commentary:**
```
[drafted] → [claim_validated] → [routed] → [under_review] → [approved] → [published]
               ↓                    ↓           ↓
            [blocked]           [rejected] → [revision]
```

---

## 8. Architecture Overview

### 8.1 Stack

| Layer | Technology | Role |
|---|---|---|
| API Gateway | Go + Fiber | Auth, routing, rate limiting, composition |
| Finance Core | Go | Deterministic calculations, variance, materiality |
| Connector Hub | Go | ERP/CRM/accounting integrations, normalization |
| Workflow Orchestrator | Python + Temporal SDK | Durable close workflows, HITL checkpoints |
| Agent Runtime | Python + LangGraph + PydanticAI | Root-cause, commentary, monitoring agents |
| Sandbox Gateway | Go | Isolated code execution for custom analysis |
| Policy Engine | Go | Autonomy decisions, routing, exception handling |
| Event Backbone | Redpanda (single-node dev) | Event streaming, audit log |
| Primary Store | PostgreSQL | Operational state, tenant isolation |
| Cache | Redis | Session, rate limiting, ephemeral coordination |
| Vector Store | Qdrant | Prior commentary, policy docs, historical patterns |
| Object Storage | MinIO | Snapshots, packs, evidence archives |
| LLM Proxy | LiteLLM | Multi-provider routing, rate limiting, fallbacks |
| Observability | Jaeger all-in-one | Distributed tracing |

### 8.2 Service Boundaries

```
┌─────────────────────────────────────────────────────────────┐
│                         API Gateway                          │
│                    (Go, Fiber, Auth, Routing)                │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌──────────────┐   ┌──────────────────┐   ┌──────────────┐
│ Finance Core │   │ Policy Engine    │   │ Connector    │
│ (Go)         │   │ (Go)             │   │ Hub (Go)     │
│              │   │                  │   │              │
│ • Variance   │   │ • Autonomy rules │   │ • ERP/CRM    │
│ • Materiality│   │ • Routing        │   │ • Accounting │
│ • Bridge     │   │ • Exceptions     │   │ • Sheets     │
│ • FX         │   │ • Confidence     │   │ • Normalizer │
└──────────────┘   └──────────────────┘   └──────────────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Workflow Orchestrator                     │
│              (Python, Temporal SDK, durable)                 │
│                                                             │
│  • PeriodRun workflow                                       │
│  • HITL checkpoints (approval, rejection, revision)       │
│  • Recovery, retries, timeouts                              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     Agent Runtime                            │
│          (Python, LangGraph, PydanticAI)                   │
│                                                             │
│  • Root-cause agent (read-only tools)                       │
│  • Commentary agent (structured output, claim validation)   │
│  • Monitoring agent (continuous threshold watch)            │
│  • Evidence graph builder                                   │
│  • Claim validator                                          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Infrastructure                            │
│  PostgreSQL │ Redis │ Qdrant │ Redpanda │ MinIO │ Jaeger   │
└─────────────────────────────────────────────────────────────┘
```

---

## 9. Feature Specifications

### 9.1 Sense: Data Quality & Close Readiness

**Requirement:** Before any analysis begins, the system must validate that source data is complete, consistent, and current.

**Checks:**
- Trial balance: sum(debits) == sum(credits)
- FX rates: all required currency pairs present for period
- Mappings: all source accounts mapped to canonical chart of accounts
- Source freshness: all sources synced within N hours of close trigger
- Intercompany: elimination entries present and balanced
- Period boundaries: no overlapping or gap periods

**Behavior:**
- If all checks pass → emit `close.ready`
- If any check fails → emit `close.blocked`, create remediation task per failure, alert data owner
- Remediation tasks must be resolved before pipeline can resume

**API:**
```
POST /api/v1/periods/{period_id}/validate
GET /api/v1/periods/{period_id}/validation-status
GET /api/v1/periods/{period_id}/remediation-tasks
```

### 9.2 Analyze: Variance & Materiality

**Requirement:** Compute variances and flag only material deviations for investigation.

**Inputs:**
- Actuals (from snapshot)
- Budget (from planning system)
- Forecast (from prior forecast version)
- Prior period actuals (for trend)

**Outputs:**
- Variance record per account × dimension combination
- Materiality status: `material` / `immaterial` / `new_activity` / `missing_budget`

**Materiality Rules (configurable per tenant):**
- Absolute threshold: |variance| > $X
- Percentage threshold: |variance%| > Y%
- Account sensitivity: revenue, cogs, opex tiers have different thresholds
- Combined: material if (abs > threshold AND pct > threshold) OR account is high-sensitivity

**Bridge Analysis:**
For material variances, compute component bridges:
- Price/volume/mix (for revenue)
- FX impact (for multi-currency)
- One-time items (identified by flag)
- Timing differences (accrual vs cash)
- Scope changes (new/discontinued products)

**API:**
```
GET /api/v1/periods/{period_id}/variances
GET /api/v1/variances/{variance_id}/bridge
GET /api/v1/variances/{variance_id}/materiality
```

### 9.3 Reason: Root-Cause Investigation

**Requirement:** For each material variance, gather evidence and build a structured explanation.

**Agent Behavior:**
- Receives variance context (account, dimensions, amount, %)
- Uses read-only tools to query operational and financial data
- Builds driver tree: variance → component drivers → operational metrics
- Collects EvidenceItems with source, record ID, field, value
- Generates 1-3 alternative hypotheses with confidence scores
- Explicitly notes data gaps or incomplete evidence

**Tools (read-only):**
- `query_gl_detail(account, period, dimensions)` → GL line items
- `query_sales_pipeline(period, product, region)` → pipeline metrics
- `query_headcount(period, department)` → headcount and comp
- `query_vendor_spend(period, vendor, category)` → AP/PO data
- `query_billing_metrics(period, product)` → MRR, churn, expansion
- `query_policy_document(topic)` → relevant accounting policies
- `query_prior_commentary(period, account)` → historical patterns

**Output:**
- Investigation record with status, confidence, evidence graph, findings
- Driver tree as structured JSON
- Alternative hypotheses
- Data gaps (if any)

**API:**
```
POST /api/v1/variances/{variance_id}/investigate
GET /api/v1/investigations/{investigation_id}
GET /api/v1/investigations/{investigation_id}/evidence
GET /api/v1/investigations/{investigation_id}/driver-tree
```

### 9.4 Decide: Policy & Routing

**Requirement:** Determine whether investigation output can proceed autonomously or requires human review.

**Policy Engine:**
- Evaluates: confidence score, materiality tier, action type, historical override rate
- Decision: `auto_proceed` / `human_review` / `hard_stop`

**Routing Rules:**
- Revenue variances > $500K or > 10% → CFO review
- Opex variances > $100K or > 15% → FP&A Manager review
- All other material variances → FP&A Analyst review
- Low confidence (< 0.7) → escalate to next level
- Conflicting evidence → escalate to FP&A Manager

**API:**
```
POST /api/v1/investigations/{investigation_id}/evaluate-policy
GET /api/v1/approvals/{approval_id}
POST /api/v1/approvals/{approval_id}/decide
```

### 9.5 Act: Commentary & Actions

**Requirement:** Draft structured commentary with verified claims and proposed actions.

**Commentary Structure:**
```json
{
  "sections": [
    {
      "title": "Executive Summary",
      "content": "...",
      "claims": [
        {
          "text": "Revenue decreased by $580K (12%)",
          "value": -580000,
          "evidence_ids": ["ev-123", "ev-124"],
          "validation_status": "verified"
        }
      ]
    }
  ],
  "actions": [
    {
      "owner_id": "user-456",
      "description": "Review EMEA pricing strategy",
      "impact": "potential $200K recovery",
      "due_date": "2026-07-15",
      "priority": "high"
    }
  ]
}
```

**Claim Validator:**
- Extracts every monetary claim from commentary
- Verifies against evidence items
- Checks: exact match, within rounding tolerance, or unsupported
- Unsupported claims → block commentary, return to investigation

**API:**
```
POST /api/v1/investigations/{investigation_id}/draft-commentary
POST /api/v1/commentaries/{commentary_id}/validate
GET /api/v1/commentaries/{commentary_id}
```

### 9.6 Act: Publish & Execute

**Requirement:** Upon approval, execute allowed actions.

**Allowed Actions:**
- Publish management pack (PDF, XLSX, HTML) to repository
- Create action items in task system
- Apply low-risk forecast assumption updates
- Send notifications to distribution list
- Update period status

**Blocked Actions (permanent):**
- Post to GL/ERP
- Change budget
- Approve payments
- Modify source data
- Delete records

**API:**
```
POST /api/v1/commentaries/{commentary_id}/publish
POST /api/v1/periods/{period_id}/complete
GET /api/v1/management-packs/{pack_id}
```

### 9.7 Learn: Monitoring & Continuous Improvement

**Requirement:** Between close cycles, monitor for anomalies and improve over time.

**Monitoring:**
- Threshold breaches: revenue run-rate, burn rate, headcount growth
- Forecast drift: actuals trending away from forecast
- Data quality degradation: source sync delays, mapping failures
- Unusual patterns: vendor spend spikes, accrual build-up

**Learning:**
- Track override rate by agent, model, and prompt version
- Measure forecast accuracy (MAPE) before and after assumption updates
- Record time-to-close per period
- Identify recurring variances for proactive modeling

**API:**
```
GET /api/v1/tenants/{tenant_id}/monitoring/alerts
GET /api/v1/tenants/{tenant_id}/metrics/override-rate
GET /api/v1/tenants/{tenant_id}/metrics/forecast-accuracy
```

---

## 10. Non-Goals (v1)

These are explicitly out of scope for the first version:

- **General-purpose chatbot:** FinSight is not a conversational interface for ad-hoc finance questions.
- **Real-time trading or market data:** Not a trading system.
- **Unsupervised system-of-record writes:** No autonomous GL posting, budget changes, or payments.
- **Multi-tenant SaaS billing:** v1 is single-tenant deployable; SaaS billing is future work.
- **Advanced NLP document extraction:** v1 uses structured connectors; unstructured document parsing is future.
- **Full ELT pipeline:** No Spark, Airflow, or complex data engineering in v1.
- **Mobile app:** Web-first.
- **Real-time collaboration:** No simultaneous editing; sequential review workflow.
- **Custom ML models:** Uses LLMs via LiteLLM; no fine-tuned finance models in v1.

---

## 11. Success Metrics

### 11.1 System Metrics

| Metric | Target | Measurement |
|---|---|---|
| Time to close (variance-to-pack) | < 4 hours (vs 2-3 days manual) | Period completion timestamp |
| Data quality block rate | < 5% | Blocked periods / total periods |
| Claim validation pass rate | > 95% | Validated claims / total claims |
| Human override rate | < 15% | Overridden decisions / total decisions |
| Agent confidence accuracy | > 80% | Correct predictions at stated confidence |
| System availability | > 99.5% | Uptime during close windows |

### 11.2 Business Metrics

| Metric | Target | Measurement |
|---|---|---|
| Forecast accuracy improvement | +10% MAPE reduction | Before vs after assumption updates |
| Unexplained variance reduction | -20% | Residual variance / total variance |
| Action completion rate | > 70% | Closed actions / created actions |
| Analyst time on mechanical work | -50% | Self-reported time allocation |

---

## 12. Implementation Phases

### Phase 0: Foundations (Week 1-2)
- Monorepo, CI/CD, Docker Compose dev profile
- Synthetic data generator, deterministic oracle fixtures
- PostgreSQL schema, tenant isolation (RLS), audit/outbox
- Auth skeleton, OpenTelemetry, Jaeger

### Phase 1: Deterministic Core (Week 3-4)
- Finance Core: variance, materiality, bridge, FX
- API Gateway: REST composition, tenant routing
- Connector Hub: mock ERP, CSV import, snapshot normalization
- Close readiness validation
- E2E: happy path month-end

### Phase 2: Agent + Workflow Layer (Week 5-7)
- Temporal integration: durable period-run workflow
- Workflow Orchestrator: Temporal activities
- Agent Runtime: LangGraph + PydanticAI
- Root-cause agent with read-only tools
- Commentary agent with claim validator
- HITL review UI
- E2E: approval, rejection, recovery

### Phase 3: Advanced Intelligence (Week 8-9)
- Monitoring agent: continuous threshold watch
- Qdrant + RAG: prior commentary, policy docs
- Policy engine: confidence-based routing
- Action execution layer
- Eval runner: regression suite
- E2E: continuous monitoring, proactive investigation

### Phase 4: Production Hardening (Week 10-12)
- Real connectors: NetSuite, QuickBooks, Salesforce, Sheets
- SSO/SCIM, RBAC/ABAC
- Security: SAST, DAST, dependency scan, pen test
- Performance: load tests, chaos tests
- Kubernetes manifests, Terraform, GitOps

---

## 13. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| LLM hallucinates financial numbers | Medium | Critical | Claim validator, evidence graph, HITL approval |
| Free-tier API rate limits | High | Medium | LiteLLM fallback, caching, rate limiting |
| Source data quality issues | High | Medium | Close readiness gate, remediation workflow |
| Human approval bottleneck | Medium | High | Policy-based auto-approval for low-risk items |
| Tenant data isolation failure | Low | Critical | RLS, strict query scoping, audit logging |
| Workflow state corruption | Low | Critical | Temporal durability, idempotent activities |
| Prompt injection | Medium | High | Input validation, tool sandboxing, security tests |
| Model drift / performance regression | Medium | Medium | Continuous eval, A/B testing, rollback |

---

# Appendix A: Coding Agent Prompt

## Context

You are implementing FinSight, an event-driven autonomous vertical agentic AI system for FP&A. The system has a polyglot architecture:
- **Go** services: API Gateway, Finance Core, Connector Hub, Policy Engine, Sandbox Gateway
- **Python** services: Workflow Orchestrator (Temporal), Agent Runtime (LangGraph + PydanticAI)
- **Infrastructure**: PostgreSQL, Redis, Qdrant, Redpanda, MinIO, Jaeger, LiteLLM

## Core Principles

1. **Deterministic finance logic is sacred.** Every calculation must match an oracle. Use `decimal.Decimal` in Python, never float. Use exact arithmetic in Go.
2. **Agents are read-only by default.** They query internal APIs; they never write to ERP, GL, or budget systems.
3. **Every claim must be evidence-backed.** Commentary agents must link every number to specific source records.
4. **Autonomy is policy-bound.** The Policy Engine decides what can auto-run vs. what needs human review.
5. **Events are first-class.** Use the event backbone for all cross-service communication, not direct RPC.
6. **Tenant isolation is non-negotiable.** Every query must include `tenant_id` and respect RLS.
7. **Audit everything.** Every decision, every approval, every override is logged immutably.

## Code Patterns

### Go Services

```go
// Handler pattern: always validate, always authorize, always audit
func (h *Handler) GetVariances(c *fiber.Ctx) error {
    ctx := c.UserContext()
    tenantID := c.Locals("tenant_id").(string)
    periodID := c.Params("period_id")

    // Validate
    if err := validatePeriodID(periodID); err != nil {
        return c.Status(400).JSON(ErrorResponse{Error: err.Error()})
    }

    // Authorize: tenant isolation
    variances, err := h.store.GetVariances(ctx, tenantID, periodID)
    if err != nil {
        return c.Status(500).JSON(ErrorResponse{Error: "internal error"})
    }

    // Audit
    h.audit.Log(ctx, "variances.listed", tenantID, periodID, len(variances))

    return c.JSON(variances)
}

// Finance calculation: exact decimal arithmetic
func CalculateVariance(actual, budget decimal.Decimal) Variance {
    diff := actual.Sub(budget)
    pct := decimal.Zero
    if budget.Sign() != 0 {
        pct = diff.Div(budget).Mul(decimal.NewFromInt(100))
    }
    return Variance{
        Amount: diff,
        Percent: pct,
    }
}
```

### Python Agents

```python
# PydanticAI agent with typed tools and structured output
from pydantic_ai import Agent, RunContext
from pydantic import BaseModel

class InvestigationOutput(BaseModel):
    confidence: float
    findings: list[Finding]
    evidence_items: list[EvidenceItem]
    data_gaps: list[str]
    alternative_hypotheses: list[Hypothesis]

class RootCauseAgent:
    def __init__(self, tool_gateway: ToolGateway):
        self.agent = Agent(
            model="groq-llama3-70b",
            result_type=InvestigationOutput,
            system_prompt="You are a financial analyst. Investigate variances using only provided tools."
        )
        self.tools = tool_gateway

    @self.agent.tool
    async def query_sales_pipeline(ctx: RunContext, period: str, product: str) -> dict:
        """Read-only query to sales pipeline"""
        return await self.tools.query_sales_pipeline(ctx.deps.tenant_id, period, product)

    async def investigate(self, variance: Variance) -> InvestigationOutput:
        result = await self.agent.run(
            f"Investigate variance: {variance.account} {variance.amount}",
            deps=AgentDeps(tenant_id=variance.tenant_id)
        )
        return result.data
```

### Temporal Workflow

```python
from temporalio import workflow

@workflow.defn
class PeriodRunWorkflow:
    @workflow.run
    async def run(self, period_id: str) -> PeriodRunResult:
        # 1. Validate data quality
        validation = await workflow.execute_activity(
            validate_data_quality,
            period_id,
            start_to_close_timeout=timedelta(minutes=5)
        )
        if not validation.passed:
            return PeriodRunResult(status="blocked", reason=validation.failures)

        # 2. Compute variances
        variances = await workflow.execute_activity(
            compute_variances,
            period_id,
            start_to_close_timeout=timedelta(minutes=10)
        )

        # 3. Investigate material variances
        investigations = []
        for v in variances.material:
            inv = await workflow.execute_activity(
                investigate_variance,
                v.id,
                start_to_close_timeout=timedelta(minutes=15)
            )
            investigations.append(inv)

        # 4. HITL checkpoint: variance review
        await workflow.execute_activity(
            notify_variance_review,
            investigations,
            start_to_close_timeout=timedelta(minutes=1)
        )
        review = await workflow.wait_for_external_signal(
            "variance_review_complete",
            timeout=timedelta(hours=48)
        )
        if review.decision == "rejected":
            return PeriodRunResult(status="rejected")

        # 5. Draft commentary
        commentaries = []
        for inv in investigations:
            if inv.confidence < 0.7:
                # Escalate
                continue
            commentary = await workflow.execute_activity(
                draft_commentary,
                inv.id,
                start_to_close_timeout=timedelta(minutes=10)
            )
            commentaries.append(commentary)

        # 6. HITL checkpoint: commentary approval
        await workflow.execute_activity(
            notify_commentary_approval,
            commentaries,
            start_to_close_timeout=timedelta(minutes=1)
        )
        approval = await workflow.wait_for_external_signal(
            "commentary_approved",
            timeout=timedelta(hours=72)
        )
        if approval.decision == "rejected":
            return PeriodRunResult(status="revision_needed")

        # 7. Publish
        await workflow.execute_activity(
            publish_management_pack,
            commentaries,
            start_to_close_timeout=timedelta(minutes=5)
        )

        return PeriodRunResult(status="completed")
```

## Rules

1. **Never use float for money.** Always `decimal.Decimal` (Python) or `shopspring/decimal` (Go).
2. **Never trust LLM output without validation.** All structured outputs must pass schema validation.
3. **Never bypass tenant isolation.** Every database query must filter by `tenant_id`.
4. **Never hardcode secrets.** Use environment variables, secret managers, or Vault.
5. **Never block the event loop.** Use async/await properly; offload CPU work to threads.
6. **Never lose workflow state.** Temporal workflows must be deterministic; no random, no time.Now(), no external I/O in workflow code.
7. **Never ignore errors.** Every error must be handled, logged, and traced.
8. **Never skip tests.** Every feature needs: unit test, integration test (Testcontainers), and eval test (if agentic).
9. **Never commit without linting.** Go: `gofmt`, `golangci-lint`. Python: `ruff`, `mypy`, `black`.
10. **Never deploy without observability.** Every service emits OpenTelemetry traces and structured logs.

## Testing Requirements

### Unit Tests
- Finance Core: 100% oracle match for all calculations
- Property tests for ledger invariants (Hypothesis/Go fuzzing)
- Agent schema round-trip tests
- Policy engine truth table tests

### Integration Tests
- Testcontainers for all infrastructure
- Tenant isolation tests
- Workflow resumption tests
- Connector idempotency tests

### Agent Evaluation
- Trajectory evaluation: tool-use accuracy
- RAG metrics: context precision, faithfulness
- Claim validation: every number verified
- Adversarial tests: prompt injection, numerical manipulation

### E2E Tests
- Happy path month-end
- Data quality block and recovery
- Approval rejection and revision
- Cross-tenant isolation
- Workflow recovery after crash

## Documentation

- Every service must have an OpenAPI spec
- Every agent must have a tool manifest
- Every workflow must have a state diagram
- Every event must have a schema registry entry

## Security

- SAST: Semgrep on every PR
- Dependency scan: Snyk/Trivy
- Container scan: Trivy
- Secret scan: GitLeaks
- No secrets in logs or traces
- All external communications over TLS
- RBAC on every endpoint
- Rate limiting on every public API
