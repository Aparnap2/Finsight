"""D7: Structured output boundary tests for validate_structured_output.

Covers the strict validation gate at shared/llm/provider.py:39. Every raw
provider payload passes through validate_structured_output before reaching
domain code. This test file proves the boundary rejects unknown fields,
wrong types, malformed JSON, non-dict payloads, and non-BaseModel schemas.
Fully deterministic: no network, no LLM, no money arithmetic.
"""

from __future__ import annotations

import socket
import urllib.request
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from agents.investigation.plan import InvestigationPlan
from shared.llm.errors import SchemaMismatchError
from shared.llm.provider import validate_structured_output


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block real sockets so every test stays deterministic."""

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("live network forbidden in structured output tests")

    monkeypatch.setattr(socket, "socket", _explode)
    monkeypatch.setattr(urllib.request, "urlopen", _explode)


class _SimpleModel(BaseModel):
    """Minimal schema for boundary tests."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    name: str
    value: int = 0


class TestValidInputs:
    """Clean payloads pass through validate_structured_output."""

    def test_valid_dict_passes(self) -> None:
        """Arrange a correct dict; Act validate; Assert model returned."""
        result = validate_structured_output({"name": "test", "value": 42}, _SimpleModel)
        assert isinstance(result, _SimpleModel)
        assert result.name == "test"
        assert result.value == 42

    def test_valid_json_string_passes(self) -> None:
        """Arrange a JSON string; Act validate; Assert model returned."""
        result = validate_structured_output('{"name": "test", "value": 7}', _SimpleModel)
        assert isinstance(result, _SimpleModel)
        assert result.name == "test"
        assert result.value == 7

    def test_basemodel_instance_passes(self) -> None:
        """Arrange an existing BaseModel; Act validate; Assert round-trip."""
        original = _SimpleModel(name="existing", value=99)
        result = validate_structured_output(original, _SimpleModel)
        assert isinstance(result, _SimpleModel)
        assert result == original


class TestRejectUnknownFields:
    """Extra fields are always rejected regardless of schema extra= setting."""

    def test_unknown_field_in_dict_rejected(self) -> None:
        """Arrange dict with rogue_field; Act; Assert SchemaMismatchError."""
        with pytest.raises(SchemaMismatchError, match="unknown fields"):
            validate_structured_output({"name": "x", "rogue_field": True}, _SimpleModel)

    def test_unknown_field_in_json_string_rejected(self) -> None:
        """Arrange JSON with extra key; Act; Assert SchemaMismatchError."""
        with pytest.raises(SchemaMismatchError, match="unknown fields"):
            validate_structured_output('{"name": "x", "extra": 1}', _SimpleModel)


class TestRejectWrongTypes:
    """Type mismatches surface as SchemaMismatchError, never silently coerce."""

    def test_wrong_field_type_rejected(self) -> None:
        """Arrange int where string expected; Act; Assert SchemaMismatchError."""
        with pytest.raises(SchemaMismatchError):
            validate_structured_output({"name": 123, "value": 1}, _SimpleModel)

    def test_missing_required_field_rejected(self) -> None:
        """Arrange missing 'name'; Act; Assert SchemaMismatchError."""
        with pytest.raises(SchemaMismatchError):
            validate_structured_output({"value": 42}, _SimpleModel)

    def test_bool_for_int_rejected(self) -> None:
        """Arrange bool where int expected; Act; Assert SchemaMismatchError."""
        with pytest.raises(SchemaMismatchError):
            validate_structured_output({"name": "x", "value": True}, _SimpleModel)


class TestRejectMalformedInput:
    """Non-JSON strings and non-dict payloads fail at the boundary."""

    def test_empty_string_rejected(self) -> None:
        """Arrange empty string; Act; Assert SchemaMismatchError."""
        with pytest.raises(SchemaMismatchError, match="not valid JSON"):
            validate_structured_output("", _SimpleModel)

    def test_malformed_json_string_rejected(self) -> None:
        """Arrange broken JSON; Act; Assert SchemaMismatchError."""
        with pytest.raises(SchemaMismatchError, match="not valid JSON"):
            validate_structured_output("{not json at all", _SimpleModel)

    def test_json_array_rejected(self) -> None:
        """Arrange a JSON list [1,2,3]; Act; Assert must-be-object."""
        with pytest.raises(SchemaMismatchError, match="must be a JSON object"):
            validate_structured_output([1, 2, 3], _SimpleModel)

    def test_non_dict_non_string_rejected(self) -> None:
        """Arrange an int; Act; Assert SchemaMismatchError."""
        with pytest.raises(SchemaMismatchError):
            validate_structured_output(42, _SimpleModel)

    def test_none_rejected(self) -> None:
        """Arrange None; Act; Assert SchemaMismatchError."""
        with pytest.raises(SchemaMismatchError):
            validate_structured_output(None, _SimpleModel)


class TestRejectBadSchema:
    """Non-BaseModel schemas are rejected before any payload inspection."""

    def test_non_basemodel_schema_rejected(self) -> None:
        """Arrange a plain dict as schema; Act; Assert SchemaMismatchError."""
        with pytest.raises(SchemaMismatchError, match="must be a BaseModel subclass"):
            validate_structured_output({"name": "x"}, dict)  # type: ignore[arg-type]

    def test_string_schema_rejected(self) -> None:
        """Arrange a string as schema; Act; Assert SchemaMismatchError."""
        with pytest.raises(SchemaMismatchError, match="must be a BaseModel subclass"):
            validate_structured_output({"name": "x"}, "not_a_schema")  # type: ignore[arg-type]


class TestInvestigationPlanBoundary:
    """Prove InvestigationPlan strict validation through the boundary."""

    def test_investigation_plan_unknown_field_rejected(self) -> None:
        """Arrange valid plan dict with extra key; Act; Assert boundary rejects."""
        payload = {
            "hypothesis_text": "Possible refund lag between systems.",
            "capability_calls": [
                {
                    "capability": "get_stripe_payment",
                    "args": {"payment_id": "p1"},
                    "order_index": 0,
                },
            ],
            "evidence_required": ["ev-001"],
            "escalation": False,
            "rogue_field": True,
        }
        with pytest.raises(SchemaMismatchError, match="unknown fields"):
            validate_structured_output(payload, InvestigationPlan)

    def test_investigation_plan_wrong_type_rejected(self) -> None:
        """Arrange hypothesis as int; Act; Assert boundary rejects."""
        payload = {
            "hypothesis_text": 123,
            "capability_calls": [
                {"capability": "get_stripe_payment", "args": {}, "order_index": 0},
            ],
            "evidence_required": ["ev-001"],
            "escalation": False,
        }
        with pytest.raises(SchemaMismatchError):
            validate_structured_output(payload, InvestigationPlan)

    def test_investigation_plan_valid_passes(self) -> None:
        """Arrange a correct InvestigationPlan dict; Act; Assert validated."""
        payload = {
            "hypothesis_text": "Possible refund posting lag.",
            "capability_calls": [
                {
                    "capability": "get_stripe_payment",
                    "args": {"payment_id": "p1"},
                    "order_index": 0,
                },
            ],
            "evidence_required": ["ev-001"],
            "escalation": False,
        }
        result = validate_structured_output(payload, InvestigationPlan)
        assert isinstance(result, InvestigationPlan)
        assert result.hypothesis_text == "Possible refund posting lag."
