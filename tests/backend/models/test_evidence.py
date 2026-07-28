from decimal import Decimal
from backend.models.state import EvidenceItem, RootCauseFinding, Variance


def test_evidence_item_creation():
    e = EvidenceItem(
        source_table="actuals",
        record_id="abc123",
        field="amount",
        value=Decimal("225528.89"),
        period="2026-06",
        description="Cloud infrastructure actual spend",
    )
    assert e.source_table == "actuals"
    assert e.value == Decimal("225528.89")
    assert e.period == "2026-06"


def test_evidence_item_in_root_cause():
    finding = RootCauseFinding(
        variance_id="7000",
        summary="Cloud infrastructure overspend",
        evidence=[
            EvidenceItem(
                source_table="actuals", record_id="a1", field="amount",
                value=Decimal("225528.89"), period="2026-06",
            ),
            EvidenceItem(
                source_table="budget_lines", record_id="b1", field="amount",
                value=Decimal("167058.44"), period="2026-06",
            ),
        ],
        confidence_score=0.85,
    )
    assert len(finding.evidence) == 2
    assert finding.evidence[0].source_table == "actuals"
    assert finding.evidence[1].source_table == "budget_lines"


def test_evidence_item_json_roundtrip():
    e = EvidenceItem(
        source_table="vendor_invoices", record_id="v1", field="amount",
        value=Decimal("80000.0"), period="2026-06", description="AWS invoice",
    )
    data = e.model_dump()
    restored = EvidenceItem(**data)
    assert restored == e
