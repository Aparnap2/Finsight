"""P10-01 RED: inventory completeness contract (failing until GREEN).

- The registry must cover every required source id.
- Every registered source must have at least one fully-described row.
- Every row must use the closed classification vocabulary with all
  descriptor fields populated (explicit N/A-with-reason, never blank).
- Unknowns surface as gap strings; the suite fails while gaps exist.

Pure unit tests, no I/O, deterministic.
"""

from __future__ import annotations

import re
from pathlib import Path

from shared.privacy.inventory import (
    INVENTORY,
    REQUIRED_SOURCE_IDS,
    SOURCE_REGISTRY,
    DataClassification,
    InventoryRow,
    completeness_gaps,
)

DOC_PATH = Path(__file__).resolve().parents[3] / "docs" / "privacy" / "DATA_CLASSIFICATION.md"


class TestSourceRegistry:
    def test_required_sources_registered(self) -> None:
        assert {e.source_id for e in SOURCE_REGISTRY} == set(REQUIRED_SOURCE_IDS)

    def test_classification_vocabulary_closed(self) -> None:
        assert {c.value for c in DataClassification} == {
            "public",
            "internal",
            "personal",
            "financial_sensitive",
            "secret",
        }


class TestCompleteness:
    def test_no_gaps(self) -> None:
        assert completeness_gaps() == []

    def test_gap_detector_reports_uncovered_source(self) -> None:
        assert any("uncovered source" in gap for gap in completeness_gaps(()))

    def test_gap_detector_rejects_blank_descriptors(self) -> None:
        row = InventoryRow(
            source_id="razorpay",
            field="customer_email",
            classification=DataClassification.PERSONAL,
            purpose="",
            system_of_record="razorpay",
            storage="postgres",
            derived_copies="none",
            llm_exposure="minimized",
            logging_exposure="masked",
            retention="short",
            deletion_rule="erase on purpose end",
            tenant_boundary="merchant",
        )
        assert any("blank purpose" in gap for gap in completeness_gaps((row,)))

    def test_gap_detector_rejects_unknown_source_rows(self) -> None:
        row = InventoryRow(
            source_id="nope",
            field="x",
            classification=DataClassification.INTERNAL,
            purpose="p",
            system_of_record="s",
            storage="s",
            derived_copies="none",
            llm_exposure="none",
            logging_exposure="none",
            retention="short",
            deletion_rule="none",
            tenant_boundary="n/a: internal constant",
        )
        assert any("unknown source" in gap for gap in completeness_gaps((row,)))


class TestDocumentSync:
    """DATA_CLASSIFICATION.md is derived from INVENTORY, not a second truth."""

    def test_every_source_has_a_section(self) -> None:
        text = DOC_PATH.read_text(encoding="utf-8")
        sections = set(re.findall(r"^## Source: (\S+)\s*$", text, flags=re.M))
        assert sections == {e.source_id for e in SOURCE_REGISTRY}

    def test_every_row_appears_in_document(self) -> None:
        text = DOC_PATH.read_text(encoding="utf-8")
        missing = [f"{r.source_id}/{r.field}" for r in INVENTORY if f"`{r.field}`" not in text]
        assert missing == []
