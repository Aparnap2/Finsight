# Reflection

## Purpose

The reflection node examines the full execution trace and decides whether the analysis is complete or needs revision. It is the meta-cognitive layer that evaluates the evaluation itself.

## Inputs

- **Action failures**: Did any actions fail or get skipped?
- **Evidence gaps**: Are there assertions with missing evidence?
- **Confidence levels**: Is overall confidence above threshold?
- **Contradictions**: Were contradictory findings detected?
- **Plan completeness**: Did the plan cover all required intents?

## Decision Logic

```
            ┌─────────────────────────────────────┐
            │  Does the analysis meet quality      │
            │  thresholds across all dimensions?   │
            └─────────────────────────────────────┘
                         │              │
                    Yes  │              │  No
                         │              │
                         ▼              ▼
                    "finalize"      "revise"
                         │              │
                         │              ▼
                         │         Planner receives
                         │         accumulated context
                         │         and produces revised
                         │         ActionPlan
                         │
                         ▼
                    Report generated
```

## Triggers for "revise"

- Any action failed with max retries exceeded
- Overall confidence below 0.5
- More than 2 assertions with insufficient support
- Contradictory evidence detected without resolution
- Required output expectations cannot be met

## Loop Safety

The reflection node respects a hard iteration limit (default 5). After the limit is reached, it forces "finalize" regardless of quality. This prevents infinite loops while ensuring the system at least produces partial output.
