"""P5.1 context/security boundary — TDD red for tenant/actor/scope hardening.

These tests define the expected P5.1 behavior before implementation:
- tenant_id is required, non-blank, bounded
- actor is required, non-blank, bounded
- capability allowlist must respect per-exception-type scope map
- context size handling remains deterministic (existing MAX_CONTEXT_CHARS)

All tests are expected to FAIL until agents/investigation/request.py is hardened.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agents.investigation.request import InvestigationRequest


def _base_kwargs(**overrides):
    """Return minimal valid kwargs for InvestigationRequest with P5.1 fields."""
    base = dict(
        exception_id="exc-boundary-001",
        exception_type="I-REFUND-LAG",
        evidence_ids=("ev-001",),
        context_window="ok",
        capability_allowlist=("get_stripe_payment",),
        round_budget=3,
        tenant_id="tenant-001",
        actor="user-001",
    )
    base.update(overrides)
    return base


def test_tenant_id_required():
    """Missing tenant_id must be rejected at boundary (no LLM call)."""
    kwargs = _base_kwargs()
    kwargs.pop("tenant_id")
    with pytest.raises(ValidationError):
        InvestigationRequest(**kwargs)


def test_tenant_id_blank_rejected():
    """Blank tenant_id must be rejected."""
    with pytest.raises(ValidationError, match="tenant"):
        InvestigationRequest(**_base_kwargs(tenant_id="   "))


def test_tenant_id_too_long():
    """Overlong tenant_id (>128) must be rejected."""
    with pytest.raises(ValidationError):
        InvestigationRequest(**_base_kwargs(tenant_id="t" * 129))


def test_actor_required():
    """Missing actor must be rejected at boundary."""
    kwargs = _base_kwargs()
    kwargs.pop("actor")
    with pytest.raises(ValidationError):
        InvestigationRequest(**kwargs)


def test_actor_blank_rejected():
    """Blank actor must be rejected."""
    with pytest.raises(ValidationError, match="actor"):
        InvestigationRequest(**_base_kwargs(actor=" "))


def test_scope_map_rejects_out_of_scope_capability_for_fee_drift():
    """I-FEE-DRIFT must not allow search_gmail (per scope map)."""
    with pytest.raises(ValidationError, match="scope|allowlist|outside"):
        InvestigationRequest(
            **_base_kwargs(
                exception_type="I-FEE-DRIFT",
                capability_allowlist=("search_gmail",),
            )
        )


def test_scope_map_rejects_out_of_scope_for_duplicate():
    """I-DUPLICATE must not allow get_stripe_payment per scope map."""
    with pytest.raises(ValidationError, match="scope|allowlist|outside"):
        InvestigationRequest(
            **_base_kwargs(
                exception_type="I-DUPLICATE",
                capability_allowlist=("get_stripe_payment",),
            )
        )


def test_scope_map_happy_paths():
    """Each exception_type allows its declared subset."""
    # I-REFUND-LAG allows get_stripe_payment + get_stripe_refunds
    InvestigationRequest(
        **_base_kwargs(
            exception_type="I-REFUND-LAG",
            capability_allowlist=("get_stripe_payment", "get_stripe_refunds"),
        )
    )
    # I-FEE-DRIFT allows get_qb_transaction
    InvestigationRequest(
        **_base_kwargs(
            exception_type="I-FEE-DRIFT",
            capability_allowlist=("get_qb_transaction",),
        )
    )
    # I-DUPLICATE allows search_gmail
    InvestigationRequest(
        **_base_kwargs(
            exception_type="I-DUPLICATE",
            capability_allowlist=("search_gmail",),
        )
    )


def test_context_window_truncation_remains():
    """Overlong context is still truncated and flagged (existing behavior)."""
    long_ctx = "x" * 5000
    req = InvestigationRequest(**_base_kwargs(context_window=long_ctx))
    assert req.context_truncated is True
    assert len(req.context_window) == 4000  # MAX_CONTEXT_CHARS


def test_cross_tenant_like_tenant_id_preserved_as_data():
    """Tenant id with injection-like content is treated as data."""
    # Should not become instruction — rejected only on blank/size
    req = InvestigationRequest(**_base_kwargs(tenant_id="tenant-attacker-001"))
    assert req.tenant_id == "tenant-attacker-001"
