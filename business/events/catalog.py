"""Event catalog — registry of every domain event type in the platform.

Populates the EventCatalog with all 15+ business events, including
producer/consumer mapping, category classification, and sensitivity
metadata as defined in the Business Knowledge Layer proposal.
"""

from business.events.models import EventCatalog, EventCatalogEntry

# ---------------------------------------------------------------------------
# Event catalog — singleton registry
# ---------------------------------------------------------------------------

EVENT_CATALOG = EventCatalog(
    entries={
        # -- Financial events --
        "invoice.imported": EventCatalogEntry(
            event_type="invoice.imported",
            name="Invoice Imported",
            description="A vendor invoice was successfully ingested from an external source.",
            producer="CSV/API Connector",
            consumers=["APEngine", "DataQuality"],
            category="financial",
            sensitivity="confidential",
            schema_ref="InvoiceImported",
        ),
        "invoice.rejected": EventCatalogEntry(
            event_type="invoice.rejected",
            name="Invoice Rejected",
            description="An invoice failed validation and was rejected.",
            producer="CSV/API Connector",
            consumers=["APEngine", "Audit"],
            category="financial",
            sensitivity="confidential",
            schema_ref="InvoiceRejected",
        ),
        "budget.approved": EventCatalogEntry(
            event_type="budget.approved",
            name="Budget Approved",
            description="A budget version was approved for a period.",
            producer="BudgetWorkflow",
            consumers=["VarianceEngine", "ScenarioEngine"],
            category="financial",
            sensitivity="confidential",
            schema_ref="BudgetApproved",
        ),
        "budget.revised": EventCatalogEntry(
            event_type="budget.revised",
            name="Budget Revised",
            description="A budget revision was created.",
            producer="BudgetWorkflow",
            consumers=["VarianceEngine"],
            category="financial",
            sensitivity="confidential",
            schema_ref="BudgetRevised",
        ),
        "forecast.published": EventCatalogEntry(
            event_type="forecast.published",
            name="Forecast Published",
            description="A new forecast version was published.",
            producer="ForecastEngine",
            consumers=["BoardReport", "VarianceEngine"],
            category="financial",
            sensitivity="confidential",
            schema_ref="ForecastPublished",
        ),
        # -- Operational events --
        "period.closed": EventCatalogEntry(
            event_type="period.closed",
            name="Period Closed",
            description="A fiscal period was closed for postings.",
            producer="CloseEngine",
            consumers=["VarianceEngine", "ForecastEngine"],
            category="operational",
            sensitivity="internal",
            schema_ref="PeriodClosed",
        ),
        "period.reopened": EventCatalogEntry(
            event_type="period.reopened",
            name="Period Reopened",
            description="A period was exceptionally reopened for adjustments.",
            producer="CloseEngine",
            consumers=["Audit", "VarianceEngine"],
            category="operational",
            sensitivity="internal",
            schema_ref="PeriodReopened",
        ),
        "variance.detected": EventCatalogEntry(
            event_type="variance.detected",
            name="Variance Detected",
            description="A material variance was identified during analysis.",
            producer="VarianceEngine",
            consumers=["CommentaryEngine", "PolicyEngine"],
            category="operational",
            sensitivity="confidential",
            schema_ref="VarianceDetected",
        ),
        "root_cause.identified": EventCatalogEntry(
            event_type="root_cause.identified",
            name="Root Cause Identified",
            description="A root cause was found for a previously detected variance.",
            producer="RootCauseAgent",
            consumers=["RecommendationEngine"],
            category="operational",
            sensitivity="confidential",
            schema_ref="RootCauseIdentified",
        ),
        "assertion.generated": EventCatalogEntry(
            event_type="assertion.generated",
            name="Assertion Generated",
            description="A new set of assertions was created by the assertion pipeline.",
            producer="AssertionPipeline",
            consumers=["CommentaryEngine", "PolicyEngine"],
            category="operational",
            sensitivity="internal",
            schema_ref="AssertionGenerated",
        ),
        "action.proposed": EventCatalogEntry(
            event_type="action.proposed",
            name="Action Proposed",
            description="An action item was proposed for review and approval.",
            producer="RecommendationEngine",
            consumers=["WorkflowEngine"],
            category="operational",
            sensitivity="confidential",
            schema_ref="ActionProposed",
        ),
        "board_report.generated": EventCatalogEntry(
            event_type="board_report.generated",
            name="Board Report Generated",
            description="A board report was compiled, rendered, or published.",
            producer="CommentaryEngine",
            consumers=["Reporting", "Export"],
            category="operational",
            sensitivity="confidential",
            schema_ref="BoardReportGenerated",
        ),
        # -- Governance events --
        "state.transition": EventCatalogEntry(
            event_type="state.transition",
            name="State Transition",
            description="A state machine transition occurred on a workflow entity.",
            producer="StateMachineFramework",
            consumers=["AuditLog", "Monitoring"],
            category="governance",
            sensitivity="internal",
            schema_ref="StateTransitionEvent",
        ),
    },
)

# Convenience lookup by event type
EVENTS_BY_TYPE: dict[str, EventCatalogEntry] = EVENT_CATALOG.entries
