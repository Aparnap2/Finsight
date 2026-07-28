# Decision Log

Architectural and design decisions for FinSight, with rationale and context.

---

## Why Google Sheets

**Decision:** Use Google Sheets as the primary data source for MVP.

**Context:** The MVP must deliver working FP&A analysis within weeks. Every FP&A team uses spreadsheets. Spreadsheets are the universal interface for financial data — they require no integration contracts, no API keys, no vendor procurement cycles.

**Rationale:**
- Spreadsheet-first is how FP&A works today. FinSight meets practitioners where they are.
- Google Sheets provides a REST API, change notifications, and familiarity for finance teams.
- Connecting to NetSuite, Workday, or SAP requires months of integration work with no guarantee of data quality at the end. A spreadsheet upload (or Google Sheet connection) delivers value in days.
- The architecture supports adding ERP connectors later. The `finance/ingestion/` module is designed to accept multiple source types behind a common interface.

**Trade-off:** We accept manual data export workflows in the short term. The `FinanceFirst` principle says domain logic must be built and tested on real financial data before we optimize data sourcing. Spreadsheets provide that data today.

---

## Why No Dashboards

**Decision:** FinSight does not include a dashboard or visualization layer.

**Context:** The product vision is an autonomous FP&A operator — not a BI tool. Dashboards are a fundamentally different product category with different user workflows, performance characteristics, and UX patterns.

**Rationale:**
- FinSight's value is *intelligence*, not *visualization*. The system detects variances, investigates root causes, and produces structured commentary. That output can be consumed by existing BI tools (Tableau, Power BI, Metabase, Grafana).
- Building a dashboard competes with every BI vendor. Building an AI-powered FP&A analyst is a new category.
- Dashboards require significant frontend investment: charting libraries, responsive layouts, drill-down UX, query builders. That investment would divert resources from the core agent pipeline.
- FinSight produces structured outputs (JSON assertions, markdown reports) that any dashboard tool can consume via API.

**Trade-off:** Users who want a visual dashboard must bring their own. We provide well-documented API endpoints and webhook delivery to integrate with their existing tools.

---

## Why No Workflow Engine

**Decision:** FinSight does not integrate a general-purpose workflow engine (Airflow, Prefect, Temporal).

**Context:** Finance workflows are unique per organization. Month-end close processes vary dramatically in sequencing, approval chains, and stakeholder dependencies. A generic DAG-based workflow engine would require every tenant to model their process in a new DSL.

**Rationale:**
- FP&A workflows are human-dependent (waiting for stakeholder input) and conditional (materiality determines depth of investigation). General workflow engines optimize for deterministic task graphs with clear completion signals.
- The LangGraph state machine in `agents/orchestrator.py` already provides the pipeline routing FinSight needs: ingestion → variance → root cause → commentary → scenario → review. Adding a workflow engine would add operational complexity (workers, queues, retry logic) without improving the pipeline.
- Finance process differences are best handled through policy configuration (materiality thresholds, approval rules, routing), not workflow DAGs.

**Trade-off:** Tenants with highly custom close processes may need to adapt their workflow to FinSight's pipeline model. The policy engine in `shared/utils/policy.py` provides configurable routing without workflow orchestration.

---

## Why Deterministic Calculations

**Decision:** All financial calculations are deterministic — never performed by an LLM.

**Context:** LLMs are probabilistic. They produce different outputs for the same input, exhibit math errors, and hallucinate values. Financial calculations must be exact, repeatable, and auditable.

**Rationale:**
- LLMs cannot perform reliable arithmetic on monetary values. A variance of $1,234.56 vs $1,234.55 is materially different in audit context — LLMs routinely make such errors.
- Financial calculations must be auditable: every number must be traceable to source data and a specific formula. Deterministic code provides this guarantee; LLM black boxes do not.
- The formula registry (`finance/formula_engine/formula_registry.py`) evaluates all calculations through pure Python functions with `Decimal` arithmetic. No LLM is involved in computing a single financial metric.
- LLMs are used only for *rendering* validated data into narrative text — and even that output is validated against the source assertions.

**Trade-off:** New formulae require code changes and deployments, not prompt edits. This is by design: financial logic should be version-controlled, reviewed, and tested like any other production code.

---

## Why No Autonomous Approvals

**Decision:** FinSight never takes financial actions without human approval.

**Context:** The system can detect variances, investigate causes, draft commentary, and recommend actions. It cannot execute journal entries, update forecasts, or publish reports without human sign-off.

**Rationale:**
- Financial operations have regulatory and fiduciary requirements. Autonomous actions in financial systems create unacceptable legal and compliance risk.
- The PRD mandates human-in-the-loop for all actions. The pipeline state machine has explicit `review` and `remediation` states for human approval routing.
- Trust is earned incrementally. Starting with human-in-the-loop allows finance teams to validate FinSight's output before considering higher autonomy levels.
- Degraded modes (low data quality, insufficient evidence) always escalate to human review, never auto-accept.

**Trade-off:** FinSight cannot fully close the loop without a human. This is a feature, not a limitation — it makes FinSight deployable in regulated environments where black-box AI is not permitted.

---

## Why `finance/` Not `finance/ontology/`

**Decision:** The domain layer is named `finance/`, not `finance/ontology/`.

**Context:** Some financial AI architectures use the term "ontology" to describe the domain model — particularly systems that model financial concepts, relationships, and hierarchies as a knowledge graph.

**Rationale:**
- FinSight is an FP&A system, not an enterprise ontology project. The codebase should communicate its purpose clearly to new developers.
- `finance/` maps directly to the problem domain: financial calculations, models, and logic. A developer looking at the project tree knows immediately where financial code lives.
- "Ontology" carries assumptions about semantic reasoning, graph databases, and taxonomic modelling that do not match FinSight's architecture. FinSight uses typed Pydantic models and deterministic engines, not a knowledge graph.
- The layered architecture already enforces clean boundaries. Naming the directory by domain (finance) rather than by architectural pattern (ontology) keeps the focus on *what* the code does, not *how* it is structured internally.

**Trade-off:** Developers coming from semantic web or enterprise ontology backgrounds will not find a familiar structure. However, the overwhelming majority of FinSight contributors are FP&A domain engineers, not ontology specialists.

---

## Why Structured Outputs

**Decision:** All LLM interactions produce structured, typed outputs validated against Pydantic schemas.

**Context:** LLMs produce free-text narratives. Free text is useful for human reading but unreliable for programmatic consumption, validation, and downstream processing.

**Rationale:**
- Structured outputs (`AssertionType`, `SupportLevel`, `VarianceCommentaryOutput`) enable automated validation, filtering, and routing. Free text requires NLP parsing, which introduces another point of failure.
- The assertion pipeline (`finance/assertion_pipeline.py`) transforms raw data into typed `Assertion` objects. Every claim has a type, confidence score, evidence references, and policy routing. This is only possible with structured output.
- Structured outputs make the system auditable: every claim can be traced from the LLM response through validation to the rendered commentary.
- Post-generation validation rejects malformed or hallucinated content before it reaches the user.

**Trade-off:** Prompt engineering is harder with structured outputs. Getting an LLM to produce valid JSON with correct enumerations and types requires more careful prompting than free-text generation. The reliability gains justify the up-front effort.

---

## Why Context Packs

**Decision:** The LLM receives structured context packs, not raw financial data.

**Context:** Raw financial data fed into an LLM causes hallucinations, token waste, and inconsistent output quality. The context builder transforms raw data into curated input for the LLM.

**Rationale:**
- Raw data contains irrelevant detail, duplicate entries, and edge cases that confuse LLMs. The context builder filters, aggregates, and formats only what the prompt needs.
- LLMs hallucinate less when given pre-digested context. A variance summary ("Revenue is $120K vs $100K budget, +20%") produces better results than raw account-level trial balance data.
- Context packs are typed Pydantic models with explicit fields. This makes the data contract between the domain layer and the agent layer visible and testable.
- The context builder is deterministic (no LLM involved). Users can inspect exactly what data the LLM will receive.

**Trade-off:** Context builders must be maintained alongside schema changes. If the underlying data model changes, the context builder must be updated. This is explicit rather than implicit — a feature, not a bug.

---

## Why Evidence-Backed

**Decision:** Every numeric claim in output must be backed by verifiable evidence.

**Context:** Financial analysis without source references is a rumor. FP&A teams spend enormous effort tracking down the source of numbers in management reports. FinSight bakes evidence into every claim.

**Rationale:**
- The `Assertion` model has `evidence_ids`, `source`, and `support_level` fields. Every value is traceable to a source record.
- The evidence graph in `shared/models/state.py` links every variance to the specific account, period, and source table. This enables drill-down from commentary to source data.
- Trust in AI-generated financial analysis depends on the ability to verify claims. Evidence-backed assertions make this possible.
- When evidence is insufficient, the system degrades gracefully: weak assertions are flagged, not promoted as verified facts.
- The claim validators (`shared/utils/validators/claim_validator.py`) cross-check every numeric value in LLM output against the evidence context.

**Trade-off:** Evidence tracking adds complexity to the data model and requires additional storage for evidence references. The alternative — producing plausible-sounding but unverifiable claims — is unacceptable in financial contexts.
