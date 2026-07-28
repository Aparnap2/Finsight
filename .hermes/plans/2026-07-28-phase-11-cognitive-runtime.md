# Phase 11 — Cognitive Runtime Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Replace the linear `Input → LLM → JSON` pipeline with a reasoning loop where the LLM is one cognitive primitive inside a larger engine that plans, retrieves, verifies, reflects, and evaluates. The plan follows vertical slices — each slice delivers a working (if limited) system before the next slice adds capability.

**Architecture:** `finance/cognition/` with `ReasoningHarness` orchestrating nodes: Planner → (Deterministic Tool Executor | LLM Reasoner) → Verifier → Reflection (+ loop). Underlying abstractions: `RetrievalManager` (multi-source), `MemoryStore` (protocol-backed), `PolicyEngine` (data-driven), `ReasoningTelemetry` (per-run trace).

**Tech Stack:** Python 3.12, Pydantic v2, pytest + pytest-httpx. Slices reference existing engines (`variance_engine`, `kpi_engine`, `evidence_engine`, `llm/`, `spreadsheet_provider`).

---

## Implementation Order

| Slice | What | Delivers | Files |
|-------|------|----------|-------|
| 1 | Harness MVP | Single-pass loop: Planner → Retriever → Verifier → Reflection | ~6 |
| 2 | Real tool wiring | Replaces dummy nodes with calls to existing engines | ~4 |
| 3 | Reflection loop | Planner re-executes on low confidence (actual iteration) | ~2 |
| 4 | RetrievalManager | Multi-source retriever (spreadsheet, policies, history) | ~4 |
| 5 | Policy Engine | Data-driven policies from YAML | ~2 |
| 6 | MemoryStore | Protocol + in-memory impl (swappable) | ~2 |
| 7 | Golden datasets | 50–100 edge-case scenarios | ~1 |
| 8 | Semantic metrics | Retrieval precision/recall, citation accuracy, reasoning depth | ~1 |
| 9 | Reasoning telemetry | Per-run trace.json, structured logs per node | ~2 |
| 10 | Docker runtime | Docker Compose for cognitive runtime only | ~3 |

---

## Slice 1 — Harness MVP

Prove the loop works. Nodes are minimal (no real engine calls, no LLM). Just state flowing through Planner → Retriever → Verifier → Reflection in a single pass.

### Task 1.1: Define `ReasoningState`

**Objective:** Create the state object that flows through every node.

**Files:**
- Create: `finance/cognition/__init__.py`
- Create: `finance/cognition/state/__init__.py`
- Create: `finance/cognition/state/models.py`
- Test: `tests/unit/test_finance/test_cognition_state.py`

**Step 1: Write failing test**

```python
from __future__ import annotations
from decimal import Decimal
import pytest
from pydantic import BaseModel


class TestReasoningState:
    def test_reasoning_state_defaults(self):
        from finance.cognition.state.models import ReasoningState
        state = ReasoningState(
            goal="Analyze Q1 revenue variance",
            company_id="acme_001",
            period_id="2026-Q1",
        )
        assert state.goal == "Analyze Q1 revenue variance"
        assert state.company_id == "acme_001"
        assert state.period_id == "2026-Q1"
        assert state.context == {}
        assert state.assertions == []
        assert state.trace == []

    def test_reasoning_state_with_assertions(self):
        from finance.cognition.state.models import ReasoningState
        from shared.models.assertions import Assertion, AssertionType, SupportLevel
        state = ReasoningState(
            goal="Check revenue",
            company_id="c1",
            period_id="P1",
            assertions=[
                Assertion(
                    id="a1",
                    type=AssertionType.NUMERIC,
                    text="Revenue up 10%",
                    value=Decimal("10000"),
                    support_level=SupportLevel.VERIFIED,
                    confidence=0.95,
                ),
            ],
        )
        assert len(state.assertions) == 1

    def test_reasoning_state_trace(self):
        from finance.cognition.state.models import ReasoningState, TraceEntry
        state = ReasoningState(goal="Analyze", company_id="c1", period_id="P1")
        state.trace.append(TraceEntry(node="planner", action="planned"))
        assert len(state.trace) == 1

    def test_reasoning_state_controls(self):
        from finance.cognition.state.models import ReasoningState
        state = ReasoningState(
            goal="Analyze", company_id="c1", period_id="P1",
            overall_confidence=0.0, iteration_count=0, max_iterations=5,
        )
        assert state.max_iterations == 5
        assert state.loop_decision == "continue"

    def test_reasoning_state_serialization(self):
        from finance.cognition.state.models import ReasoningState
        state = ReasoningState(goal="Analyze", company_id="c1", period_id="P1")
        d = state.model_dump()
        restored = ReasoningState.model_validate(d)
        assert restored.goal == state.goal
```

**Step 2: Run to verify failure** → `ModuleNotFoundError`

**Step 3: Write implementation**

```python
# finance/cognition/__init__.py
# finance/cognition/state/__init__.py

# finance/cognition/state/models.py
from __future__ import annotations
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from pydantic import BaseModel
from shared.models.assertions import Assertion


class TraceEntry(BaseModel):
    node: str
    action: str
    detail: dict[str, Any] = {}
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: float = 0.0


class ReasoningState(BaseModel):
    goal: str
    company_id: str
    period_id: str
    context: dict[str, Any] = {}
    assertions: list[Assertion] = []
    trace: list[TraceEntry] = []
    overall_confidence: float = 0.0
    iteration_count: int = 0
    max_iterations: int = 5
    loop_decision: str = "continue"
    summary: str = ""
```

**Step 4: Verify pass**

Run: `python -m pytest tests/unit/test_finance/test_cognition_state.py -v`
Expected: 5 passed

**Step 5: Commit**

```bash
git add finance/cognition/ tests/unit/test_finance/test_cognition_state.py
git commit -m "feat(slice1): add ReasoningState model"
```

---

### Task 1.2: Define `CognitiveNode` protocol + `NodeResult`

**Objective:** Unify every node behind a single protocol.

**Files:**
- Create: `finance/cognition/state/node.py`
- Test: same test file

**Test:**

```python
class TestNodeProtocol:
    def test_node_result_creation(self):
        from finance.cognition.state.node import NodeResult
        r = NodeResult(node_name="planner", state_updates={"plan": ["a"]}, confidence=0.8)
        assert r.success is True
        assert r.state_updates["plan"] == ["a"]

    def test_cognitive_node_is_protocol(self):
        import inspect
        from finance.cognition.state.node import CognitiveNode
        assert inspect.isclass(CognitiveNode)

    def test_node_result_carries_assertions(self):
        from finance.cognition.state.node import NodeResult
        from shared.models.assertions import Assertion, AssertionType
        r = NodeResult(node_name="verifier", new_assertions=[
            Assertion(id="v1", type=AssertionType.NUMERIC, text="V", confidence=0.9),
        ])
        assert len(r.new_assertions) == 1
```

**Implementation:**

```python
# finance/cognition/state/node.py
from __future__ import annotations
from typing import Any, Protocol
from pydantic import BaseModel
from shared.models.assertions import Assertion
from finance.cognition.state.models import ReasoningState


class NodeResult(BaseModel):
    node_name: str
    success: bool = True
    state_updates: dict[str, Any] = {}
    new_assertions: list[Assertion] = []
    confidence: float = 0.0
    message: str = ""
    metadata: dict[str, Any] = {}


class CognitiveNode(Protocol):
    def execute(self, state: ReasoningState) -> NodeResult:
        ...
```

---

### Task 1.3: Build all 4 minimal nodes

**Objective:** Create stub nodes that transform state without calling real engines.

**Files:**
- Create: `finance/cognition/nodes/__init__.py`
- Create: `finance/cognition/nodes/planner.py`
- Create: `finance/cognition/nodes/retriever.py`
- Create: `finance/cognition/nodes/verifier.py`
- Create: `finance/cognition/nodes/reflection.py`
- Test: `tests/unit/test_finance/test_cognition_nodes.py`

All 4 nodes follow the same pattern. Here is the planner as reference:

```python
# finance/cognition/nodes/planner.py
from finance.cognition.state.models import ReasoningState
from finance.cognition.state.node import NodeResult, CognitiveNode


class PlannerNode:
    def execute(self, state: ReasoningState) -> NodeResult:
        sub_goals = [
            "retrieve_financial_data",
            "compute_variances",
            "collect_evidence",
            "verify_claims",
        ]
        return NodeResult(
            node_name="planner",
            success=True,
            state_updates={
                "sub_goals": sub_goals,
                "plan": sub_goals,
                "current_step": 0,
            },
            confidence=0.5,
            message=f"Decomposed goal into {len(sub_goals)} sub-goals",
        )
```

Retriever: sets `context` with empty `variances`, `kpis`, `evidence_items`.
Verifier: reads `context["overall_confidence"]`, flags low-confidence assertions.
Reflection: reads `context["needs_revision"]` → sets `loop_decision` to `"finalize"` or `"revise"`.

**Tests per node:**

```python
class TestPlannerNode:
    def test_planner_creates_sub_goals(self):
        from finance.cognition.nodes import PlannerNode
        from finance.cognition.state.models import ReasoningState
        result = PlannerNode().execute(ReasoningState(goal="Analyze", company_id="c1", period_id="P1"))
        assert result.success
        assert len(result.state_updates["sub_goals"]) >= 1

    def test_planner_sets_confidence(self):
        from finance.cognition.nodes import PlannerNode
        from finance.cognition.state.models import ReasoningState
        result = PlannerNode().execute(ReasoningState(goal="A", company_id="c", period_id="p"))
        assert result.confidence >= 0.0


class TestRetrieverNode:
    def test_retriever_gathers_context(self):
        from finance.cognition.nodes import RetrieverNode
        result = RetrieverNode().execute(MockState())
        assert "context" in result.state_updates
        assert "evidence" in result.state_updates


class TestVerifierNode:
    def test_verifier_accepts_verified_assertions(self):
        from finance.cognition.nodes import VerifierNode
        state = StateWithAssertions(confidence=0.9)
        result = VerifierNode().execute(state)
        assert result.success

    def test_verifier_detects_low_confidence(self):
        from finance.cognition.nodes import VerifierNode
        state = StateWithAssertions(confidence=0.3)
        result = VerifierNode().execute(state)
        assert result.state_updates.get("needs_revision") is True


class TestReflectionNode:
    def test_reflection_decides_finalize(self):
        from finance.cognition.nodes import ReflectionNode
        result = ReflectionNode().execute(StateWithContext({"overall_confidence": 0.85}))
        assert result.state_updates["loop_decision"] == "finalize"

    def test_reflection_decides_revise(self):
        from finance.cognition.nodes import ReflectionNode
        result = ReflectionNode().execute(StateWithContext({"overall_confidence": 0.3, "needs_revision": True}))
        assert result.state_updates["loop_decision"] == "revise"
```

---

### Task 1.4: Build `ReasoningHarness` (single pass)

**Objective:** Orchestrate Planner → Retriever → Verifier → Reflection in sequence.

**Files:**
- Create: `finance/cognition/harness.py`
- Test: `tests/unit/test_finance/test_cognition_harness.py`

```python
class TestReasoningHarness:
    def test_harness_single_pass(self):
        from finance.cognition.harness import ReasoningHarness
        from finance.cognition.state.models import ReasoningState
        harness = ReasoningHarness()
        state = ReasoningState(goal="Analyze revenue", company_id="c1", period_id="P1")
        result = harness.run(state)
        assert result.success
        assert len(result.state.trace) >= 4  # all 4 nodes

    def test_harness_trace_contains_all_nodes(self):
        from finance.cognition.harness import ReasoningHarness
        from finance.cognition.state.models import ReasoningState
        result = ReasoningHarness().run(ReasoningState(goal="A", company_id="c", period_id="p"))
        nodes = [t.node for t in result.state.trace]
        assert "planner" in nodes
        assert "retriever" in nodes
        assert "verifier" in nodes
        assert "reflection" in nodes

    def test_harness_respects_max_iterations(self):
        from finance.cognition.harness import ReasoningHarness
        from finance.cognition.state.models import ReasoningState
        state = ReasoningState(goal="A", company_id="c", period_id="p", max_iterations=1)
        ReasoningHarness().run(state)
        assert state.iteration_count <= 1
```

**Implementation:**

```python
# finance/cognition/harness.py
from datetime import UTC, datetime
from finance.cognition.state.models import ReasoningState, TraceEntry
from finance.cognition.state.node import NodeResult
from finance.cognition.nodes import PlannerNode, RetrieverNode, VerifierNode, ReflectionNode


class HarnessResult:
    def __init__(self, state: ReasoningState, success: bool = True):
        self.state = state
        self.success = success


class ReasoningHarness:
    def __init__(self, max_iterations: int = 5):
        self.max_iterations = max_iterations
        self._planner = PlannerNode()
        self._retriever = RetrieverNode()
        self._verifier = VerifierNode()
        self._reflection = ReflectionNode()

    def run(self, state: ReasoningState) -> HarnessResult:
        while state.iteration_count < min(state.max_iterations, self.max_iterations):
            state.iteration_count += 1
            state = self._apply(self._planner, state, "planner")
            state = self._apply(self._retriever, state, "retriever")
            state = self._apply(self._verifier, state, "verifier")
            state = self._apply(self._reflection, state, "reflection")
            if state.loop_decision == "finalize":
                break
        state.overall_confidence = state.context.get("overall_confidence", 0.0)
        return HarnessResult(state=state, success=True)

    def _apply(self, node, state: ReasoningState, name: str) -> ReasoningState:
        started = datetime.now(UTC)
        result = node.execute(state)
        completed = datetime.now(UTC)
        duration = (completed - started).total_seconds() * 1000
        state.trace.append(TraceEntry(
            node=name, action=result.message, detail=result.state_updates,
            started_at=started, completed_at=completed, duration_ms=duration,
        ))
        for key, value in result.state_updates.items():
            if key == "loop_decision":
                state.loop_decision = value
            else:
                state.context[key] = value
        state.assertions.extend(result.new_assertions)
        return state
```

---

## Slice 2 — Real Tool Wiring

Replace stub nodes with actual calls to existing engines. The pattern: each node calls the real engine instead of returning dummy data.

### Task 2.1: Wire RetrieverNode to SpreadsheetProvider + EvidenceEngine

**Objective:** `RetrieverNode.execute()` reads actual data via `SpreadsheetProvider` and `EvidenceEngine`.

**Files:**
- Modify: `finance/cognition/nodes/retriever.py`
- Test: `tests/unit/test_finance/test_cognition_retriever_real.py`

**Key pattern — dependency injection:**

```python
class RetrieverNode:
    def __init__(self, sheet_provider=None, evidence_engine=None):
        from finance.integration.spreadsheet_provider import SpreadsheetProvider
        from finance.evidence.engine import EvidenceEngine
        self._sheet = sheet_provider or SpreadsheetProvider()
        self._evidence = evidence_engine or EvidenceEngine()
```

**Test with mocks:**

```python
def test_retriever_calls_spreadsheet_provider(self):
    from unittest.mock import MagicMock
    from finance.cognition.nodes import RetrieverNode
    sheet = MagicMock()
    sheet.fetch.return_value = {"4010": {"actual": 100000, "budget": 95000}}
    node = RetrieverNode(sheet_provider=sheet, evidence_engine=MagicMock())
    result = node.execute(MockState())
    sheet.fetch.assert_called_once()
```

### Task 2.2: Wire VerifierNode to existing `ResponseValidator` + `AssertionPipeline`

**Objective:** `VerifierNode` runs the existing `run_assertion_pipeline()` and `ResponseValidator` instead of a toy check.

### Task 2.3: Wire LLM Reasoner as a node (not a tool)

**Objective:** Create `ReasonerNode` that calls `LLMClient.generate()` for tasks requiring reasoning (commentary, root cause analysis). This is distinct from deterministic tool execution.

```python
# finance/cognition/nodes/reasoner.py
class ReasonerNode:
    def __init__(self, llm_client=None):
        from finance.llm.client import LLMClient
        self._llm = llm_client or LLMClient()

    def execute(self, state: ReasoningState) -> NodeResult:
        # Called for commentary generation, root cause analysis, etc.
        # Not called for deterministic computation (variances, KPIs)
        ...
```

The `ToolRouter` (added in Slice 3) decides whether a sub-goal goes to:
- Deterministic executor (variance engine, KPI engine, spreadsheet provider)
- `ReasonerNode` (LLM for commentary, root cause, narrative)

---

## Slice 3 — Reflection Loop

### Task 3.1: Wire Reflection → Planner iteration

Make `ReflectionNode` set `loop_decision="revise"` when confidence is low, causing the harness to re-run the Planner with updated context.

**Harness becomes:**

```python
def run(self, state: ReasoningState) -> HarnessResult:
    while state.iteration_count < max_iterations:
        state.iteration_count += 1
        state = self._apply(self._planner, state, "planner")
        state = self._apply(self._retriever, state, "retriever")
        state = self._apply(self._verifier, state, "verifier")
        state = self._apply(self._reflection, state, "reflection")
        if state.loop_decision == "finalize":
            break
        # "revise" → loop continues, planner re-runs with enriched state
    return HarnessResult(state=state, success=True)
```

### Task 3.2: Planner re-plans based on gaps

`PlannerNode` reads `context["gaps"]` from previous reflection iteration and prioritizes missing evidence.

---

## Slice 4 — RetrievalManager

### Task 4.1: Define `RetrievalManager` with sub-retrievers

```python
# finance/cognition/retrieval/__init__.py

class RetrievalManager:
    def __init__(self):
        self._retrievers = [
            SpreadsheetRetriever(),
            PolicyRetriever(),
            HistoryRetriever(),
            MemoryRetriever(),
        ]

    def retrieve(self, goal: str, company_id: str) -> RetrievalResult:
        results = [r.fetch(goal, company_id) for r in self._retrievers]
        merged = self._merge(results)
        ranked = self._rank(merged, goal)
        compressed = self._compress(ranked)
        return RetrievalResult(
            context=compressed,
            sources=[r.name for r in self._retrievers if r.has_data],
            evidence=compressed["evidence"],
        )


class SpreadsheetRetriever:
    name = "spreadsheet"
    def fetch(self, goal, company_id) -> dict: ...
```

---

## Slice 5 — Policy Engine (data-driven)

```python
# finance/cognition/policies/engine.py
import yaml
from pathlib import Path


class PolicyEngine:
    def __init__(self, policy_path: str | None = None):
        path = policy_path or Path(__file__).parent / "defaults.yaml"
        with open(path) as f:
            self._policies = yaml.safe_load(f)

    def get(self, domain: str = "general") -> list[dict]:
        return [p for p in self._policies if p.get("domain") in (domain, "general")]

    def apply(self, name: str, context: dict) -> dict:
        policy = next((p for p in self._policies if p["name"] == name), {})
        # Generic rule evaluation (no hardcoded ASC 606 logic)
        ...
```

```yaml
# finance/cognition/policies/defaults.yaml
- name: materiality
  domain: general
  rule: threshold_pct
  params:
    threshold: 5.0
  description: Variances above threshold are material

- name: approval_limit
  domain: expense
  rule: max_amount
  params:
    amount: 50000
  description: Expenses over amount require CFO approval
```

---

## Slice 6 — MemoryStore Protocol

```python
# finance/cognition/memory/store.py
from typing import Any, Protocol


class MemoryStore(Protocol):
    def store(self, company_id: str, key: str, value: Any) -> None: ...
    def retrieve(self, company_id: str, key: str) -> Any | None: ...
    def store_error(self, company_id: str, error: str, component: str) -> None: ...
    def get_errors(self, company_id: str) -> list[dict]: ...


class InMemoryStore:
    def __init__(self):
        self._data: dict[str, dict[str, Any]] = {}
        self._errors: dict[str, list[dict]] = {}

    def store(self, company_id: str, key: str, value: Any) -> None:
        self._data.setdefault(company_id, {})[key] = value

    def retrieve(self, company_id: str, key: str) -> Any | None:
        return self._data.get(company_id, {}).get(key)

    def store_error(self, company_id: str, error: str, component: str) -> None:
        self._errors.setdefault(company_id, []).append({
            "error": error, "component": component,
        })

    def get_errors(self, company_id: str) -> list[dict]:
        return self._errors.get(company_id, [])
```

Later: RedisStore, PostgresStore implement same protocol, swapped at construction.

---

## Slice 7 — Golden Datasets (50–100)

### Task 7.1: Replace `_build_builtins()` with scenario files

**Files:**
- Create: `finance/evaluation/scenarios/` (one YAML per scenario or a single large loader)
- Keep: `finance/evaluation/loader.py`

**Scenarios focused on edge cases:**

| Category | Scenarios |
|----------|-----------|
| **Revenue** | drop 15%, surge 40%, flat MoM, zero, negative, new product, seasonality, FX impact, pricing change, volume shift |
| **Expense** | overspend 2x, underspend, hiring freeze, layoff severance, restructuring, R&D scale, one-time charge |
| **Cash flow** | runway < 3mo, DSO spike, inventory surge, capex overrun, dividend cut, debt covenant |
| **Data quality** | missing budget, missing GL, duplicate txns, currency mismatch, empty sheet, fiscal overlap, future period |
| **Edge cases** | hallucination bait (plausible numbers), contradictory KPIs, conflicting evidence, retrieval ambiguity, context overflow, policy violation, approval limit breach |

Each scenario is a `GoldenDataset` with:
- `input_data` (minimal accounts + actuals/budget)
- `expected_variances` (exact numbers)
- `expected_kpis` (3–5)
- `expected_report_sections` (executive_summary + key content)
- `tags` for filtering

**Test:**

```python
def test_loader_has_50_plus_datasets(self):
    from finance.evaluation.loader import GoldenDatasetLoader
    assert len(GoldenDatasetLoader().load_all()) >= 50

def test_all_datasets_unique_ids(self):
    ds = GoldenDatasetLoader().load_all()
    ids = [d.id for d in ds]
    assert len(ids) == len(set(ids))

def test_covers_edge_tag(self):
    from finance.evaluation.loader import GoldenDatasetLoader
    all_tags = set(t for d in GoldenDatasetLoader().load_all() for t in d.tags)
    assert "edge_case" in all_tags
```

---

## Slice 8 — Semantic Metrics

Add to `finance/evaluation/metrics.py`:

```python
class CitationAccuracy:
    """Claims should cite the right evidence IDs."""
    @staticmethod
    def compute(claims: list[str], expected_citations: list[list[str]], actual_citations: list[list[str]]) -> float: ...

class RetrievalPrecision:
    """Fraction of retrieved items that are relevant."""
    @staticmethod
    def compute(relevant: int, retrieved: int) -> float: ...

class RetrievalRecall:
    """Fraction of relevant items that were retrieved."""
    @staticmethod
    def compute(relevant: int, total_relevant: int) -> float: ...

class ContextUtilization:
    """Fraction of provided context actually referenced in output."""
    @staticmethod
    def compute(context_items: int, referenced_items: int) -> float: ...

class ReasoningDepth:
    """Number of reasoning steps before reaching conclusion."""
    @staticmethod
    def compute(loop_count: int, max_loops: int) -> float: ...

class PlanningEfficiency:
    """Were sub-goals achieved without unnecessary replanning?"""
    @staticmethod
    def compute(replans: int, total_steps: int) -> float: ...
```

---

## Slice 9 — Reasoning Telemetry

### Task 9.1: Structured per-run logging

```python
# finance/cognition/telemetry.py
import json
from pathlib import Path
from datetime import UTC, datetime
from finance.cognition.state.models import ReasoningState


class ReasoningTelemetry:
    def __init__(self, output_dir: str = ".reasoning_traces"):
        self._dir = Path(output_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def capture(self, run_id: str, state: ReasoningState) -> Path:
        trace = {
            "run_id": run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "goal": state.goal,
            "company_id": state.company_id,
            "period_id": state.period_id,
            "iteration_count": state.iteration_count,
            "overall_confidence": state.overall_confidence,
            "loop_decision": state.loop_decision,
            "assertions": [a.model_dump() for a in state.assertions],
            "trace": [t.model_dump() for t in state.trace],
            "context_keys": list(state.context.keys()),
        }
        path = self._dir / f"{run_id}.json"
        path.write_text(json.dumps(trace, indent=2, default=str))
        return path
```

Each node also logs its own prompt + response to a node-specific file:

```
.reasoning_traces/
  run_abc123/
    trace.json
    planner.json
    retriever.json
    verifier.json
    reflection.json
    timings.json
```

---

## Slice 10 — Docker Runtime

Only after Slices 1–9 pass all local tests.

- `Dockerfile.cognition` — minimal Python image with `finance/` only
- `docker-compose.yml` — cognition service + (optional) Postgres/Redis for memory
- `Makefile` target: `make cognition-up`

---

## Verification (after each slice)

```bash
python -m pytest tests/unit/ -v --tb=short 2>&1 | tail -10
uv run ruff check .
uv run mypy .
```

Every slice must leave the test suite green.

---

## Summary

| Slice | Delivers | Files | Tests |
|-------|----------|-------|-------|
| 1 | Working harness with stub nodes | ~6 | ~12 |
| 2 | Nodes wired to real engines | ~4 | ~8 |
| 3 | Multi-pass reflection loop | ~2 | ~4 |
| 4 | RetrievalManager with sub-retrievers | ~4 | ~5 |
| 5 | Data-driven policy engine | ~2 | ~3 |
| 6 | MemoryStore protocol + impl | ~2 | ~4 |
| 7 | 50–100 edge-case golden datasets | ~1 | ~4 |
| 8 | Retrieval/semantic metrics | ~1 | ~8 |
| 9 | Per-run structured telemetry | ~2 | ~3 |
| 10 | Docker Compose for runtime | ~3 | — |
