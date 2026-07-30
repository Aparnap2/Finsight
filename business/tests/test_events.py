"""Tests for the Domain Events module.

Covers event construction, field validation, catalog lookup,
and the event catalog API.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from business.events.catalog import EVENT_CATALOG, EVENTS_BY_TYPE
from business.events.models import (
    ActionProposed,
    AssertionGenerated,
    BoardReportGenerated,
    BudgetApproved,
    BudgetRevised,
    DomainEvent,
    ForecastPublished,
    InvoiceImported,
    InvoiceRejected,
    PeriodClosed,
    PeriodReopened,
    RootCauseIdentified,
    StateTransitionEvent,
    VarianceDetected,
)


class TestDomainEventBase:
    """Tests for the base DomainEvent model."""

    def test_base_event_creation(self) -> None:
        """A basic domain event can be created with required fields."""
        event = DomainEvent(
            event_id="evt-001",
            event_type="test.event",
            producer="TestSystem",
            consumer=["ConsumerA"],
        )
        assert event.event_id == "evt-001"
        assert event.event_type == "test.event"
        assert event.version == "1.0"
        assert event.producer == "TestSystem"
        assert event.consumer == ["ConsumerA"]
        assert event.sensitivity == "internal"
        assert event.correlation_id is None
        assert event.causation_id is None

    def test_base_event_default_timestamp(self) -> None:
        """Timestamp defaults to current UTC time if not provided."""
        before = datetime.now(UTC).replace(tzinfo=None)
        event = DomainEvent(
            event_id="evt-002",
            event_type="test.event",
            producer="TestSystem",
            consumer=["ConsumerA"],
        )
        after = datetime.now(UTC).replace(tzinfo=None)
        assert before <= event.timestamp <= after

    def test_base_event_sensitivity_validation(self) -> None:
        """Sensitivity must be one of the allowed literals."""
        with pytest.raises(ValidationError):
            DomainEvent(
                event_id="evt-003",
                event_type="test.event",
                producer="TestSystem",
                consumer=["ConsumerA"],
                sensitivity="top_secret",
            )

    def test_base_event_is_frozen(self) -> None:
        """DomainEvent instances are immutable."""
        event = DomainEvent(
            event_id="evt-004",
            event_type="test.event",
            producer="TestSystem",
            consumer=["ConsumerA"],
        )
        with pytest.raises(ValidationError):
            event.event_id = "changed"

    def test_base_event_extra_forbidden(self) -> None:
        """Extra fields are not allowed."""
        with pytest.raises(ValidationError):
            DomainEvent(
                event_id="evt-005",
                event_type="test.event",
                producer="TestSystem",
                consumer=["ConsumerA"],
                unknown_field="value",
            )

    def test_correlation_and_causation_ids(self) -> None:
        """Correlation and causation IDs support event chaining."""
        event = DomainEvent(
            event_id="evt-006",
            event_type="test.event",
            producer="TestSystem",
            consumer=["ConsumerA"],
            correlation_id="corr-001",
            causation_id="cause-001",
        )
        assert event.correlation_id == "corr-001"
        assert event.causation_id == "cause-001"


class TestSpecificEvents:
    """Tests for each specific domain event model."""

    def test_invoice_imported(self) -> None:
        """InvoiceImported carries vendor and amount data."""
        event = InvoiceImported(
            event_id="evt-010",
            event_type="invoice.imported",
            producer="CSVConnector",
            consumer=["APEngine"],
            vendor_id="VEN-001",
            invoice_number="INV-2024-001",
            amount=Decimal("15000.00"),
            currency="USD",
            date=datetime(2024, 6, 15),
        )
        assert event.vendor_id == "VEN-001"
        assert event.amount == Decimal("15000.00")
        assert event.currency == "USD"

    def test_invoice_imported_default_currency(self) -> None:
        """InvoiceImported defaults to USD."""
        event = InvoiceImported(
            event_id="evt-011",
            event_type="invoice.imported",
            producer="CSVConnector",
            consumer=["APEngine"],
            vendor_id="VEN-002",
            invoice_number="INV-2024-002",
            amount=Decimal("500.00"),
            date=datetime(2024, 6, 15),
        )
        assert event.currency == "USD"

    def test_invoice_rejected(self) -> None:
        """InvoiceRejected carries rejection reason and errors."""
        event = InvoiceRejected(
            event_id="evt-020",
            event_type="invoice.rejected",
            producer="CSVConnector",
            consumer=["APEngine"],
            vendor_id="VEN-003",
            invoice_number="INV-2024-003",
            rejection_reason="Duplicate invoice",
            validation_errors=["Vendor name mismatch", "Amount exceeds PO limit"],
        )
        assert event.rejection_reason == "Duplicate invoice"
        assert len(event.validation_errors) == 2

    def test_invoice_rejected_default_errors(self) -> None:
        """InvoiceRejected validation_errors defaults to empty list."""
        event = InvoiceRejected(
            event_id="evt-021",
            event_type="invoice.rejected",
            producer="CSVConnector",
            consumer=["APEngine"],
            vendor_id="VEN-004",
            invoice_number="INV-2024-004",
            rejection_reason="Missing tax ID",
        )
        assert event.validation_errors == []

    def test_budget_approved(self) -> None:
        """BudgetApproved carries period and approver info."""
        event = BudgetApproved(
            event_id="evt-030",
            event_type="budget.approved",
            producer="BudgetWorkflow",
            consumer=["VarianceEngine"],
            entity_id="ENT-001",
            period="2026-07",
            budget_version="v2.1",
            approved_by="jdoe@company.com",
        )
        assert event.entity_id == "ENT-001"
        assert event.period == "2026-07"
        assert event.approved_by == "jdoe@company.com"

    def test_budget_revised(self) -> None:
        """BudgetRevised carries version change information."""
        event = BudgetRevised(
            event_id="evt-031",
            event_type="budget.revised",
            producer="BudgetWorkflow",
            consumer=["VarianceEngine"],
            entity_id="ENT-001",
            period="2026-07",
            previous_version="v2.0",
            new_version="v2.1",
            changes=["Increased Marketing by $50K", "Reduced T&E by $10K"],
        )
        assert event.previous_version == "v2.0"
        assert event.new_version == "v2.1"

    def test_period_closed(self) -> None:
        """PeriodClosed carries close metadata."""
        event = PeriodClosed(
            event_id="evt-040",
            event_type="period.closed",
            producer="CloseEngine",
            consumer=["VarianceEngine"],
            entity_id="ENT-001",
            period="2026-06",
            closed_by="close_bot",
        )
        assert event.entity_id == "ENT-001"
        assert event.closed_by == "close_bot"

    def test_period_reopened(self) -> None:
        """PeriodReopened carries reason and approval."""
        event = PeriodReopened(
            event_id="evt-041",
            event_type="period.reopened",
            producer="CloseEngine",
            consumer=["Audit"],
            entity_id="ENT-001",
            period="2026-06",
            reason="Adjustment for FX gain",
            approved_by="cfo@company.com",
        )
        assert event.reason == "Adjustment for FX gain"
        assert event.approved_by == "cfo@company.com"

    def test_variance_detected(self) -> None:
        """VarianceDetected carries variance and materiality data."""
        event = VarianceDetected(
            event_id="evt-050",
            event_type="variance.detected",
            producer="VarianceEngine",
            consumer=["CommentaryEngine"],
            entity_id="ENT-001",
            period="2026-07",
            account_id="ACCT-4010",
            variance_amount=Decimal("75000.00"),
            variance_pct=Decimal("15.5"),
            is_material=True,
        )
        assert event.variance_amount == Decimal("75000.00")
        assert event.variance_pct == Decimal("15.5")
        assert event.is_material is True

    def test_variance_detected_not_material_by_default(self) -> None:
        """VarianceDetected defaults is_material to False."""
        event = VarianceDetected(
            event_id="evt-051",
            event_type="variance.detected",
            producer="VarianceEngine",
            consumer=["CommentaryEngine"],
            entity_id="ENT-001",
            period="2026-07",
            account_id="ACCT-4010",
            variance_amount=Decimal("1000.00"),
            variance_pct=Decimal("2.0"),
        )
        assert event.is_material is False

    def test_root_cause_identified(self) -> None:
        """RootCauseIdentified carries variance reference and confidence."""
        event = RootCauseIdentified(
            event_id="evt-060",
            event_type="root_cause.identified",
            producer="RootCauseAgent",
            consumer=["RecommendationEngine"],
            variance_id="var-001",
            root_cause_summary="Revenue shortfall due to delayed product launch",
            confidence=Decimal("0.85"),
        )
        assert event.variance_id == "var-001"
        assert event.confidence == Decimal("0.85")

    def test_forecast_published(self) -> None:
        """ForecastPublished carries forecast type and version."""
        event = ForecastPublished(
            event_id="evt-070",
            event_type="forecast.published",
            producer="ForecastEngine",
            consumer=["BoardReport"],
            entity_id="ENT-001",
            period="2026-08",
            version="v3.0",
            forecast_type="rolling",
        )
        assert event.forecast_type == "rolling"
        assert event.version == "v3.0"

    def test_assertion_generated(self) -> None:
        """AssertionGenerated carries assertion count and pipeline version."""
        event = AssertionGenerated(
            event_id="evt-080",
            event_type="assertion.generated",
            producer="AssertionPipeline",
            consumer=["CommentaryEngine"],
            entity_id="ENT-001",
            period="2026-07",
            assertion_count=42,
            pipeline_version="2.1.0",
        )
        assert event.assertion_count == 42
        assert event.pipeline_version == "2.1.0"

    def test_action_proposed(self) -> None:
        """ActionProposed carries action metadata and impact estimate."""
        event = ActionProposed(
            event_id="evt-090",
            event_type="action.proposed",
            producer="RecommendationEngine",
            consumer=["WorkflowEngine"],
            entity_id="ENT-001",
            period="2026-07",
            action="reduce",
            domain="cost",
            target="Marketing",
            impact_estimate=Decimal("50000.00"),
        )
        assert event.action == "reduce"
        assert event.domain == "cost"
        assert event.impact_estimate == Decimal("50000.00")

    def test_action_proposed_no_impact(self) -> None:
        """ActionProposed impact_estimate can be None."""
        event = ActionProposed(
            event_id="evt-091",
            event_type="action.proposed",
            producer="RecommendationEngine",
            consumer=["WorkflowEngine"],
            entity_id="ENT-001",
            period="2026-07",
            action="review",
            domain="compliance",
            target="SOXControls",
        )
        assert event.impact_estimate is None

    def test_board_report_generated(self) -> None:
        """BoardReportGenerated carries report type and metrics."""
        event = BoardReportGenerated(
            event_id="evt-100",
            event_type="board_report.generated",
            producer="CommentaryEngine",
            consumer=["Reporting"],
            entity_id="ENT-001",
            period="2026-Q2",
            report_type="quarterly",
            metrics_included=["revenue", "ebitda", "gross_margin"],
        )
        assert event.report_type == "quarterly"
        assert "revenue" in event.metrics_included

    def test_state_transition_event(self) -> None:
        """StateTransitionEvent carries transition details."""
        event = StateTransitionEvent(
            event_id="evt-110",
            event_type="state.transition",
            producer="StateMachineFramework",
            consumer=["AuditLog"],
            entity_type="pipeline_run",
            entity_id="pl-001",
            from_status="pending",
            to_status="running",
            triggered_by="system",
            reason="Pipeline started by scheduler",
        )
        assert event.entity_type == "pipeline_run"
        assert event.from_status == "pending"
        assert event.to_status == "running"
        assert event.triggered_by == "system"

    def test_state_transition_event_default_reason(self) -> None:
        """StateTransitionEvent reason defaults to empty string."""
        event = StateTransitionEvent(
            event_id="evt-111",
            event_type="state.transition",
            producer="StateMachineFramework",
            consumer=["AuditLog"],
            entity_type="agent_run",
            entity_id="ar-001",
            from_status="running",
            to_status="success",
            triggered_by="system",
        )
        assert event.reason == ""


class TestEventCatalog:
    """Tests for the EventCatalog registry."""

    def test_catalog_has_all_events(self) -> None:
        """The catalog should contain 13 registered events."""
        assert EVENT_CATALOG.count >= 13

    def test_catalog_lookup_by_type(self) -> None:
        """Events can be looked up by their type identifier."""
        entry = EVENT_CATALOG.get("invoice.imported")
        assert entry is not None
        assert entry.name == "Invoice Imported"
        assert entry.producer == "CSV/API Connector"

    def test_catalog_lookup_nonexistent(self) -> None:
        """Looking up a nonexistent event type returns None."""
        assert EVENT_CATALOG.get("nonexistent.event") is None

    def test_catalog_by_category(self) -> None:
        """Events can be filtered by category."""
        financial_events = EVENT_CATALOG.list_by_category("financial")
        assert len(financial_events) >= 5
        assert all(e.category == "financial" for e in financial_events)

    def test_catalog_by_consumer(self) -> None:
        """Events can be filtered by consumer."""
        variance_events = EVENT_CATALOG.list_by_consumer("VarianceEngine")
        assert len(variance_events) >= 2
        assert all("VarianceEngine" in e.consumers for e in variance_events)

    def test_catalog_by_type_dict(self) -> None:
        """The EVENTS_BY_TYPE dict provides fast lookup."""
        entry = EVENTS_BY_TYPE.get("period.closed")
        assert entry is not None
        assert entry.sensitivity == "internal"

    def test_invoice_events_have_confidential_sensitivity(self) -> None:
        """Invoice-related events are classified as confidential."""
        imported = EVENT_CATALOG.get("invoice.imported")
        rejected = EVENT_CATALOG.get("invoice.rejected")
        assert imported is not None and imported.sensitivity == "confidential"
        assert rejected is not None and rejected.sensitivity == "confidential"

    def test_governance_events_list(self) -> None:
        """Governance category contains state transition events."""
        governance = EVENT_CATALOG.list_by_category("governance")
        assert any(e.event_type == "state.transition" for e in governance)

    def test_events_all_have_schema_ref(self) -> None:
        """Every event entry should reference a model class."""
        for entry in EVENT_CATALOG.entries.values():
            assert entry.schema_ref != "", f"Event {entry.event_type} missing schema_ref"
