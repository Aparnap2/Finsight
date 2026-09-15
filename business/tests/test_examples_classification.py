"""Tests for the example classification catalog.

Covers the good/bad/edge/malicious classification of curated example
sets per aggregate.
"""

from __future__ import annotations

from business.examples import (
    EDGE_CASE_SETS,
    EXAMPLE_CATALOG,
    FINANCE_EXAMPLE_SETS,
    MALICIOUS_SETS,
    ExampleClassification,
)


class TestExampleCatalog:
    """Tests for the classification catalog."""

    def test_catalog_builds_from_all_sources(self) -> None:
        """The catalog includes finance, edge-case, and malicious sets."""
        total = len(FINANCE_EXAMPLE_SETS) + len(EDGE_CASE_SETS) + len(MALICIOUS_SETS)
        assert len(EXAMPLE_CATALOG) == total

    def test_good_classification(self) -> None:
        """Good examples are the happy-path sets."""
        good = {e.example_id for e in EXAMPLE_CATALOG.by_classification(ExampleClassification.GOOD)}
        assert "invoice_good" in good
        assert "trial_balance_balanced" in good

    def test_bad_classification(self) -> None:
        """Bad examples are validation-failing sets."""
        bad = {e.example_id for e in EXAMPLE_CATALOG.by_classification(ExampleClassification.BAD)}
        assert "invoice_duplicate" in bad
        assert "trial_balance_unbalanced" in bad

    def test_edge_classification(self) -> None:
        """Edge examples cover boundary conditions."""
        edge = {
            e.example_id for e in EXAMPLE_CATALOG.by_classification(ExampleClassification.EDGE)
        }
        assert "zero_budget_variance" in edge
        assert "invoice_negative_amount" in edge

    def test_malicious_classification(self) -> None:
        """Malicious examples cover adversarial input."""
        malicious = {
            e.example_id
            for e in EXAMPLE_CATALOG.by_classification(ExampleClassification.MALICIOUS)
        }
        assert "invoice_cross_tenant" in malicious
        assert "invoice_tampered" in malicious
        assert "cross_tenant_variance" in malicious

    def test_by_aggregate(self) -> None:
        """Aggregate lookup returns all classified sets in that domain."""
        invoices = {e.example_id for e in EXAMPLE_CATALOG.by_aggregate("invoices")}
        assert "invoice_good" in invoices
        assert "invoice_tampered" in invoices

    def test_classify_defaults_to_good(self) -> None:
        """Unclassified sets default to good."""
        assert (
            EXAMPLE_CATALOG.classify("never_registered") == ExampleClassification.GOOD
        )

    def test_every_classification_has_examples(self) -> None:
        """All four categories are populated."""
        for classification in ExampleClassification:
            sets = EXAMPLE_CATALOG.by_classification(classification)
            assert sets, f"no examples classified as {classification.value}"


class TestMaliciousSets:
    """Tests for the malicious example data."""

    def test_cross_tenant_rows_reference_foreign_entities(self) -> None:
        """Cross-tenant invoices carry foreign entity ids."""
        cross_tenant = next(e for e in MALICIOUS_SETS if e.example_id == "invoice_cross_tenant")
        assert all("other-tenant" in row["entity_id"] for row in cross_tenant.data)

    def test_tampered_rows_carry_hash_and_injection(self) -> None:
        """Tampered invoices expose a hash mismatch and injection string."""
        tampered = next(e for e in MALICIOUS_SETS if e.example_id == "invoice_tampered")
        hashes = [row.get("row_hash") for row in tampered.data]
        assert any(hashes)
        vendor_names = [row["vendor_name"] for row in tampered.data]
        assert any("DROP TABLE" in name for name in vendor_names)

    def test_malicious_sets_are_tagged(self) -> None:
        """Malicious sets carry the malicious tag."""
        for ex in MALICIOUS_SETS:
            assert "malicious" in ex.tags
