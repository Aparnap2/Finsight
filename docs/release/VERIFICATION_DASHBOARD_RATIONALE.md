# Report: Custom UI vs. Existing Observability Dashboards for FinSight E2E Verification

## Question

Why build a custom read-only NiceGUI viewer (`/gui/verification`) when monitoring and observability tools (Grafana, Datadog, New Relic, etc.) already provide dashboards?

## Short answer

The custom viewer and the observability tools answer **different questions from different data**. The custom viewer is a *verification artifact consumer*; observability tools are *runtime telemetry consumers*. They are complementary, not competing. However, the custom viewer's scope should be kept deliberately small, and several of its planned capabilities are better served by existing tools.

---

## 1. What the custom viewer actually does

The `/gui/verification` page (commit `8fc6cbf`) is a **read-only consumer of a machine-readable E2E evidence report** (`E2ERunReport` Pydantic schema, `finance/verification/evidence.py`). It displays:

| Question it answers | Data source | Could an observability tool answer it? |
|---|---|---|
| Did the complete workflow execute? | `stages[]` with status per stage | Partially — trace spans show stages, but not the pass/fail verdict of a test scenario |
| Did financial results match expected? | `scenarios[].expected` vs `scenarios[].actual` + golden fixture | **No** — observability tools do not have the independently-defined golden expected values |
| What did the LLM receive and return? | `provider` (model, request_id, latency) + investigation output | Partially — trace spans show provider calls, but not the structured diagnostic envelope or eligibility decision |
| Was everything persisted correctly? | Persisted IDs (run_id, exception_ids, investigation_id, export_id, decision_id) | Partially — DB queries can verify, but not in a single dashboard view |
| Did the real provider call and trace export happen? | `provider.request_id`, `trace.trace_id`, `trace.exported` | Partially — trace backend confirms export, but not the correlation to a specific scenario's expected outcome |

**Core distinction:** The viewer compares **expected vs. actual financial values** from a version-controlled golden fixture against persisted database state. No observability tool has access to the golden fixture or the test verdict. The verifier (`finance/verification/verifier.py`) produces a deterministic `VERIFIED/FAILED/INCOMPLETE` verdict that the viewer displays but never calculates.

---

## 2. What existing observability tools do better

The codebase already references OpenTelemetry and tracing (`OTEL_EXPORTER_OTLP_ENDPOINT` in the staging workflow). Existing tools would handle these better than a custom UI:

| Capability | Better served by | Why |
|---|---|---|
| Request traces, span timing, latency percentiles | Jaeger, Tempo, Datadog APM | Purpose-built for distributed tracing; the custom viewer only shows a single latency number |
| Log aggregation and search | Loki, Elasticsearch, CloudWatch Logs | Full-text search, filtering, correlation by trace ID; the viewer has no log search |
| Metric dashboards (request rate, error rate, latency) | Grafana, Datadog | Time-series visualization, alerting, anomaly detection |
| Infrastructure health (CPU, memory, DB connections) | Prometheus + Grafana, CloudWatch | Real-time resource monitoring |
| Alerting on failures | PagerDuty, Grafana alerts | Automated notification; the viewer is pull-only |
| Provider call cost tracking | Provider dashboards (Groq, OpenAI) | Token usage, cost breakdowns |
| Historical trend analysis | Any TSDB-backed tool | The viewer shows a single run; observability tools show trends over time |

**Conclusion:** For runtime monitoring, alerting, and historical analysis, existing tools are strictly superior. The custom viewer should not attempt to replace them.

---

## 3. Where the custom viewer adds value that tools cannot

1. **Golden fixture comparison.** The viewer compares independently-defined expected financial values (from `tests/fixtures/reconciliation/golden_scenarios.json`) against actual persisted results. No observability tool has the golden fixture or the test oracle. This is the core trust mechanism.

2. **Deterministic verdict.** The `verify_run()` function produces a `VERIFIED/FAILED/INCOMPLETE` verdict from the evidence report + golden fixture. This is a test verdict, not a runtime metric. Observability tools don't produce test verdicts.

3. **Single-run forensic view.** A developer or reviewer can paste a report JSON and see the complete story of one E2E run — every stage, every scenario, every persisted ID, every provider call — in one place. Observability tools require navigating multiple dashboards (traces in Jaeger, logs in Loki, metrics in Grafana).

4. **No external dependency.** The viewer works offline with a pasted JSON report. No OTLP collector, no Grafana instance, no cloud account needed. This matters for local development and air-gapped review.

5. **Read-only, no verdict authority.** The viewer explicitly does not calculate verdicts. It displays what the verifier computed. This is a deliberate trust boundary that observability tools don't enforce.

---

## 4. Where the custom viewer is redundant or should be removed

| Custom viewer feature | Better alternative | Recommendation |
|---|---|---|
| Provider latency display | Trace span in Jaeger/Tempo | Keep in viewer for convenience, but defer to tracing tool for analysis |
| Stage timeline | Trace spans | Keep — the stage list is a test concept, not a trace concept |
| Financial invariants display | N/A (test-specific) | Keep — no observability tool knows about these |
| Run metadata (commit, image digest) | CI/CD system (GitHub Actions) | Keep in viewer for forensic completeness, but CI already shows this |
| Provider success/failure | Trace span status + alerting | Keep for the single-run view, but alerting belongs in observability tools |

---

## 5. Recommended architecture: viewer as a thin forensic layer

The correct relationship is:

```
┌─────────────────────────────────────────────────────────────┐
│  CI / Staging E2E Run                                       │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ Golden      │  │ Application  │  │ E2E Evidence     │   │
│  │ Fixture     │→ │ (real app)   │→ │ Report (JSON)    │   │
│  │ (human-     │  │              │  │                  │   │
│  │  verified)  │  │              │  │                  │   │
│  └─────────────┘  └──────┬───────┘  └────────┬─────────┘   │
│                          │                   │             │
│                          │                   │             │
│                          ▼                   ▼             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Deterministic Verifier (finance/verification/)     │   │
│  │  → VERIFIED / FAILED / INCOMPLETE                   │   │
│  └────────────────────┬────────────────────────────────┘   │
│                       │                                     │
│                       ▼                                     │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Read-Only NiceGUI Viewer (/gui/verification)       │   │
│  │  Displays report + verifier verdict. Never computes.│   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ (runtime telemetry flows separately)
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Observability Stack (Jaeger/Tempo + Grafana + Loki)       │
│  - Traces, logs, metrics from the running application      │
│  - Alerting, dashboards, historical trends                  │
│  - Provider call timing, error rates, resource usage        │
└─────────────────────────────────────────────────────────────┘
```

**Key principle:** The viewer consumes the E2E evidence report. The observability stack consumes runtime telemetry. They share the trace ID (so you can click from the viewer to the trace backend), but they are separate systems with separate data.

---

## 6. What should NOT be in the custom viewer

To avoid scope creep, the viewer should **not**:

1. **Replace Grafana/Jaeger for runtime monitoring.** If you want to see request latency trends over time, use Grafana. The viewer shows one run's latency.
2. **Store historical runs.** The viewer reads a single report JSON. Historical comparison should use the CI artifact store or a database.
3. **Send alerts.** Alerting belongs in the observability stack or GitHub Actions.
4. **Perform calculations.** The verifier does that. The viewer is display-only.
5. **Show production data.** The viewer is for CI/staging E2E runs with synthetic data.

---

## 7. Honest assessment

**Was building the custom viewer the right call?**

Yes, but with caveats:

- **Right call because:** No existing tool can compare a version-controlled golden fixture against persisted DB state and produce a test verdict. The viewer makes this comparison human-readable. It is a forensic tool for a specific artifact (the E2E report), not a general-purpose dashboard.

- **Caveat:** The viewer is only as trustworthy as the golden fixture and the verifier. If the golden fixture is wrong (agent-observed, not human-verified), the viewer will confidently display incorrect expected values. The viewer cannot fix this — only human verification of the fixture can.

- **Caveat:** The viewer should not grow into a general-purpose observability dashboard. If there's demand for runtime monitoring, the correct investment is configuring Grafana + Jaeger/Tempo against the existing OTLP export, not extending NiceGUI.

**Recommendation:** Keep the viewer as-is (it is small, read-only, and serves a specific forensic purpose). Invest in the observability stack separately when production monitoring becomes a priority. The two systems are complementary: the viewer answers "did this specific E2E run produce the correct financial result?" and the observability stack answers "is the application healthy right now?"
