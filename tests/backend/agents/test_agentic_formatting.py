"""Agentic capability tests: Formatting dimension.

Tests that LLM response parsers correctly extract structured data from
free-text LLM output, handle edge cases (missing fields, malformed input),
and produce valid Pydantic models.
"""

import pytest
from decimal import Decimal

from backend.agents.root_cause_agent import _parse_llm_response, _build_prompt
from backend.agents.commentary_agent import _parse_sections_from_text
from backend.models.state import Variance, EvidenceItem


# ── Root-cause _parse_llm_response ────────────────────────────────────────────


class TestRootCauseParseLLMResponse:
    def test_extracts_all_fields(self):
        """_parse_llm_response must extract SUMMARY, EVIDENCE, CONFIDENCE, ACTION."""
        text = (
            "SUMMARY: Revenue shortfall due to lower deal volume\n"
            "EVIDENCE: Q2 pipeline down 20%, close rate dropped 5%\n"
            "CONFIDENCE: 0.75\n"
            "ACTION: Review sales pipeline and forecast accuracy"
        )
        result = _parse_llm_response(text)
        assert "Revenue shortfall" in result["summary"]
        assert len(result["evidence"]) > 0
        assert result["confidence_score"] == 0.75
        assert "Review sales pipeline" in result["recommended_action"]

    def test_evidence_items_have_description(self):
        """Each evidence item must have a non-empty description from the split text."""
        text = (
            "SUMMARY: Cost overrun\n"
            "EVIDENCE: AWS spend up 35%, Datadog usage increased\n"
            "CONFIDENCE: 0.6\n"
            "ACTION: Review cloud costs"
        )
        result = _parse_llm_response(text)
        assert len(result["evidence"]) == 2
        descriptions = [e.description for e in result["evidence"]]
        assert "AWS spend up 35%" in descriptions

    def test_single_evidence_item(self):
        """A single evidence item with no comma should still be captured."""
        text = (
            "SUMMARY: Simple cause\n"
            "EVIDENCE: Just one data point\n"
            "CONFIDENCE: 0.5\n"
            "ACTION: Investigate"
        )
        result = _parse_llm_response(text)
        assert len(result["evidence"]) == 1
        assert result["evidence"][0].description == "Just one data point"

    def test_missing_fields_get_defaults(self):
        """Missing fields must get sensible defaults, not crash."""
        text = "SUMMARY: Something happened"
        result = _parse_llm_response(text)
        assert result["summary"] == "Something happened"
        assert result["evidence"] is not None
        assert result["confidence_score"] == 0.5  # default
        assert result["recommended_action"] == ""  # default

    def test_missing_summary_returns_empty_string(self):
        """If SUMMARY is completely missing, summary should default to empty string."""
        text = "CONFIDENCE: 0.8\nACTION: Do something"
        result = _parse_llm_response(text)
        assert result["summary"] == ""

    def test_confidence_default_with_invalid_number(self):
        """Malformed confidence value must default to 0.5."""
        text = (
            "SUMMARY: Test\n"
            "EVIDENCE: Some data\n"
            "CONFIDENCE: not_a_number\n"
            "ACTION: Do something"
        )
        result = _parse_llm_response(text)
        assert result["confidence_score"] == 0.5

    def test_confidence_default_with_blank(self):
        """Blank confidence field must default to 0.5."""
        text = (
            "SUMMARY: Test\n"
            "EVIDENCE: Data\n"
            "CONFIDENCE: \n"
            "ACTION: Act"
        )
        result = _parse_llm_response(text)
        assert result["confidence_score"] == 0.5

    def test_confidence_out_of_range_still_accepted(self):
        """Confidence outside 0-1 is stored as-is (caller's responsibility to clamp)."""
        text = (
            "SUMMARY: Test\n"
            "EVIDENCE: Data\n"
            "CONFIDENCE: 1.5\n"
            "ACTION: Act"
        )
        result = _parse_llm_response(text)
        assert result["confidence_score"] == 1.5

    def test_evidence_with_no_data_returns_empty_list(self):
        """If EVIDENCE line is missing, evidence must be an empty list."""
        text = "SUMMARY: Test\nCONFIDENCE: 0.5\nACTION: Act"
        result = _parse_llm_response(text)
        assert result["evidence"] == []

    def test_empty_text_returns_defaults(self):
        """Completely empty text should return default values."""
        result = _parse_llm_response("")
        assert result["summary"] == ""
        assert result["evidence"] == []
        assert result["confidence_score"] == 0.5
        assert result["recommended_action"] == ""

    def test_extra_whitespace_handling(self):
        """Extra whitespace around fields should be stripped."""
        text = (
            "SUMMARY:   Spacing test   \n"
            "EVIDENCE:   Point 1  \n"
            "CONFIDENCE:   0.9  \n"
            "ACTION:   Review   "
        )
        result = _parse_llm_response(text)
        assert result["summary"] == "Spacing test"
        assert result["evidence"][0].description == "Point 1"
        assert result["confidence_score"] == 0.9
        assert result["recommended_action"] == "Review"


# ── _build_prompt ─────────────────────────────────────────────────────────────


class TestBuildPrompt:
    def test_includes_variance_data(self):
        """Prompt must include account name, actual, budget, and variance amounts."""
        v = Variance(
            account_id="4010",
            account_name="Cloud Infrastructure",
            department="Engineering",
            actual_amount=Decimal("150000"),
            budget_amount=Decimal("100000"),
            variance_amount=Decimal("50000"),
            variance_pct=Decimal("50.0"),
            is_material=True,
        )
        prompt = _build_prompt(v)
        assert "Cloud Infrastructure" in prompt
        assert "150000" in prompt.replace(",", "")
        assert "100000" in prompt.replace(",", "")
        assert "50.0" in prompt or "50.00" in prompt

    def test_includes_negative_variance(self):
        """Negative variance amounts must appear in the prompt."""
        v = Variance(
            account_id="4010",
            account_name="Revenue Shortfall",
            department="Sales",
            actual_amount=Decimal("80000"),
            budget_amount=Decimal("100000"),
            variance_amount=Decimal("-20000"),
            variance_pct=Decimal("-20.0"),
            is_material=True,
        )
        prompt = _build_prompt(v)
        assert "Revenue Shortfall" in prompt
        assert "-20.0" in prompt or "-20.00" in prompt

    def test_requested_format_in_prompt(self):
        """Prompt must instruct the LLM to use the structured format."""
        v = Variance(
            account_id="4000",
            account_name="Test",
            department="Sales",
            actual_amount=Decimal("100"),
            budget_amount=Decimal("100"),
            variance_amount=Decimal("0"),
            variance_pct=Decimal("0"),
        )
        prompt = _build_prompt(v)
        assert "SUMMARY:" in prompt
        assert "EVIDENCE:" in prompt
        assert "CONFIDENCE:" in prompt
        assert "ACTION:" in prompt


# ── Commentary _parse_llm_response ────────────────────────────────────────────


class TestCommentaryParseSections:
    def test_extracts_all_sections(self):
        """Commentary parser must extract all expected sections from markdown headings."""
        text = (
            "## Executive Summary\n"
            "Solid month with revenue up 5%.\n"
            "## Revenue\n"
            "Revenue was $500K against budget.\n"
            "## Cost\n"
            "Costs were controlled.\n"
            "## Cash\n"
            "Cash position stable.\n"
            "## Risks\n"
            "EMEA deal slippage is a risk.\n"
            "## Actions\n"
            "Monitor deal pipeline."
        )
        sections = _parse_sections_from_text(text)
        section_types = [s.section_type for s in sections]
        assert "executive_summary" in section_types
        assert "revenue" in section_types
        assert "cost" in section_types
        assert "cash" in section_types
        assert "risks" in section_types
        assert "actions" in section_types

    def test_parses_content_correctly(self):
        """Section content must be captured accurately."""
        text = "## Executive Summary\nThis is the summary text.\n## Revenue\nRevenue details."
        sections = _parse_sections_from_text(text)
        exec_section = next(s for s in sections if s.section_type == "executive_summary")
        assert "This is the summary text" in exec_section.content

    def test_missing_section_omitted(self):
        """If a section is missing, it should not appear in results."""
        text = "## Executive Summary\nOnly summary."
        sections = _parse_sections_from_text(text)
        assert len(sections) == 1
        assert sections[0].section_type == "executive_summary"

    def test_empty_section_with_label_still_captured(self):
        """A section label with empty content should still produce a section."""
        text = "## Executive Summary\n \n## Revenue\nSome revenue data."
        sections = _parse_sections_from_text(text)
        assert len(sections) >= 1

    def test_section_types_from_headings(self):
        """Section types are derived from markdown headings (case-insensitive)."""
        text = "## executive_summary\nlower case label works"
        sections = _parse_sections_from_text(text)
        assert len(sections) == 1
        assert sections[0].section_type == "executive_summary"

    def test_multiline_content_handling(self):
        """Section content spanning multiple lines must be captured."""
        text = (
            "## Executive Summary\n"
            "First line of summary.\n"
            "Second line of summary content.\n"
            "## Revenue\n"
            "Single line revenue."
        )
        sections = _parse_sections_from_text(text)
        exec_section = next(s for s in sections if s.section_type == "executive_summary")
        assert "First line" in exec_section.content
        assert "Second line" in exec_section.content
