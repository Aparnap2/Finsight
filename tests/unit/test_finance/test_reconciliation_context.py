"""Unit tests for finance/reconciliation/context.py Pydantic context models."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from finance.reconciliation.context import (
    EXCEPTION_CONTEXT_SCHEMA,
    RECONCILIATION_RUN_CONTEXT_SCHEMA,
    ExceptionContext,
    ExceptionDiagnostic,
    ReconciliationRunContext,
    RuleResult,
    RuleStatus,
    SourceSummary,
    context_json_schema,
)


def _rule_result() -> RuleResult:
    return RuleResult(rule_id="R1", status=RuleStatus.PASS)


def _source_summary() -> SourceSummary:
    return SourceSummary(source_type="INVOICE", rows=10, invalid_rows=1)


def _exception_context(**overrides: Any) -> ExceptionContext:
    base: dict[str, Any] = {
        "exception_id": "exc-1",
        "exception_code": "I-FEE-DRIFT",
        "severity": "HIGH",
        "title": "Fee drift",
        "description": "desc",
        "currency": "USD",
        "expected_net": "971.00",
        "actual_deposit": "960.00",
        "variance": "11.00",
        "tolerance": "5.00",
        "calculations": {"captured": "1000.00", "fees": "29.00"},
        "evidence_refs": ["ev-1"],
        "evidence": [{"type": "invoice", "record_id": "inv-1"}],
        "investigation_eligible": True,
    }
    base.update(overrides)
    return ExceptionContext(**base)


def _run_context(**overrides: Any) -> ReconciliationRunContext:
    base: dict[str, Any] = {
        "run_id": "run-1",
        "snapshot_id": "snap-1",
        "engine_version": "1.0.0",
        "status": "ready_for_investigation",
        "sources": {"invoices": _source_summary()},
        "validation_summary": {"passed": 1, "warnings": 0, "failed": 0, "blocked": 0},
        "exception_ids": ["exc-1"],
        "fingerprint": "a" * 64,
    }
    base.update(overrides)
    return ReconciliationRunContext(**base)


def test_models_complete() -> None:
    """All required fields construct successfully."""
    rr = _rule_result()
    assert rr.rule_id == "R1"
    ss = _source_summary()
    assert ss.rows == 10
    ec = _exception_context()
    assert ec.exception_id == "exc-1"
    rc = _run_context()
    assert rc.run_id == "run-1"
    assert rc.exceptions == []


def test_frozen() -> None:
    """Mutation raises ValidationError."""
    ec = _exception_context()
    with pytest.raises(ValidationError):
        ec.title = "changed"  # type: ignore[misc]
    rc = _run_context()
    with pytest.raises(ValidationError):
        rc.status = "x"  # type: ignore[misc]
    rr = _rule_result()
    with pytest.raises(ValidationError):
        rr.severity = "LOW"  # type: ignore[misc]


def test_extra_forbid() -> None:
    """Unknown fields are rejected."""
    with pytest.raises(ValidationError):
        RuleResult(rule_id="R1", status=RuleStatus.PASS, foo="bar")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        SourceSummary(source_type="INVOICE", rows=1, invalid_rows=0, bar=2)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        _exception_context(extra_field="x")
    with pytest.raises(ValidationError):
        _run_context(noise=1)


def test_deterministic_serialization() -> None:
    """Equal instances serialize identically."""
    a = _exception_context()
    b = _exception_context()
    assert a == b
    assert json.dumps(a.model_dump(), sort_keys=True) == json.dumps(b.model_dump(), sort_keys=True)
    ra = _run_context()
    rb = _run_context()
    assert json.dumps(ra.model_dump(), sort_keys=True) == json.dumps(
        rb.model_dump(), sort_keys=True
    )


def test_decimal_precision_roundtrip() -> None:
    """Money strings preserve precision without float coercion."""
    ec = _exception_context(expected_net="971.00")
    dumped = ec.model_dump()
    assert dumped["expected_net"] == "971.00"
    rt = ExceptionContext.model_validate_json(ec.model_dump_json())
    assert rt.expected_net == "971.00"
    assert isinstance(rt.expected_net, str)


def test_rule_status_values() -> None:
    """RuleStatus enum exposes the required values."""
    expected = {"PASS", "FAIL", "WARNING", "BLOCKED", "NOT_APPLICABLE"}
    assert {s.value for s in RuleStatus} == expected


def test_json_schema_generated() -> None:
    """Generated schemas contain properties and title."""
    schema = context_json_schema(ExceptionContext)
    assert "properties" in schema
    assert "title" in schema
    assert schema["title"] == "ExceptionContext"
    assert "properties" in RECONCILIATION_RUN_CONTEXT_SCHEMA
    assert "title" in RECONCILIATION_RUN_CONTEXT_SCHEMA
    assert EXCEPTION_CONTEXT_SCHEMA["title"] == "ExceptionContext"


def test_ineligibility_reason_optional() -> None:
    """ineligibility_reason defaults to None and can be omitted."""
    # remove key by reconstructing without it
    data = _exception_context().model_dump()
    data.pop("ineligibility_reason", None)
    # ineligibility_reason has default None, so omitting is fine
    ec2 = ExceptionContext(**{k: v for k, v in data.items() if k != "ineligibility_reason"})
    assert ec2.ineligibility_reason is None
    assert ec2.investigation_eligible is True


def _exception_diagnostic() -> ExceptionDiagnostic:
    return ExceptionDiagnostic(
        run_id="run-1",
        exception_id="exc-1",
        tenant_id="t-1",
        snapshot_id="snap-1",
        engine_version="1.0.0",
        context=_exception_context(),
        rule_results=[_rule_result()],
        query_count=5,
    )


def test_exception_diagnostic_complete() -> None:
    d = _exception_diagnostic()
    assert d.run_id == "run-1"
    assert d.snapshot_id == "snap-1"
    assert d.engine_version == "1.0.0"
    assert d.query_count == 5
    assert d.context.exception_id == "exc-1"


def test_exception_diagnostic_frozen() -> None:
    d = _exception_diagnostic()
    with pytest.raises(ValidationError):
        d.status = "x"  # type: ignore[misc]


def test_exception_diagnostic_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        ExceptionDiagnostic(
            run_id="r", exception_id="e", tenant_id="t", snapshot_id="s",
            engine_version="1", context=_exception_context(), noise=1,
        )  # type: ignore[call-arg]
