## Why
Payment succeeds but Stripe, QuickBooks, and Sheets disagree, forcing humans to manually hunt down why money movement and system records diverge.

## What Changes
- **BREAKING** Pivot scope from broad FP&A platform to agentic reconciliation: payment-to-ledger matching is the P0 capability.
- Add deterministic reconciliation engine covering ~80% of cases with exact and tolerance-based matching.
- Add 3 versioned exception types: partial-refund lag (flagship: 50k authorized / 15k refunded / 35k settled), fee mismatch (`max(1.00, 0.5%)`), and duplicate entry.
- Add LLM planner-only layer (~20%) via Groq with swappable `LLMProvider` interface for explanation and next-action planning; LLM never mutates balances directly.
- Add HITL review queue with approve/reject for low-confidence and material exceptions.
- Enforce sandbox-only writes with post-verify close: no production ledger mutation until verification passes.

## Impact
- Affected specs: new `reconciliation` capability (ADDED).
- Affected code:
  - `finance/reconciliation` — matching engine, exception classifiers, tolerance rules.
  - `agents/exceptions` — planner-only triage and explanation nodes.
  - `apps/api` — webhooks ingestion (Stripe/QB/Sheets) and review endpoints.
  - `shared` — contracts, assertion schemas, `LLMProvider` interface.
- Non-goals:
  - No ERP close, management packs, or forecasts in P0.
  - No Qdrant / vector memory initially.
  - No Go extraction service in P0.
  - No real QuickBooks / Gmail integration in P0 (sandbox fixtures only).
