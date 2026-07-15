from unittest.mock import MagicMock
from backend.agents.root_cause_agent import investigate_root_causes, root_cause_node
from backend.models.state import Variance, RootCauseFinding, PipelineState


def _make_state(**overrides) -> PipelineState:
    base: PipelineState = {
        "period": "2026-06",
        "entity_id": "CF001",
        "actuals": {},
        "budget": {},
        "forecast": {},
        "variances": [],
        "root_causes": [],
        "commentary_draft": None,
        "scenarios": [],
        "review_decisions": [],
        "error": None,
        "current_step": "start",
    }
    base.update(overrides)
    return base


def test_investigate_returns_findings():
    variances = [
        Variance(
            account_id="4001", account_name="Revenue - Product Y", department="Sales",
            actual_amount=100000, budget_amount=120000,
            variance_amount=-20000, variance_pct=-16.67, is_material=True,
        )
    ]
    findings = investigate_root_causes(variances)
    assert len(findings) == 1
    assert findings[0].variance_id == "4001"
    assert findings[0].confidence_score > 0


def test_investigate_empty_returns_empty():
    findings = investigate_root_causes([])
    assert findings == []


def test_root_cause_node_only_material():
    variances = [
        Variance(
            account_id="4000", account_name="Test", department="Sales",
            actual_amount=100000, budget_amount=103000,
            variance_amount=-3000, variance_pct=-2.91, is_material=False,
        ),
        Variance(
            account_id="4001", account_name="Test2", department="Sales",
            actual_amount=100000, budget_amount=200000,
            variance_amount=-100000, variance_pct=-50.0, is_material=True,
        ),
    ]
    state = _make_state(variances=variances)
    result = root_cause_node(state)
    assert len(result["root_causes"]) == 1
    assert result["root_causes"][0].variance_id == "4001"
    assert result["current_step"] == "root_cause_complete"


def test_root_cause_node_no_material():
    state = _make_state(variances=[
        Variance(
            account_id="4000", account_name="Test", department="Sales",
            actual_amount=100000, budget_amount=103000,
            variance_amount=-3000, variance_pct=-2.91, is_material=False,
        )
    ])
    result = root_cause_node(state)
    assert result["root_causes"] == []


def test_investigate_uses_llm_when_provided():
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content=(
        "SUMMARY: Revenue declined due to delayed enterprise deal closings in EMEA.\n"
        "EVIDENCE: 3 deals worth $1.2M slipped from June to July.\n"
        "CONFIDENCE: 0.85\n"
        "ACTION: Accelerate deal closings with updated proposals."
    )))]
    mock_llm.chat.completions.create.return_value = mock_response

    variances = [
        Variance(
            account_id="4001", account_name="Revenue - Product Y", department="Sales",
            actual_amount=100000, budget_amount=120000,
            variance_amount=-20000, variance_pct=-16.67, is_material=True,
        )
    ]
    findings = investigate_root_causes(variances, llm_client=mock_llm)
    assert len(findings) == 1
    assert findings[0].confidence_score == 0.85
    assert "EMEA" in findings[0].summary or "deal" in findings[0].summary.lower()
    mock_llm.chat.completions.create.assert_called_once()


def test_investigate_falls_back_without_llm():
    variances = [
        Variance(
            account_id="4001", account_name="Revenue - Product Y", department="Sales",
            actual_amount=100000, budget_amount=120000,
            variance_amount=-20000, variance_pct=-16.67, is_material=True,
        )
    ]
    findings = investigate_root_causes(variances)
    assert len(findings) == 1
    assert "pending" in findings[0].summary.lower()


import os
import pytest
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


@pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"),
    reason="OPENROUTER_API_KEY not set",
)
def test_investigate_real_llm_call():
    client = OpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
    )
    variances = [
        Variance(
            account_id="7000", account_name="Cloud Infrastructure", department="Engineering",
            actual_amount=225528.89, budget_amount=167058.44,
            variance_amount=58470.45, variance_pct=35.0, is_material=True,
        )
    ]
    findings = investigate_root_causes(variances, llm_client=client)
    assert len(findings) == 1
    assert len(findings[0].summary) > 20, "LLM should produce substantive summary"
    assert findings[0].confidence_score > 0
    assert findings[0].recommended_action != ""
