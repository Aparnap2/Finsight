"""Malicious example sets for the Example Library.

Adversarial inputs used to prove the platform rejects cross-tenant
reference leaks, tampered rows, and injection-shaped payloads. These
are the ``malicious`` category of the example classification
(``docs/14-platform/implementation-plan.md`` Phase 0).

Each set is deliberately small and explicit so security and validation
tests can assert exact rejection behaviour without ambiguity.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from business.examples.models import ExampleSet


def _build_cross_tenant_invoices() -> ExampleSet:
    """Invoices that reference a foreign tenant's entity or vendor.

    The ``tenant_id`` column points at a different tenant while the row
    lives in this tenant's stream — tests tenant-isolation enforcement.
    """
    data: list[dict[str, Any]] = [
        {
            "tenant_id": "tenant-acme",
            "entity_id": "ent-other-tenant-001",
            "vendor_name": "Foreign Entity Corp",
            "account_id": "acc-4010",
            "amount": Decimal("999999.00"),
            "currency": "USD",
            "invoice_date": "2026-04-01",
            "department": "Operations",
        },
        {
            "tenant_id": "tenant-acme",
            "entity_id": "ent-other-tenant-002",
            "vendor_name": "Sibling Tenant Supply",
            "account_id": "acc-4010",
            "amount": Decimal("50000.00"),
            "currency": "USD",
            "invoice_date": "2026-04-02",
            "department": "Finance",
        },
    ]
    return ExampleSet(
        example_id="invoice_cross_tenant",
        name="Cross-Tenant Invoices",
        description="Two invoices whose entity ids belong to another tenant "
        "— tests tenant-isolation and RLS enforcement at the data boundary.",
        domain="invoices",
        data=data,
        tags=["malicious", "cross-tenant", "isolation"],
        source="programmatic",
    )


def _build_tampered_invoices() -> ExampleSet:
    """Invoices with tampered fields: modified totals and forged ids.

    The first row carries a hash/signature field that does not match the
    amount, simulating a tampered record; the second embeds an
    injection-shaped vendor string.
    """
    data: list[dict[str, Any]] = [
        {
            "tenant_id": "tenant-acme",
            "entity_id": "ent-001",
            "vendor_name": "Acme Paper Co",
            "account_id": "acc-4010",
            "amount": Decimal("15000.00"),
            "expected_amount": Decimal("1500.00"),
            "row_hash": "deadbeef",
            "currency": "USD",
            "invoice_date": "2026-04-03",
            "department": "Operations",
        },
        {
            "tenant_id": "tenant-acme",
            "entity_id": "ent-001",
            "vendor_name": "x'); DROP TABLE invoices; --",
            "account_id": "acc-4010",
            "amount": Decimal("1.00"),
            "currency": "USD",
            "invoice_date": "2026-04-04",
            "department": "Finance",
        },
    ]
    return ExampleSet(
        example_id="invoice_tampered",
        name="Tampered Invoices",
        description="An invoice whose amount disagrees with its row hash and "
        "an invoice with an injection-shaped vendor string — tests tamper "
        "detection and SQL/CSV injection hardening.",
        domain="invoices",
        data=data,
        tags=["malicious", "tampered", "injection"],
        source="programmatic",
    )


def _build_cross_tenant_variance() -> ExampleSet:
    """Variance rows whose department or entity references another tenant.

    Tests that variance aggregation honours tenant boundaries even when
    dimension values look plausible.
    """
    data: list[dict[str, Any]] = [
        {
            "tenant_id": "tenant-acme",
            "entity_id": "ent-001",
            "period": "2026-01",
            "account_id": "acc-7010",
            "department": "dept.other-tenant",
            "budget_amount": Decimal("10000.00"),
            "actual_amount": Decimal("50000.00"),
            "variance_amount": Decimal("40000.00"),
        },
        {
            "tenant_id": "tenant-acme",
            "entity_id": "ent-other-tenant",
            "period": "2026-01",
            "account_id": "acc-7011",
            "department": "Sales",
            "budget_amount": Decimal("20000.00"),
            "actual_amount": Decimal("0.00"),
            "variance_amount": Decimal("-20000.00"),
        },
    ]
    return ExampleSet(
        example_id="cross_tenant_variance",
        name="Cross-Tenant Variance",
        description="Variance rows with foreign tenant dimensions — tests "
        "tenant-isolation in variance aggregation and drill-down.",
        domain="variance",
        data=data,
        tags=["malicious", "cross-tenant", "isolation"],
        source="programmatic",
    )


MALICIOUS_SETS: list[ExampleSet] = [
    _build_cross_tenant_invoices(),
    _build_tampered_invoices(),
    _build_cross_tenant_variance(),
]


def get_malicious_examples() -> list[ExampleSet]:
    """Return all programmatic malicious example sets.

    Returns:
        The full list of malicious ExampleSets.
    """
    return list(MALICIOUS_SETS)


__all__ = ["MALICIOUS_SETS", "get_malicious_examples"]
