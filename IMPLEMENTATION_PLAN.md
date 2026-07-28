# FinSight Implementation Plan v2
## Leveraging Existing Code — Closing the PRD Gap

**PRD Coverage Today:** ~25-30% | **Target:** 100% of v1 scope

---

## Guiding Principle

The existing Python/LangGraph/FastAPI prototype is **not wrong** — it's an excellent MVP that validated the agentic pipeline concept. This plan **evolves** it toward the PRD architecture incrementally, prioritizing functional completeness over language purity. Go migration happens where it adds clear value (deterministic finance core, policy engine throughput). Everything else ships in Python first.

---

## Phase 0: Fix Critical Deviations (Week 1)

These are non-negotiable fixes that violate PRD core principles. Ship these first.

### 0.1 Decimal Everywhere
**Files:** `backend/models/state.py`, `backend/agents/variance_agent.py`, `backend/agents/ingestion_agent.py`, `backend/agents/root_cause_agent.py`, `backend/validators/claim_validator.py`, `backend/models/database.py`, all `routes.py`, all tests

**Change:** Replace all `float` financial fields with `Decimal`. Update Pydantic models, SQLAlchemy columns (already `Numeric`), agent prompt formatting, and claim validator regex math.

| File | Current | Target |
|---|---|---|
| `state.py:Variance.actual_amount` | `float` | `Decimal` |
| `state.py:Variance.budget_amount` | `float` | `Decimal` |
| `state.py:Variance.variance_amount` | `float` | `Decimal` |
| `state.py:Variance.variance_pct` | `float` | `Decimal` |
| `state.py:Variance.confidence_score` | `float` | keep float (not money) |
| `state.py:EvidenceItem.value` | `float` | `Decimal` |
| `state.py:RootCauseFinding.confidence_score` | `float` | keep float |
| `state.py:Scenario.*_impact` | `float` | `Decimal` |
| `variance_agent.py:9-12` | `float(a["amount"])` | `Decimal(a["amount"])` |
| `variance_agent.py:12` | `/` with `float` | `.Div()` with `Decimal` |
| `ingestion_agent.py:51` | `float(actual.amount)` | `Decimal(actual.amount)` |
| `claim_validator.py:Claim.amount` | `float` | `Decimal` |

### 0.2 Wire LiteLLM Proxy
**Files:** `backend/agents/root_cause_agent.py:64-69`, `backend/agents/commentary_agent.py:56-61`

**Change:** All LLM calls go through `LiteLLM` Python SDK at `settings.litellm_proxy_url` instead of calling OpenRouter directly. This gives us rate limiting, fallback, cost tracking, and caching.

```python
# Before
response = llm_client.chat.completions.create(
    model="google/gemma-4-26b-a4b-it:free",
    messages=[...],
)

# After
from litellm import completion
response = completion(
    model="openrouter/google/gemma-4-26b-a4b-it:free",
    messages=[...],
    api_base=settings.litellm_proxy_url,
)
```

Both agents already accept an `llm_client` parameter — create a shared `LLMClient` wrapper that routes through LiteLLM.

### 0.3 Connect Tools to Real DB + Tool Contracts
**Files:** `backend/tools/*.py`

**Change:** Replace all hardcoded mock return values with real PostgreSQL queries using the same `engine` pattern as `ingestion_agent.py`.

**Anti-hallucination: Tool Wrapper Contracts.** Every tool response must include metadata:

```python
class ToolResult(BaseModel):
    data: list[dict]
    row_count: int
    coverage_pct: float  # 0.0-1.0, how complete the data is
    fresh_at: str | None  # ISO timestamp of latest record
    tenant_id: str
    insufficient_data: bool  # true if coverage < threshold
    source_type: str  # "gl_detail" | "operational_metric" | "hr" | "vendor" | "sales"
```

| Tool | Current | Target |
|---|---|---|
| `gl_tools.py` | `{"status": "ok", "records": []}` | Query `trial_balance`, `actuals` tables — return `ToolResult` |
| `headcount_tools.py` | `{"total_hc": 280}` | Query `headcount_data` table — return `ToolResult` |
| `vendor_tools.py` | Hardcoded vendor spend | Query `vendor_invoices` table — return `ToolResult` |
| `pipeline_tools.py` | Hardcoded pipeline | Query `sales_pipeline` table — return `ToolResult` |
| `rag_tools.py` | Hardcoded RAG results | Query Qdrant or fallback to DB — return `ToolResult` |

**Pattern:** Each tool accepts `(tenant_id, period, **kwargs)` and returns `ToolResult`. Add `engine` injection similar to `ingestion_node`.

### 0.4 Assertion Model (Anti-Hallucination Foundation)
**New file:** `backend/models/assertions.py`
**Modify:** `backend/models/state.py`

Create an `Assertion` type system that classifies every claim the system makes:

```python
class AssertionType(str, Enum):
    NUMERIC = "numeric"        # "Revenue was $1.2M"
    COMPARATIVE = "comparative" # "Costs are 15% higher than budget"
    CAUSAL = "causal"          # "Driven by increased compute spend"
    HYPOTHESIS = "hypothesis"   # "Possibly due to seasonal effects"
    ACTION = "action"           # "Review EMEA pricing strategy"

class Assertion(BaseModel):
    id: str
    type: AssertionType
    text: str
    value: Decimal | None = None
    evidence_ids: list[str] = []
    support_level: str = "pending"  # verified / probable / insufficient
    contradictions: list[str] = []
    missing_evidence: list[str] = []
    max_allowed_action: str = "route_for_review"
    source: str = ""  # "deterministic" | "llm_analysis" | "human"
```

**Validation rules per type:**
- `NUMERIC`: must match source evidence within tolerance, or be labeled `unverified`
- `COMPARATIVE`: must be provable from ranked facts (evidence must contain comparison source)
- `CAUSAL`: must cite ≥2 independent evidence sources, or be downgraded to `hypothesis`
- `HYPOTHESIS`: never treated as fact, max confidence 0.5, always routes to human review
- `ACTION`: must map to a rule-based template or be evidence-backed driver

**Why this matters:** The root-cause and commentary agents will assert claims _through_ this model, not through free text. The claim validator then enforces structural rules per type, not just monetary tolerance.

---

## Phase 1: Complete the Core Pipeline (Week 2-3)

Build missing PRD capabilities within the existing Python stack.

### 1.1 Sense: Real Data Quality Validation + Degraded Modes
**New file:** `backend/validators/data_quality.py`
**Modify:** `backend/agents/ingestion_agent.py`

**Replace stubs** `_check_reconciliation` and `_detect_anomalies` with proper checks from PRD §9.1:

| Check | Implementation | Degradation Effect |
|---|---|---|
| Trial balance: debits == credits | Query `trial_balance` SUM(debit) vs SUM(credit) per period | Block all commentary |
| FX rates: all pairs present | Check `fx_rates` table (new table) for required pairs | Block multi-currency variance commentary |
| Mapping completeness | Verify all `actuals.account_id` exist in `gl_accounts` | Allow raw anomaly surfacing, block final driver attribution |
| Source freshness | Check `agent_runs` ingestion timestamp vs configured max age | Allow "preliminary view" only, block final publication |
| Intercompany elimination | Validate IC accounts have elimination entries | Block consolidated margin commentary |
| Period boundaries | Check no overlapping periods in `periods` table | Block period progression |

**Anti-hallucination: Degraded Modes.** Each failed check generates a `degraded_mode` status:
- `DegradedMode.preliminary_only` — results visible, not publishable
- `DegradedMode.insufficient_for_publication` — block pack publish
- `DegradedMode.fact_verified_cause_unverified` — numbers ok, causes blocked
- `DegradedMode.blocked_missing_fx` — multi-currency analysis unavailable
- `DegradedMode.blocked_mapping_gap` — driver attribution unavailable

These propagate through the policy engine, which can allow auto-proceed on some actions while blocking others from the same pipeline run.

**New table:** `data_quality_checks` — stores check results, failures, timestamps, and computed degraded mode.

### 1.2 Analyze: Bridge Analysis
**New file:** `backend/agents/bridge_agent.py`

**Price/Volume/Mix** for revenue accounts:
```
Revenue = Price × Volume × Mix
Variance = ΔPrice × V_actual + P_budget × ΔVolume + (P_actual − P_budget) × ΔMix
```

**FX Impact** for multi-currency accounts:
```
FX Variance = Actual_FC × (Actual_Rate − Budget_Rate)
Volume Variance = (Actual_FC − Budget_FC) × Budget_Rate
```

**One-time / Timing / Scope** — check `actuals.notes` or account flags for tagged items.

### 1.3 Reason: Alternative Hypotheses + Data Gaps + Structured Findings
**Modify:** `backend/agents/root_cause_agent.py`

- Add prompt instruction to generate 2-3 alternative hypotheses with individual confidence scores
- Add "data_gaps" field to output: explicitly name what's missing
- **Anti-hallucination: Deterministic confidence computation** — final confidence is computed, not LLM-generated:

```python
def compute_confidence(
    llm_confidence: float,
    evidence_count: int,
    source_diversity: int,  # distinct source types
    has_contradictions: bool,
    stale_data: bool,
    missing_dimensions: list[str],
) -> float:
    score = llm_confidence
    if evidence_count >= 2: score += 0.15
    if source_diversity >= 2: score += 0.10
    if not stale_data: score += 0.10
    if has_contradictions: score -= 0.20
    if missing_dimensions: score -= 0.10 * len(missing_dimensions)
    if evidence_count < 2: score = min(score, 0.6)  # hard cap: thin evidence
    if stale_data: score = min(score, 0.4)  # hard cap: stale data
    return max(0.0, min(1.0, score))
```

- **Every finding uses the Assertion model.** Each root-cause summary becomes one or more `Assertion` objects with type, evidence links, and support level. Commentary cannot "upgrade" a hypothesis to a fact.

```python
class RootCauseFinding(BaseModel):
    variance_id: str
    summary: str
    assertions: list[Assertion]  # typed claims, not free text
    evidence: list[EvidenceItem]
    confidence_score: float  # computed, not LLM-generated
    recommended_action: str | None = None
    alternative_hypotheses: list[Assertion] = []
    data_gaps: list[str] = []
```

### 1.4 Decide: Policy Engine
**New file:** `backend/agents/policy_engine.py`

**Implement the Autonomy Policy Matrix** (PRD §5) as a Python module:

```python
def evaluate_policy(
    action_type: str,
    confidence: float,
    variance_amount: Decimal,
    variance_pct: Decimal,
    account_type: str,
    historical_override_rate: float,
) -> PolicyDecision:
    """Returns auto_proceed / human_review / hard_stop"""
```

**Routing rules** (PRD §9.4):
- Revenue > $500K or > 10% → CFO
- Opex > $100K or > 15% → FP&A Manager
- Confidence < 0.7 → escalate
- Conflicting evidence → escalate

### 1.5 PRD-Compliant API Endpoints
**Modify:** `backend/api/routes.py`

Add all endpoints from PRD §9:

| PRD Endpoint | Priority | Notes |
|---|---|---|
| `POST /periods/{id}/validate` | High | Gate before analysis |
| `GET /periods/{id}/variances` | High | List with materiality filter |
| `GET /variances/{id}/bridge` | Medium | Decomposition |
| `POST /variances/{id}/investigate` | High | Trigger root cause |
| `GET /investigations/{id}` | Medium | Status + findings |
| `GET /investigations/{id}/evidence` | Medium | Evidence chain |
| `POST /investigations/{id}/evaluate-policy` | High | Policy decision |
| `POST /approvals/{id}/decide` | High | HITL decision |
| `POST /investigations/{id}/draft-commentary` | Medium | Commentary gen |
| `POST /commentaries/{id}/validate` | Medium | Claim check |
| `POST /commentaries/{id}/publish` | Medium | Output delivery |

### 1.6 Commentary as Rendering Layer (Anti-Hallucination)
**Modify:** `backend/models/state.py`, `backend/agents/commentary_agent.py`

**Critical rule: Commentary is a rendering layer over validated assertions, not a fresh reasoning pass.**

The commentary agent:
- Receives findings as `list[Assertion]` from root-cause investigation
- **Must not create new numeric claims** (any `$` amount must come from an existing assertion)
- **Must not create new causal claims** not present in findings
- Can paraphrase, organize, and structure existing assertions into readable sections
- Can mark uncertain items explicitly with language like "requires further investigation"

**Change `CommentaryDraft`** to match PRD §9.5:

```python
class Claim(BaseModel):
    text: str
    value: Decimal
    evidence_ids: list[str]
    validation_status: str  # "verified" | "unverified" | "pending"

class CommentarySection(BaseModel):
    title: str  # "Executive Summary", "Revenue", etc.
    content: str
    claims: list[Claim] = []  # must be subset of assertions passed from investigation

class CommentaryDraft(BaseModel):
    sections: list[CommentarySection]
    actions: list[ActionItem] = []
    assertions_used: list[str]  # assertion IDs consumed in this draft
    generated_at: str
    version: int = 1
    status: str = "draft"  # drafted → claim_validated → routed → under_review → approved → published
    approval_state: str | None = None
```

### 1.7 Action Creation (Template-Backed, Anti-Hallucination)
**New file:** `backend/agents/action_agent.py`

**Anti-hallucination: Actions are template-backed, not free-form LLM inventions.**

Action creation follows a taxonomy of allowed action types per variance driver:

```python
class ActionType(str, Enum):
    INVESTIGATE = "investigate"       # "Review vendor X pricing"
    FORECAST_UPDATE = "forecast_update"  # "Revise Q3 forecast for Y"
    TASK_ASSIGN = "task_assign"       # "Assign owner for Z remediation"
    POLICY_REVIEW = "policy_review"   # "Review accounting policy for W"
    NOTIFY = "notify"                 # "Alert business owner of trend"

class ActionItem(BaseModel):
    id: str
    commentary_id: str
    action_type: ActionType
    owner_id: str
    description: str
    impact: str
    due_date: str
    priority: str  # high / medium / low
    template_used: str | None = None  # which template generated this action
    evidence_ids: list[str] = []      # what evidence justifies this action
    status: str = "open"
```

**Allowed action templates (mapped by variance type):**
- Cloud spend increase + driver=compute hours → `INVESTIGATE` reserved-instance coverage
- Revenue shortfall + driver=volume → `INVESTIGATE` deal pipeline
- Opex overspend + driver=hc → `TASK_ASSIGN` hiring freeze review
- Forecast drift > threshold → `FORECAST_UPDATE` low-risk, `POLICY_REVIEW` material

**Blocked:** Any action not matching a defined template is `hard_stop` per policy engine.

**New DB table:** `action_items`

---

## Phase 2: State Machines + HITL (Week 4-5)

### 2.1 PeriodRun State Machine
**Modify:** `backend/agents/orchestrator.py`

Replace the 5-node linear graph with the full PRD §6 state machine:

```
[initialized] → [data_validation] → [variance_analysis] → [investigation] → [commentary] → [review] → [approved] → [published] → [completed]
                    ↓                    ↓                     ↓                 ↓            ↓
               [blocked] ← [remediation] ← [insufficient_evidence] ← [rejected] ← [revision]
```

**Implement via LangGraph** with conditional edges for each failure mode. Add checkpointing via `SqliteSaver` or `PostgresSaver` for persistence.

**New states:**
- `blocked`: data quality failed, remediation tasks created
- `remediation`: waiting for human-fixed data
- `insufficient_evidence`: root cause couldn't gather enough data
- `review`: HITL checkpoint for commentary/action approval
- `rejected`: human rejected, routed back with feedback
- `revision`: commentary needs edits
- `published`: actions executed
- `completed`: all done

### 2.2 Investigation State Machine
**Modify:** `backend/agents/root_cause_agent.py`

```
[created] → [evidence_gathering] → [analysis] → [findings_ready] → [completed]
               ↓
            [blocked] → [escalated]
```

### 2.3 Commentary State Machine
**Modify:** `backend/agents/commentary_agent.py`

```
[drafted] → [claim_validated] → [routed] → [under_review] → [approved] → [published]
               ↓                    ↓           ↓
            [blocked]           [rejected] → [revision]
```

### 2.4 HITL Review UI (Uncertainty-Focused)
**Modify:** `frontend/src/app/commentary/page.tsx`, `frontend/src/app/runs/page.tsx`

**Anti-hallucination: Reviews focus on uncertainty, not just approval.** Every review screen shows:

1. **Top claims** — each claim rendered with its type (numeric/causal/hypothesis), evidence count, and support level
2. **Evidence links** — clickable drill-down to source records
3. **Missing evidence** — what data was unavailable
4. **Contradictions** — conflicting signals the system detected
5. **Confidence explanation** — why confidence is at this level (row count, source diversity, freshness, contradictions)
6. **What would unblock** — specific actions the reviewer can take to improve confidence
7. **Proposed action** — which template was used and what evidence justifies it

Review workflow:
- **Variance review:** approve/reject/revision per material variance
- **Commentary review:** full commentary with claim-by-claim validation status display, approve/reject with notes
- **Approval routing:** show CFO/Manager/Analyst view based on who's assigned
- **Status badges:** blocked / in-review / approved / rejected

### 2.5 Domain Model DB Tables
**New Alembic migration** to add missing tables from PRD §7:

| Table | Columns |
|---|---|
| `periods` | id, tenant_id, fiscal_year, fiscal_period, start_date, end_date, status |
| `sources` | id, tenant_id, type, config_json, last_sync_at |
| `snapshots` | id, source_id, period_id, status, checksum, record_count |
| `financial_facts` | id, tenant_id, period_id, account_id, dimensions_json, amount, currency |
| `investigations` | id, variance_id, status, confidence, driver_tree_json, findings_json |
| `evidence_items` | id, investigation_id, source_table, record_id, field, value, verification_hash |
| `claims` | id, commentary_id, text, value, evidence_ids_json, validation_status |
| `action_items` | id, commentary_id, owner_id, description, impact, due_date, status |
| `approvals` | id, commentary_id, approver_id, decision, comments, decided_at |
| `policy_rules` | id, tenant_id, action_type, conditions_json, decision |
| `fx_rates` | id, period_id, currency_pair, rate |
| `data_quality_checks` | id, period_id, check_type, passed, details, checked_at |

### 2.6 Tenant Isolation
**Modify:** All DB queries, all route handlers

Add `tenant_id` filtering to every query. Rename `entity_id` → `tenant_id` for consistency with PRD. Add RLS policies via Alembic migration.

---

## Phase 3: Event-Driven + Temporal (Week 6-7)

### 3.1 Wire Redpanda Event Backbone
**New file:** `backend/events/producer.py`, `backend/events/consumer.py`

Emit events at each pipeline transition (PRD §6):
```
source.snapshot.ready   → data processing
close.ready             → analysis can start
close.no_action         → no material variances
variance.material       → material variance found
evidence.insufficient   → need more data
investigation.completed → ready for policy
commentary.ready        → drafted, ready for review
commentary.blocked      → claim validation failed
commentary.drafted      → passed validation
approval.rejected       → human said no
approval.granted        → human said yes
close.completed         → period published
```

**Audit log:** All events go to both Redpanda and an `audit_log` DB table.

### 3.2 Temporal Workflow Integration
**New file:** `backend/workflows/period_run.py`

Register Temporal worker. Wrap existing LangGraph pipeline in Temporal activities:

```python
@activity.defn
async def run_validation(period_id: str) -> ValidationResult

@activity.defn  
async def run_variance_analysis(period_id: str) -> VarianceResult

@activity.defn
async def run_investigation(variance_id: str) -> InvestigationResult

@activity.defn
async def draft_commentary(investigation_id: str) -> CommentaryResult

@activity.defn  
async def publish_pack(commentary_id: str) -> PackResult
```

**HITL checkpoints** (PRD §9 Temporal code sample):
```python
review = await workflow.wait_for_external_signal(
    "commentary_approved",
    timeout=timedelta(hours=72)
)
```

### 3.3 Redis Caching
**Configure** Redis for:
- LLM response caching (identical prompts → cached response)
- Rate limiting counters
- Session state
- Ephemeral coordination tokens

---

## Phase 4: Act Layer + Learn Layer (Week 8-9)

### 4.1 Action Execution
**New file:** `backend/agents/execute_agent.py`

After approval:
1. **Publish management pack:** Generate HTML/PDF summary from commentary + variance data. Save to filesystem (future: MinIO). Return URL.
2. **Create task items:** Write `action_items` records. (Future: integrate with task system API.)
3. **Apply low-risk forecast assumptions:** Update `forecast_lines` with new amounts. Only if policy allows.
4. **Send notifications:** Log notification events. (Future: email/Slack integration.)

### 4.2 Monitoring Agent (Continuous)
**New file:** `backend/agents/monitor_agent.py`

Between close cycles, run on schedule:
- **Threshold breaches:** Check current run-rate vs budget. Revenue, burn rate, headcount growth.
- **Forecast drift:** Compare actuals to forecast weekly. Flag if |actual - forecast| > threshold.
- **Data quality degradation:** Monitor source sync delays, mapping failures.
- **Unusual patterns:** Vendor spend spikes, accrual build-up, headcount changes.

Runs as a cron-like loop in a separate LangGraph agent.

### 4.3 Metrics & Learning
**New file:** `backend/metrics.py`

Track all PRD §11 metrics:

| Metric | Calculation | Storage |
|---|---|---|
| Time to close | `published_at - data_validation_started_at` | `periods` table columns |
| Override rate | `overridden_decisions / total_decisions` per period | `approvals` table |
| Forecast accuracy (MAPE) | `abs(actual - forecast) / actual * 100` per account | `forecast_lines` vs `actuals` |
| Claim validation pass rate | `verified_claims / total_claims` | `claims` table |
| Action completion rate | `closed_actions / created_actions` | `action_items` table |

### 4.4 Qdrant + RAG
**Wire Qdrant** for:
- Prior commentary retrieval (`rag_tools.py`: query Qdrant for similar periods)
- Policy document search
- Historical evidence pattern matching

Replace mock `rag_tools.py` with real Qdrant client queries.

---

## Phase 5: Gradual Go Migration (Week 10-11)

Only migrate where Python becomes a bottleneck:

### 5.1 Finance Core (Go)
**When:** Variance/materiality engine confirmed correct in Python, benchmarks show Python bottleneck on large datasets (>50K accounts).

**Scope:** `finance-core` service with gRPC API:
- Variance calculation (actual vs budget/forecast/prior)
- Materiality assessment (threshold + sensitivity)
- Bridge analysis (price/vol/mix, FX)
- Close readiness validation

### 5.2 Policy Engine (Go)
**When:** Complex policy rules (50+ rules per tenant) cause latency in Python policy evaluation.

**Scope:** `policy-engine` service with gRPC API:
- `EvaluatePolicy(action, context)` → auto/review/block
- `RouteApproval(investigation, materiality)` → owner
- `CheckConfidence(score, evidence_count)` → calibrated score

### 5.3 API Gateway (Go)
**When:** Need auth (SSO/SCIM), rate limiting, per-tenant routing at scale.

**Scope:** `api-gateway` with Go/Fiber:
- Auth middleware (JWT, OAuth2)
- Tenant routing from JWT claims
- Rate limiting (Redis-backed)
- Request validation
- OpenAPI spec generation

---

## Phase 6: Production Hardening (Week 12)

### 6.1 Auth & RBAC
- JWT/OAuth2 authentication
- Role-based access: Analyst, Manager, Controller/CFO, BU Leader, Data Ops
- Tenant-scoped sessions

### 6.2 Security
- SAST: Semgrep on every PR
- Dependency scan: Trivy
- Container scan: Trivy
- Secret scan: GitLeaks

### 6.3 Observability
- OpenTelemetry instrumentation in every service
- Jaeger traces for all pipeline runs
- Structured JSON logging
- Health check endpoints

### 6.4 CI/CD
- GitHub Actions: lint (ruff, mypy), test (pytest), typecheck
- Docker image build and push
- Integration test suite with Testcontainers

### 6.5 Tests (Fill Gaps)
| Layer | Current | Target |
|---|---|---|
| Unit | 78 tests | 200+ (all calculations, edge cases) |
| Integration | SQLite-based | Testcontainers for Postgres/Redis/Qdrant |
| E2E | None | Playwright for full pipeline flow |
| Agent Eval | None | Trajectory eval, RAG metrics, adversarial |

---

## Summary: What Gets Built, In Order

| Phase | What | Reuses | New |
|---|---|---|---|
| 0 | Fix float→Decimal, wire LiteLLM, connect tools to DB | All agents, validators, models | Decimal migration, tool queries |
| 1 | Data quality, bridge analysis, policy engine, PRD endpoints, action creation | Existing API, agents, DB schema | 6 new files, 12 new endpoints, 3 new DB tables |
| 2 | State machines, HITL UI, domain model tables, tenant isolation | LangGraph orchestration, frontend | 9 new DB tables, review UI, state transitions |
| 3 | Redpanda events, Temporal workflows, Redis caching | Docker Compose infra | Event producers/consumers, Temporal activities |
| 4 | Act layer, monitoring agent, metrics, Qdrant RAG | Agent patterns, tool framework | Execute agent, monitor agent, metrics engine |
| 5 | Go services (optional, bottleneck-driven) | None | finance-core, policy-engine, api-gateway |
| 6 | Auth, security, observability, CI/CD, tests | Docker Compose | Auth middleware, CI/CD config, test expansion |

---

## Key Risks

| Risk | Mitigation |
|---|---|
| **Decimal refactor breaks tests** | Update test fixtures to use `Decimal("...")` strings. Run existing 78 tests to validate no regression. |
| **LiteLLM adds latency** | LiteLLM adds <50ms proxy overhead. Cache common prompts in Redis. |
| **Temporal overhead for prototype** | Temporal is overkill for single-user dev. Add after core pipeline is complete + stable. |
| **Go migration is expensive** | Don't start Go until Python proves insufficient. Measure latency before migrating. |
| **Tool→DB connection creates load** | Tools query operational tables. Add query caching (Redis, 30s TTL) for repeated calls. |

---

**Total estimated effort:** ~12 weeks (matches PRD §12 phases, but reordered to maximize existing code reuse)
