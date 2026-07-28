# ADR-005: Why Context Packs — Never Send Raw Spreadsheet Rows to an LLM

**Status:** Accepted  
**Date:** 2026-07-28  
**Deciders:** Architecture Team  

---

## Context

When the root-cause agent or commentary agent needs context to do its work, the naive approach is to send raw data to the LLM — e.g., "here are all 5,000 rows of the general ledger, tell me what happened." This fails for multiple reasons:

- **Token limits.** A full chart of accounts with 500+ line items exceeds most LLM context windows. Truncation loses information and produces biased analysis.
- **Noise obscures signal.** LLMs are poor at identifying relevant rows in a sea of uniform data. They hallucinate patterns or fixate on outliers.
- **No validation context.** Raw rows don't carry data quality metadata, confidence scores, or materiality flags. The LLM has no way to distinguish a reliable figure from a stale estimate.
- **Nondeterministic responses.** The same data presented differently (different row order, different column names) can produce different LLM responses.

The core problem: **LLMs need context, but they don't need all the data.** They need a curated, structured summary that highlights what matters and suppresses what doesn't.

## Decision

Introduce **Finance Context Packs** — validated, structured context objects that are the **only** way data reaches an LLM.

### What Is a Context Pack?

A Context Pack is a Pydantic `BaseModel` that assembles pre-processed, pre-validated context for a specific LLM interaction. It is built by deterministic code in `finance/` and `shared/` and is the exclusive carrier of data to `agents/`.

```python
class FinanceContextPack(BaseModel):
    """The only way data reaches an LLM agent."""
    period: str
    entity_id: str

    # Pre-computed, never raw
    material_variances: list[MaterialVarianceSummary]
    kpi_summary: list[KpiSummary]
    bridge_summary: list[BridgeSummary] | None = None

    # Pre-validated assertions only — never raw evidence
    assertions: list[Assertion]

    # Quality metadata for every data point
    data_quality: DataQualitySummary

    # Degraded modes affect interpretation
    degraded_modes: list[DegradedMode]

    # Explicit exclusions (what to ignore)
    excluded_accounts: list[str] = []
```

Key properties:
- **No raw ledger rows.** Every data point has been computed, summarised, and validated by deterministic code.
- **Pre-materiality-filtered.** Only material variances are included. Immaterial items are excluded entirely.
- **Assertion-attached context.** Every data point in the pack carries its associated `Assertion` — the LLM sees validated claims, not raw figures.
- **Quality metadata.** Every pack includes `DataQualitySummary` so the LLM can (and must) qualify its analysis based on data reliability.
- **Deterministically assembled.** The pack is built by `finance/assertion_pipeline.py` — no LLM involvement in construction.

### The Prohibition

> **No raw spreadsheet rows, no raw database records, no unprocessed data is ever sent to an LLM.**

This includes:
- No raw CSV rows
- No raw SQL query results
- No unprocessed general ledger extracts
- No unprocessed Google Sheets ranges
- No raw tool output (unless it passes through the assertion pipeline first)

### Context Pack Assembly Pipeline

```
Raw Data (DB/Sheets/CSV)
    │
    ▼
finance/ingestion/ → Structured dicts
    │
    ▼
finance/variance_engine/ → Materiality assessment → Only material items
    │
    ▼
finance/assertion_pipeline/ → Typed Assertions with evidence IDs
    │
    ▼
shared/utils/tools/ → ToolResult → DataQualityReport
    │
    ▼
FinanceContextPack.Builder (deterministic)
    │
    ▼
agents/root_cause_agent OR agents/commentary_agent (LLM receives pack)
```

### Context Pack Variants

| Pack | Recipient | Contents |
|------|-----------|----------|
| `RootCauseContextPack` | Root-cause agent | Material variances, bridge decomposition, prior-period trends, account metadata |
| `CommentaryContextPack` | Commentary agent | Verified assertions only, data quality summary, required sections, audience |
| `ScenarioContextPack` | Scenario agent | Current forecast, historical trends, constraint parameters, policy rules |

## Consequences

### Positive

- **LLM sees only what matters.** Token usage drops dramatically. The root-cause agent receives 20–50 material variance summaries instead of 5,000 ledger rows.
- **No LLM data filtering bias.** The LLM never decides which data is important — that's determined by the materiality engine. All items in the pack are, by construction, material and relevant.
- **Consistent LLM input.** The same financial situation always produces the same Context Pack (deterministic assembly). LLM nondeterminism is reduced to true variation in output text, not variation in input structure.
- **Traceability.** Every item in a Context Pack carries its provenance (`source_table`, `record_id`, `field`). The LLM can cite evidence, and the citation can be traced back to source.
- **Security boundary.** Context Packs are a formalised data minimisation mechanism. Sensitive immaterial data is excluded by policy, not by chance.

### Negative

- **Assembly complexity.** Building a Context Pack requires the deterministic engines to run first. The ingestion → variance → assertion → pack sequence is sequential and increases pipeline latency.
- **Schema maintenance.** Every new agent or new analysis type requires a new Context Pack variant (or at least a schema extension).
- **Loss of low-level detail.** If the LLM needs to inspect a specific sub-ledger transaction that was excluded by materiality, it cannot — the data is gone. Mitigated by allowing the root-cause agent to make targeted tool calls for specific accounts.
- **Rigidity for exploration.** Context Packs are optimized for analysis, not exploration. If an FP&A analyst wants "show me everything unusual this month," the pack may pre-filter too aggressively.

## Compliance

1. **No LLM prompt contains raw data.** All prompt templates in `shared/prompts/` are audited — no variable contains unprocessed CSV, SQL, or spreadsheet content.
2. **Context Pack is the only carrier.** Agent node functions accept `FinanceContextPack` as their data input. They do not accept `list[dict]`, `pd.DataFrame`, or raw text data.
3. **Every LLM agent documents its Context Pack schema.** The `## Context` section of every agent prompt template documents which pack fields it consumes.
4. **Context Pack assembly is tested.** Each pack variant has a golden-data test: given fixed inputs, the pack assembles deterministically.
5. **No `pd.DataFrame` crosses into `agents/`.** Pandas DataFrames are banned from agent inputs. All structured data must be Pydantic models or typed lists thereof.
