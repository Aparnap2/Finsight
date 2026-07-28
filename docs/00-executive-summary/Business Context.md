# Business Context

## The FP&A Cycle Time Problem

Financial Planning & Analysis (FP&A) teams are the analytical engine of every enterprise. They are responsible for transforming raw financial data into actionable business intelligence — variance analyses, KPI dashboards, forecast updates, and board-ready management packs. Yet despite the criticality of this function, FP&A teams consistently report that **60–80% of their time is consumed by mechanical, non-analytical work**.

### The Current Reality

A typical monthly close cycle follows this pattern:

1. **Data gathering (Days 1–3):** Export actuals from ERP (NetSuite, SAP, Oracle), pull budget data from planning systems, reconcile discrepancies between sources, and load everything into spreadsheets. This is manual, error-prone, and varies by the quality and format of each data source.

2. **Validation (Days 3–5):** Check for missing data, stale periods, inconsistent chart of accounts, and currency mismatches. These are simple checks but require institutional knowledge to perform correctly. In practice, validation happens inconsistently.

3. **Variance computation (Day 5):** Calculate actual-versus-budget variances, flag material exceptions, and compute standard KPIs. Spreadsheet formulas drift, break, or get accidentally overwritten. Minor errors here cascade into the entire analysis.

4. **Root cause investigation (Days 5–7):** For material variances, trace back to operational drivers. Why did revenue miss budget? Was it price, volume, or mix? This requires cross-referencing multiple data sources — GL accounts, headcount reports, vendor invoices, pipeline data.

5. **Commentary writing (Days 7–9):** Write narrative explanations for each material variance. This is where analysts add value, but the writing itself is formulaic — and often cut short because the earlier steps consumed the available time.

6. **Review and revision (Days 9–10):** Managers review, challenge assumptions, request corrections. The cycle may iterate 2–3 times before final approval.

**Result:** A 10-business-day close cycle that leaves **at most 2 days for actual strategic analysis.** The majority of the team's cognitive capacity is spent on clerical work.

### The Scaling Problem

As organisations grow, the problem compounds:

- **More accounts:** A mid-market company has 200–500 GL accounts. An enterprise has 5,000+.
- **More data sources:** Multi-entity consolidations, multi-currency operations, intercompany eliminations.
- **More stakeholders:** Each department head wants their own variance report with their own format.
- **Faster cycles:** The push toward continuous close and real-time FP&A means cycle times must shrink, not grow.

Hiring more analysts is not a sustainable solution — it increases headcount cost without changing the fundamental ratio of mechanical work to analytical work.

### The Trust Problem in AI-Enabled Finance

Financial systems have zero tolerance for error. A miscalculated variance of 0.1% on a $50M revenue line is a $50,000 error. An LLM that "hallucinates" a supporting number in a board pack erodes trust in the entire system.

The finance industry has learned through hard experience that:

- **LLMs cannot be trusted for financial arithmetic.** They produce plausible-looking numbers that are frequently wrong.
- **Unreferenced claims are worthless.** An FP&A analyst needs to know: *Which account? Which period? What's the source? How confident is this claim?*
- **Validation cannot be optional.** Every number must be cross-checked against a deterministic source before it reaches a report.

### The Opportunity

A system that can:

- **Automate the mechanical loop** — gathering, validating, computing, flagging
- **Preserve the analytical loop** — root cause investigation, scenario modelling, strategic recommendations
- **Eliminate calculation errors entirely** — deterministic engines with `Decimal` precision
- **Make every claim auditable** — every number traces back to a source record
- **Restrict AI to what it does well** — language generation from structured, validated data

...would transform FP&A from a cost centre constrained by cycle time into a strategic function that drives business decisions.

---

## Engagement Scope

This engagement delivered a production-ready cognitive reasoning system for FP&A that:

1. **Ingests** financial source data (GL accounts, budgets, forecasts)
2. **Validates** data quality through 6 deterministic checks (coverage, freshness, row count, source diversity, filters, quality score)
3. **Computes** variances, KPIs, materiality, and bridge decompositions — all without floating-point arithmetic
4. **Generates evidence-backed assertions** — typed, scored, and traceable to source records
5. **Applies AI reasoning** only for planning decomposition and language generation — never for computation
6. **Validates output** through a 6-metric business evaluation suite
7. **Detects regressions** automatically via threshold-based comparison against stored baselines

The architecture is **frozen after Phase 3** — the cognitive runtime is complete, stable, and ready for production use.
