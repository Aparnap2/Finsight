# Cognitive Runtime

## Overview

The cognitive runtime is the orchestrator that drives the analysis pipeline. It implements an iterative plan-execute-verify-reflect loop that mirrors how a human financial analyst approaches variance analysis.

## Architecture

```
  Query
    │
    ▼
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ Planner  │───▶│Retriever │───▶│ Executor │───▶│Verifier  │───▶│Reflection│
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
    │                │               │               │               │
    │                │               │               │               │
    ▼                ▼               ▼               ▼               ▼
 ActionPlan     SpreadsheetData  EngineResults   Assertions      LoopDecision
                                                                    │
                                                     ┌──────────────┴──────────────┐
                                                     ▼                             ▼
                                                 "finalize"                   "revise"
                                                     │                             │
                                                     ▼                             │
                                                 Report                    ┌───────┘
                                                                          ▼
                                                                     Planner (retry)
```

## Core Components

### ReasoningHarness (`finance/cognition/harness.py`)
The top-level orchestrator. Accepts a ReasoningState, runs the configured pipeline of nodes, then checks the loop_decision. On "revise", loops back. On "finalize", stops. Captures telemetry on each run.

### ReasoningState (`finance/cognition/state/models.py`)
Pydantic model that carries state through the pipeline: query, trace of node executions, aggregated assertions, context dict, action plan, plan history, overall confidence, loop decision.

### NodeRegistry (`finance/cognition/registry.py`)
Defines the pipeline order and manages node lifecycle. Default pipeline: planner → retriever → executor → verifier → reflection.

## Iteration Loop

1. **Planner** produces an ActionPlan from the natural language query
2. **Retriever** fetches spreadsheet data based on the plan
3. **Executor** runs each action against deterministic engines
4. **Verifier** scores all assertions against their evidence
5. **Reflection** decides whether to finalize or revise

Max 5 iterations. Telemetry captures the full trace on every run.

## Key Design Decisions

- **No LLM in the loop**: After planning, all nodes are deterministic
- **ActionPlan as contract**: The planner communicates intent via structured actions, never free text
- **Assertions carry evidence**: Every claim is linked to its supporting data
- **Telemetry is structured**: JSON traces enable post-hoc analysis and debugging
