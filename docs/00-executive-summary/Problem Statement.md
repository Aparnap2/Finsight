# Problem Statement

## What We Set Out to Solve

Financial analysts manually reconcile budgets versus actuals, calculate variances, validate assertions, and produce reports. This process is:

- **Repetitive:** The same cycle of data gathering, formula checking, and variance flagging repeats every month, quarter, and year. The work is mechanical but requires financial domain knowledge to perform correctly.
- **Error-prone:** Spreadsheet formulas drift, break, or get overwritten. A single broken formula in a 10,000-row variance model can produce undetected errors across the entire analysis. Manual reconciliation misses discrepancies.
- **Difficult to scale:** Adding more accounts, entities, or data sources increases mechanical work linearly. The analytical capacity of the team remains fixed.
- **Intellectually wasteful:** Trained financial analysts spend the majority of their time on clerical work rather than the strategic analysis that justifies their compensation.

### The Core Tension

FP&A teams face an impossible trade-off: **faster close vs. higher quality.** Speeding up the close cycle by cutting validation steps increases the risk of errors reaching board packs. Slowing down to improve quality means less time for analysis and decision support.

Current approaches fail to resolve this tension:

| Approach | Problem |
|----------|---------|
| **More analysts** | Linear cost increase for (at best) linear throughput improvement |
| **Spreadsheet automation** | Macros and VBA break silently; no audit trail for changes |
| **Traditional BI tools** | Dashboards show what happened but not why; no root cause analysis |
| **LLM copilots** | Generate plausible-sounding text but cannot guarantee numerical accuracy; hallucinate financial figures |
| **ERP-native reporting** | Rigid, slow to configure, designed for statutory reporting not management analysis |

### The Gap in AI-Enabled Finance

Existing AI tools in financial analysis operate as **copilots** — they generate text when prompted but do not:

- Own the end-to-end workflow
- Enforce data quality guarantees
- Validate claims against deterministic evidence
- Guard against hallucinated financial figures
- Provide audit trails for every computed value
- Measure their own correctness through structured evaluation

They produce **drafts, not auditable outcomes.**

### What a Solution Must Guarantee

An FP&A intelligence system must meet requirements that are unusual in AI applications:

1. **100% calculation accuracy.** No AI model can be trusted for financial arithmetic. All variance computations, KPI evaluations, materiality assessments, and bridge decompositions must use deterministic code with `Decimal` precision. **Zero tolerance for numerical errors.**

2. **Audit-grade traceability.** Every number presented in a report must trace back to a specific source record. An FP&A analyst must be able to verify any claim by following its evidence chain. Claims without evidence are not permitted.

3. **Hallucination-proof architecture.** The AI's role must be limited to language generation from structured, pre-validated data. The AI must never produce financial facts — only arrange, paraphrase, and contextualise facts that were computed deterministically.

4. **Quantifiable correctness.** Beyond unit tests, the system must have a structured evaluation framework that measures planning quality, execution success, verification accuracy, reflection quality, and output correctness — all against golden datasets.

5. **Regression detection.** Changes to the system must not silently degrade correctness. A regression harness must compare current evaluation results against stored baselines with threshold-based breaking change detection.

---

## Problem Statement (One Sentence)

> Financial FP&A teams spend 60–80% of their cycle time on mechanical data work rather than analysis, because no existing system can automate the cognitive loop of *analyse → verify → reflect → revise* while guaranteeing audit-grade numerical accuracy, evidence traceability, and hallucination-free AI output.

## Success Criteria

The solution must demonstrate:

| Criterion | Measure |
|-----------|---------|
| **Calculation accuracy** | 0% error rate on all financial computations |
| **Audit readiness** | Every monetary claim traceable to a source record |
| **Hallucination rate** | 0% — LLM never produces unverified financial facts |
| **Cycle time reduction** | Variance analysis from 3 days to 30 minutes |
| **Adoption friction** | < 15 minutes to configure a new account set |
| **Correctness measurement** | 22 golden datasets across 4 categories with automatic regression detection |
