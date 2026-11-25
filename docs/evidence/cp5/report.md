# CP5 — Measured Efficiency: Prior Flow vs. Prepared-Context Flow

Cases: 4. Old total LLM calls: 3. New total LLM calls: 2. Gated (no LLM call): 2.

| Case | Eligibility | Old | New | Old tok | New tok | Gated |
|---|---|---|---|---|---|---|
| eligible_fee_discrepancy | ELIGIBLE | 1 | 1 | 134 | 228 | no |
| incomplete_evidence | INELIGIBLE | 0 | 0 | 0 | 0 | yes |
| integrity_failure | BLOCKED | 1 | 0 | 134 | 0 | yes |
| duplicate_review | REVIEW_REQUIRED | 1 | 1 | 134 | 223 | no |

## Honesty note
Both flows use a single generate_structured call (BoundedInvestigation is single-call). The prepared-context gain is NOT a reduction in LLM call count within the investigator; it is (a) gating ineligible/blocked cases before any LLM call, (b) richer evidence in the prompt, and (c) eliminating external context-gathering. Tool calls are 0 in both flows because the investigator does not use tools. No metrics stack was added.

## Baseline limitation
Old flow reproduced from the pre-CP4 code pattern (InvestigationContext built from exception row, no diagnostic, no gate). No captured historical run exists; baseline is a faithful local reproduction, not a measured production observation.
