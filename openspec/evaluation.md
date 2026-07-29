# Evaluation Impact — [Change Name]

> **Reusable template.** When proposing an AI-system change, copy this file from
> `openspec/evaluation.md` to `openspec/changes/<change-name>/evaluation.md` and
> fill out every section. Delete unused sections rather than leaving them blank.

---

## Summary

One paragraph describing what changed and why evaluation matters.
What behaviour does this change touch (planning, commentary, formula engine,
validation pipeline, etc.) and why does it warrant careful measurement?

---

## Accuracy Impact

| Field | Answer |
|---|---|
| **Which metrics are affected?** | List the 6 business metrics hit (VarianceAccuracy, KPIAccuracy, ReportCoverage, UnsupportedClaimRate, EvidenceCoverage, PolicyCompliance) and any other relevant metrics. |
| **Expected score change** | Before → After (e.g. 94.3% → 96.1%) per affected metric. |
| **Which golden datasets exercise this change?** | List dataset IDs from the 22 golden datasets that cover this path. |
| **Acceptance threshold** | Minimum score that must hold after the change (e.g. ≥ 92% on VarianceAccuracy). If no regression is the bar, state "≥ current baseline". |

### Notes

- Provide evidence for the expected delta (prototype run, ablation study, or
  reasoned argument).
- If metrics are not applicable (e.g. pure infrastructure change), state "N/A".

---

## Latency Impact

| Field | Answer |
|---|---|
| **Expected change in AverageLatency** | Δ in milliseconds per pipeline invocation. |
| **Budget check** | Default budget is **1000 ms** end-to-end. Does this change keep the pipeline under budget? |
| **New pipeline steps added/removed** | List each step added or removed and its estimated latency contribution. |

### Notes

- Measure at P50 and P99 if data is available.
- Latency increases beyond 200 ms should include a justification and a
  stated plan to optimise within one milestone.

---

## Cost Impact

| Field | Answer |
|---|---|
| **Change in LLM calls per pipeline** | Current baseline is **2 calls per pipeline** (planning + commentary). What is the new count? |
| **New compute dependencies** | Any new services, containers, libraries, or models introduced. State cost estimate if applicable. |
| **Storage impact** | New artifacts, caches, traces, or database collections. Estimate size (e.g. "~50 KB per pipeline run for trace JSON"). |

### Notes

- LLM call increases must be justified by accuracy gains.
- Consider token count changes even if the call count stays at 2 (e.g. longer
  context windows, larger system prompts).

---

## Reliability Impact

| Field | Answer |
|---|---|
| **New failure modes introduced** | Describe each new way the system could fail. |
| **Retry behaviour changes** | Any changes to retry policy, backoff strategy, or max attempts. |
| **HITL / escalation path changes** | Any changes to human-in-the-loop thresholds, escalation triggers, or manual review steps. |

### Notes

- For each failure mode, state the probability (rare / occasional / frequent)
  and the blast radius (single user / pipeline / all pipelines).
- HITL changes require a UX review note.

---

## Risk Assessment

| Field | Answer |
|---|---|
| **Hallucination risk** | Applicable to LLM changes only. Describe what new constructs the LLM can now emit and how validation gates catch incorrect output. |
| **Data quality risk** | Could this change introduce incorrect or stale data into the pipeline? |
| **Regression risk** | Likelihood that this change breaks existing behaviours on the 22 golden datasets. |
| **Mitigations** | List every safeguard: assertion pipeline steps, schema validation, constraint checks, Comparator baselines, manual review gates, etc. |

### Risk Matrix

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| Example | Low | High | Assertion pipeline rejects scores outside [0, 100] |

---

## Regression Tests

| Field | Answer |
|---|---|
| **New golden datasets needed?** | If yes, describe the scenario and expected output. |
| **Existing datasets affected?** | List each dataset ID and describe how its expected output changes. |
| **Threshold adjustments needed?** | YAML threshold changes required in the regression config. |
| **Baseline update required?** | Do Comparator baselines need to be regenerated? |

### Threshold Change Summary

```
# If thresholds change, paste the relevant YAML snippet here:
# metric:
#   VarianceAccuracy:
#     min: 0.92  # was 0.90
```

---

## Telemetry Changes

| Field | Answer |
|---|---|
| **New metrics to track** | Metric name, type (counter / gauge / histogram), and labels. |
| **New log events** | Event name, structure, and log level. |
| **Trace structure changes** | New spans, span attributes, or parent-child relationship changes. |

---

## Verification Gates

Check every gate before merging:

- [ ] **Tests pass** — `python -m pytest` (all 342 tests pass)
- [ ] **Type check passes** — `mypy .` (strict mode, no errors)
- [ ] **Lint passes** — `ruff check .` (no warnings)
- [ ] **All 12 metrics meet thresholds** — 6 runtime + 6 business metrics above their configured floor
- [ ] **No regression detected** — `Comparator` passes against the 22 golden datasets
- [ ] **Evaluation doc updated** — this file is present under `openspec/changes/<change-name>/evaluation.md`

---

## Note on `openspec/schema/workflow.yaml`

`openspec/schema/workflow.yaml` does not exist in this project. The OpenSpec
workflow is configured through `openspec/AGENTS.md` and the CLI tooling. When
the schema file is created in future, `evaluation.md` should be listed as an
**optional** artifact in the change directory scaffold alongside `proposal.md`,
`design.md`, and `tasks.md`.
