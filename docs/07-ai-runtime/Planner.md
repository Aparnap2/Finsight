# Planner

## Purpose

The planner is the only node that uses an LLM. It receives the user's natural language query and produces a structured `ActionPlan` — an ordered list of discrete, executable actions.

## What It Does

1. Receives the original query from `ReasoningState`
2. Uses an LLM to decompose the query into intents (e.g., "compute variance", "analyse KPI", "calculate margin")
3. Produces an `ActionPlan` with one `Action` per intent
4. Stores the plan in `state.action_plan` and appends it to `state.plan_history`

## What It Never Does

- Never computes a financial value
- Never accesses financial data
- Never makes assertions about data quality
- Produces only action objectives, tool assignments, and input parameter specifications

## ActionPlan Model

```python
class ActionPlan(BaseModel):
    actions: list[Action]
    iteration: int

class Action(BaseModel):
    id: str
    objective: str
    status: ActionStatus
    inputs: dict
    outputs: dict
    tool: str
    latency_ms: float
    retry_count: int
    evidence_ids: list[str]
```

## LLM Boundary

The planner prompt includes:
- Available tools (variance engine, KPI engine, evidence engine, validation suite)
- Account taxonomy (4010 = revenue, 5010 = expenses, etc.)
- Output format (structured ActionPlan, not free text)
- Constraint: produce actions, not answers

The LLM is **never** asked to interpret financial data or draw conclusions. That is the executor's job.
