import hashlib
import random
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from shared.models.database import (
    Entity, GLAccount, TrialBalance, BudgetLine, Actual,
    HeadcountData, VendorInvoice, SalesPipeline
)
from shared.utils.encoders import dumps


def _id() -> str:
    return str(uuid.uuid4())[:8]


def seed_database(session: Session) -> None:
    entity = Entity(id="CF001", name="CloudForge Inc.", currency="USD", fiscal_year_start="01")
    session.add(entity)

    departments = ["Sales", "Marketing", "Engineering", "G&A", "Customer Success"]
    regions = ["North America", "EMEA"]
    products = ["Product X", "Product Y", "Services"]

    gl_accounts = _create_gl_accounts(entity.id, departments, regions, products)
    for acc in gl_accounts:
        session.add(acc)
    session.flush()

    periods = [f"2025-{m:02d}" for m in range(1, 13)] + [f"2026-{m:02d}" for m in range(1, 7)]

    for period in periods:
        _seed_period(session, entity.id, gl_accounts, departments, regions, period)

    _seed_headcount(session, entity.id, periods, departments)
    _seed_vendors(session, entity.id, periods, gl_accounts)
    _seed_pipeline(session, entity.id, periods, regions, products)

    session.commit()


def _create_gl_accounts(entity_id: str, departments: list, regions: list, products: list) -> list:
    accounts = []
    templates = [
        ("4000", "Revenue - Product X", "revenue", "Sales", "North America"),
        ("4001", "Revenue - Product Y", "revenue", "Sales", "EMEA"),
        ("4002", "Revenue - Services", "revenue", "Customer Success", "North America"),
        ("5000", "COGS - Hosting", "expense", "Engineering", "North America"),
        ("5001", "COGS - Support", "expense", "Customer Success", "North America"),
        ("6000", "Sales Salaries", "expense", "Sales", "North America"),
        ("6001", "Marketing Salaries", "expense", "Marketing", "North America"),
        ("6002", "Engineering Salaries", "expense", "Engineering", "North America"),
        ("6003", "G&A Salaries", "expense", "G&A", "North America"),
        ("6004", "CS Salaries", "expense", "Customer Success", "North America"),
        ("7000", "Cloud Infrastructure", "expense", "Engineering", "North America"),
        ("7001", "Software Licenses", "expense", "Engineering", "North America"),
        ("7002", "Marketing Campaigns", "expense", "Marketing", "North America"),
        ("7003", "Travel & Entertainment", "expense", "G&A", "North America"),
        ("7004", "Professional Services", "expense", "G&A", "North America"),
        ("8000", "Office Rent", "expense", "G&A", "North America"),
        ("8001", "Insurance", "expense", "G&A", "North America"),
        ("8002", "Legal & Accounting", "expense", "G&A", "North America"),
    ]
    for acct_num, name, acct_type, dept, region in templates:
        accounts.append(GLAccount(
            id=_id(), entity_id=entity_id, account_number=acct_num,
            account_name=name, account_type=acct_type, department=dept, region=region,
        ))
    return accounts


def _seed_period(session: Session, entity_id: str, accounts: list, departments: list, regions: list, period: str):
    # First pass: compute amounts, create Actual and BudgetLine records,
    # and collect trial-balance rows so we can balance them.
    tb_rows = []          # (account, debit, credit)
    total_debits = Decimal("0")
    total_credits = Decimal("0")

    for acc in accounts:
        if acc.account_type == "revenue":
            base = random.uniform(200000, 500000)
        else:
            base = random.uniform(50000, 200000)

        if period == "2026-06" and acc.account_number == "4001":
            actual = base * 0.88
            budget = base
        elif period == "2026-06" and acc.account_number == "7000":
            actual = base * 1.35
            budget = base
        else:
            variance = random.uniform(-0.05, 0.05)
            actual = base * (1 + variance)
            budget = base

        session.add(Actual(
            id=_id(), entity_id=entity_id, period=period,
            account_id=acc.id, department=acc.department, amount=Decimal(str(round(actual, 2))),
        ))
        session.add(BudgetLine(
            id=_id(), entity_id=entity_id, period=period,
            account_id=acc.id, department=acc.department, amount=Decimal(str(round(budget, 2))),
        ))

        if acc.account_type == "revenue":
            debit = Decimal("0")
            credit = Decimal(str(round(actual, 2)))
            total_credits += credit
        else:
            debit = Decimal(str(round(actual, 2)))
            credit = Decimal("0")
            total_debits += debit

        tb_rows.append((acc, debit, credit))

    # Balance the trial balance so total debits == total credits.
    imbalance = total_debits - total_credits
    if imbalance > 0:
        # Excess debits — add the difference as a credit to a revenue account.
        for i, (acc, debit, credit) in enumerate(tb_rows):
            if acc.account_type == "revenue":
                tb_rows[i] = (acc, debit, credit + imbalance)
                break
    elif imbalance < 0:
        # Excess credits — add the difference as a debit to an expense account.
        for i, (acc, debit, credit) in enumerate(tb_rows):
            if acc.account_type != "revenue":
                tb_rows[i] = (acc, debit - imbalance, credit)  # -negative = add
                break

    for acc, debit, credit in tb_rows:
        session.add(TrialBalance(
            id=_id(), entity_id=entity_id, period=period,
            account_id=acc.id, debit=debit, credit=credit,
            balance=debit - credit,
        ))


def _seed_headcount(session: Session, entity_id: str, periods: list, departments: list):
    hc_data = {
        "Sales": (45, 12000), "Marketing": (25, 9500), "Engineering": (120, 15000),
        "G&A": (30, 8500), "Customer Success": (60, 8000),
    }
    for dept, (count, avg_comp) in hc_data.items():
        for period in periods:
            hires = random.randint(0, 3) if dept == "Engineering" else random.randint(0, 1)
            departures = random.randint(0, 1)
            session.add(HeadcountData(
                id=_id(), entity_id=entity_id, period=period, department=dept,
                headcount=count + hires - departures,
                total_compensation=Decimal(str(count * avg_comp)),
                new_hires=hires, departures=departures,
            ))


def _seed_vendors(session: Session, entity_id: str, periods: list, accounts: list):
    acct_lookup = {acc.account_number: acc.id for acc in accounts}
    vendors = [
        ("AWS", "7000", 80000), ("Stripe", "7001", 15000), ("Slack", "7001", 8000),
        ("Datadog", "7001", 12000), ("Google Cloud", "7000", 25000),
    ]
    for vendor_name, acct_num, base in vendors:
        acct_id = acct_lookup.get(acct_num)
        if not acct_id:
            continue
        for period in periods:
            amt = base * 1.35 if (period == "2026-06" and vendor_name == "AWS") else base * random.uniform(0.9, 1.1)
            session.add(VendorInvoice(
                id=_id(), entity_id=entity_id, period=period,
                vendor_name=vendor_name, account_id=acct_id,
                amount=Decimal(str(round(amt, 2))), category="SaaS",
                invoice_date=date(2026, 6, 15),
            ))


def _seed_pipeline(session: Session, entity_id: str, periods: list, regions: list, products: list):
    deals = [
        ("Enterprise Deal A", "Negotiation", 2000000, "EMEA", "Product X"),
        ("Mid-Market Deal B", "Closed Won", 500000, "North America", "Product Y"),
        ("SMB Deal C", "Proposal", 150000, "EMEA", "Product X"),
    ]
    for deal_name, stage, amount, region, product in deals:
        for period in periods:
            session.add(SalesPipeline(
                id=_id(), entity_id=entity_id, period=period,
                deal_name=deal_name, stage=stage,
                expected_close_date=date(2026, 7, 31),
                amount=Decimal(str(amount)), region=region, product=product,
            ))


# ---------------------------------------------------------------------------
# Multi-tenant identity seeding (plan v3 Phase 1: Organization -> Tenant ->
# User -> Role, reduced identity scope)
# ---------------------------------------------------------------------------

#: Fixed, deterministic demo-tenant UUIDs (v4-shaped, variant 8).
ACME_TENANT_ID = "11111111-1111-4111-8111-111111111111"
GLOBEX_TENANT_ID = "22222222-2222-4222-8222-222222222222"
INITECH_TENANT_ID = "33333333-3333-4333-8333-333333333333"

#: Deterministic org UUIDs for the three demo organizations.
_ACME_ORG_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_GLOBEX_ORG_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_INITECH_ORG_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

DEMO_ROLES = ("analyst", "manager", "director", "cfo")


def _tenant_uuid(tenant_code: str, kind: str, role: str) -> str:
    """Build a deterministic v4/variant-8 UUID from a (tenant, kind, role) seed."""
    digest = hashlib.sha256(f"{tenant_code}:{kind}:{role}".encode()).hexdigest()
    return f"{digest[0:8]}-{digest[8:12]}-4{digest[12:15]}-8{digest[16:19]}-{digest[20:32]}"


#: Demo tenant specs, keyed by tenant code. Monetary values are Decimal; the
#: jsonb approval_limits are serialized with shared.utils.encoders.dumps.
DEMO_TENANTS: dict[str, dict[str, Any]] = {
    "acme-corp": {
        "org": {"id": _ACME_ORG_ID, "code": "acme-corp", "name": "Acme Corp"},
        "tenant": {
            "id": ACME_TENANT_ID,
            "organization_id": _ACME_ORG_ID,
            "code": "acme-corp",
            "name": "Acme Corp",
            "currency_code": "USD",
            "fiscal_year_start_month": 1,
            "default_materiality_amount": Decimal("5000.00"),
            "default_materiality_pct": Decimal("5.00"),
            "approval_limits": {
                "manager": Decimal("10000"),
                "director": Decimal("50000"),
                "cfo": Decimal("250000"),
            },
        },
    },
    "globex": {
        "org": {"id": _GLOBEX_ORG_ID, "code": "globex", "name": "Globex Industries"},
        "tenant": {
            "id": GLOBEX_TENANT_ID,
            "organization_id": _GLOBEX_ORG_ID,
            "code": "globex",
            "name": "Globex Industries",
            "currency_code": "EUR",
            "fiscal_year_start_month": 7,
            "default_materiality_amount": Decimal("25000.00"),
            "default_materiality_pct": Decimal("8.00"),
            "approval_limits": {
                "manager": Decimal("25000"),
                "director": Decimal("100000"),
                "cfo": Decimal("500000"),
            },
        },
    },
    "initech": {
        "org": {"id": _INITECH_ORG_ID, "code": "initech", "name": "Initech"},
        "tenant": {
            "id": INITECH_TENANT_ID,
            "organization_id": _INITECH_ORG_ID,
            "code": "initech",
            "name": "Initech",
            "currency_code": "GBP",
            "fiscal_year_start_month": 4,
            "default_materiality_amount": Decimal("10000.00"),
            "default_materiality_pct": Decimal("6.00"),
            "approval_limits": {
                "manager": Decimal("5000"),
                "director": Decimal("25000"),
                "cfo": Decimal("100000"),
            },
        },
    },
}


def seed_all(session: Session) -> None:
    """Seed every demo tenant (acme-corp, globex, initech) idempotently."""
    for code in DEMO_TENANTS:
        seed_tenant(session, code)


def seed_tenant(session: Session, code: str) -> None:
    """Idempotently upsert one demo tenant and its org/user/role/user_role rows.

    Uses SQLAlchemy Core ``text()`` upserts (``ON CONFLICT ... DO NOTHING``) so
    re-seeding never duplicates rows or raises.

    Requires an ORM ``Session`` (not a ``Connection``): this function calls
    ``session.commit()`` internally and is not safe inside a caller-managed
    transaction context.
    """
    if code not in DEMO_TENANTS:
        raise ValueError(f"unknown demo tenant code: {code!r}")
    spec = DEMO_TENANTS[code]
    org, tenant = spec["org"], spec["tenant"]

    session.execute(
        text(
            "INSERT INTO organizations (id, name, code) "
            "VALUES (:id, :name, :code) ON CONFLICT (id) DO NOTHING"
        ),
        org,
    )
    session.execute(
        text(
            "INSERT INTO tenants ("
            "  id, organization_id, name, code, currency_code,"
            "  fiscal_year_start_month, default_materiality_amount,"
            "  default_materiality_pct, approval_limits"
            ") VALUES ("
            "  :id, :organization_id, :name, :code, :currency_code,"
            "  :fiscal_year_start_month, :default_materiality_amount,"
            "  :default_materiality_pct, CAST(:approval_limits AS jsonb)"
            ") ON CONFLICT (id) DO NOTHING"
        ),
        {**tenant, "approval_limits": dumps(tenant["approval_limits"])},
    )

    for role in DEMO_ROLES:
        session.execute(
            text(
                "INSERT INTO roles (id, tenant_id, name, description) "
                "VALUES (:id, :tenant_id, :name, :description) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {
                "id": _tenant_uuid(code, "role", role),
                "tenant_id": tenant["id"],
                "name": role,
                "description": f"{role.title()} role for {tenant['name']}",
            },
        )
        session.execute(
            text(
                "INSERT INTO users (id, tenant_id, email, display_name, active) "
                "VALUES (:id, :tenant_id, :email, :display_name, true) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {
                "id": _tenant_uuid(code, "user", role),
                "tenant_id": tenant["id"],
                "email": f"{role}@{code}.example.com",
                "display_name": f"{tenant['name']} {role.title()}",
            },
        )
        session.execute(
            text(
                "INSERT INTO user_roles (user_id, role_id) "
                "VALUES (:user_id, :role_id) "
                "ON CONFLICT (user_id, role_id) DO NOTHING"
            ),
            {
                "user_id": _tenant_uuid(code, "user", role),
                "role_id": _tenant_uuid(code, "role", role),
            },
        )
    session.commit()
