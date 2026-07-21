"""T2.4 — Tenant isolation tests (TDD: tests written BEFORE implementation).

Covers:
- entity_id → tenant_id rename in PipelineState
- All tools scope queries by tenant_id
- Cross-tenant query isolation (tenant A never sees tenant B)
- API endpoints enforce tenant scoping
- Seed data is correctly scoped
- tenant_id is required in PipelineState
- RLS-style query scoping
"""

import pytest
from decimal import Decimal
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from backend.models.database import (
    Base, Entity, GLAccount, TrialBalance, BudgetLine, Actual,
    HeadcountData, VendorInvoice, SalesPipeline,
)
from backend.data.seed import seed_database
from backend.tools.gl_tools import query_gl_detail, query_trial_balance
from backend.tools.headcount_tools import query_headcount
from backend.tools.vendor_tools import query_vendor_spend
from backend.tools.pipeline_tools import query_sales_pipeline


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def multi_tenant_db():
    """Create an in-memory SQLite DB seeded with TWO tenants' data."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        # Seed first tenant (CF001)
        seed_database(session)

        # Seed second tenant (CF002) with distinct data
        _seed_second_tenant(session)

    return engine


def _seed_second_tenant(session: Session) -> None:
    """Seed a second tenant 'CF002' with clearly different data."""
    entity = Entity(id="CF002", name="Acme Corp", currency="EUR", fiscal_year_start="04")
    session.add(entity)
    session.flush()

    departments = ["Engineering", "Sales"]
    regions = ["EMEA", "APAC"]
    products = ["Product Z"]

    # GL Accounts for tenant 2
    gl_accounts = []
    templates = [
        ("4000", "Revenue - Product Z", "revenue", "Sales", "EMEA"),
        ("6000", "Engineering Salaries", "expense", "Engineering", "EMEA"),
        ("7000", "Cloud Infrastructure", "expense", "Engineering", "EMEA"),
    ]
    for acct_num, name, acct_type, dept, region in templates:
        acct = GLAccount(
            id=f"CF002_{acct_num}", entity_id=entity.id,
            account_number=acct_num, account_name=name,
            account_type=acct_type, department=dept, region=region,
        )
        gl_accounts.append(acct)
        session.add(acct)
    session.flush()

    period = "2026-06"
    for acc in gl_accounts:
        if acc.account_type == "revenue":
            actual_amt = Decimal("300000")
            budget_amt = Decimal("280000")
        else:
            actual_amt = Decimal("100000")
            budget_amt = Decimal("95000")

        session.add(Actual(
            id=f"CF002_ACT_{acc.account_number}", entity_id=entity.id,
            period=period, account_id=acc.id,
            department=acc.department, amount=actual_amt,
        ))
        session.add(BudgetLine(
            id=f"CF002_BUD_{acc.account_number}", entity_id=entity.id,
            period=period, account_id=acc.id,
            department=acc.department, amount=budget_amt,
        ))
        debit = actual_amt if acc.account_type != "revenue" else Decimal("0")
        credit = actual_amt if acc.account_type == "revenue" else Decimal("0")
        session.add(TrialBalance(
            id=f"CF002_TB_{acc.account_number}", entity_id=entity.id,
            period=period, account_id=acc.id,
            debit=debit, credit=credit, balance=debit - credit,
        ))

    # Headcount for tenant 2
    session.add(HeadcountData(
        id="CF002_HC_1", entity_id=entity.id, period=period,
        department="Engineering", headcount=80,
        total_compensation=Decimal("1200000"), new_hires=5, departures=2,
    ))

    # Vendor invoices for tenant 2
    session.add(VendorInvoice(
        id="CF002_VI_1", entity_id=entity.id, period=period,
        vendor_name="Azure", account_id="CF002_7000",
        amount=Decimal("50000"), category="Cloud",
    ))

    # Sales pipeline for tenant 2
    session.add(SalesPipeline(
        id="CF002_SP_1", entity_id=entity.id, period=period,
        deal_name="Acme Enterprise Deal", stage="Negotiation",
        amount=Decimal("1500000"), region="EMEA", product="Product Z",
    ))

    session.commit()


# ── Test Classes ──────────────────────────────────────────────────────────────


class TestTenantIsolation:
    """Verify that cross-tenant data leakage is impossible."""

    def test_tenant_a_data_not_visible_to_tenant_b_gl(self, multi_tenant_db):
        """GL detail query for CF001 must NOT return CF002 rows."""
        result = query_gl_detail(
            tenant_id="CF001", period="2026-06", engine=multi_tenant_db,
        )
        entity_ids = {r["entity_id"] for r in result.data}
        assert entity_ids == {"CF001"}, f"Leaked tenant IDs: {entity_ids - {'CF001'}}"

    def test_tenant_b_data_not_visible_to_tenant_a_gl(self, multi_tenant_db):
        """GL detail query for CF002 must NOT return CF001 rows."""
        result = query_gl_detail(
            tenant_id="CF002", period="2026-06", engine=multi_tenant_db,
        )
        entity_ids = {r["entity_id"] for r in result.data}
        assert entity_ids == {"CF002"}, f"Leaked tenant IDs: {entity_ids - {'CF002'}}"

    def test_tenant_a_data_not_visible_to_tenant_b_trial_balance(self, multi_tenant_db):
        """Trial balance query for CF001 must NOT return CF002 rows."""
        result = query_trial_balance(
            tenant_id="CF001", period="2026-06", engine=multi_tenant_db,
        )
        entity_ids = {r["entity_id"] for r in result.data}
        assert entity_ids == {"CF001"}, f"Leaked tenant IDs: {entity_ids - {'CF001'}}"

    def test_tenant_a_data_not_visible_to_tenant_b_headcount(self, multi_tenant_db):
        """Headcount query for CF001 must NOT return CF002 rows."""
        result = query_headcount(
            tenant_id="CF001", period="2026-06", engine=multi_tenant_db,
        )
        entity_ids = {r["entity_id"] for r in result.data}
        assert entity_ids == {"CF001"}, f"Leaked tenant IDs: {entity_ids - {'CF001'}}"

    def test_tenant_a_data_not_visible_to_tenant_b_vendor(self, multi_tenant_db):
        """Vendor spend query for CF001 must NOT return CF002 rows."""
        result = query_vendor_spend(
            tenant_id="CF001", period="2026-06", engine=multi_tenant_db,
        )
        entity_ids = {r["entity_id"] for r in result.data}
        assert entity_ids == {"CF001"}, f"Leaked tenant IDs: {entity_ids - {'CF001'}}"

    def test_tenant_a_data_not_visible_to_tenant_b_pipeline(self, multi_tenant_db):
        """Pipeline query for CF001 must NOT return CF002 rows."""
        result = query_sales_pipeline(
            tenant_id="CF001", period="2026-06", engine=multi_tenant_db,
        )
        entity_ids = {r["entity_id"] for r in result.data}
        assert entity_ids == {"CF001"}, f"Leaked tenant IDs: {entity_ids - {'CF001'}}"

    def test_tenant_b_data_not_visible_to_tenant_a_headcount(self, multi_tenant_db):
        """Headcount query for CF002 must NOT return CF001 rows."""
        result = query_headcount(
            tenant_id="CF002", period="2026-06", engine=multi_tenant_db,
        )
        entity_ids = {r["entity_id"] for r in result.data}
        assert entity_ids == {"CF002"}, f"Leaked tenant IDs: {entity_ids - {'CF002'}}"

    def test_tenant_b_data_not_visible_to_tenant_a_vendor(self, multi_tenant_db):
        """Vendor spend query for CF002 must NOT return CF001 rows."""
        result = query_vendor_spend(
            tenant_id="CF002", period="2026-06", engine=multi_tenant_db,
        )
        entity_ids = {r["entity_id"] for r in result.data}
        assert entity_ids == {"CF002"}, f"Leaked tenant IDs: {entity_ids - {'CF002'}}"

    def test_tenant_b_data_not_visible_to_tenant_a_pipeline(self, multi_tenant_db):
        """Pipeline query for CF002 must NOT return CF001 rows."""
        result = query_sales_pipeline(
            tenant_id="CF002", period="2026-06", engine=multi_tenant_db,
        )
        entity_ids = {r["entity_id"] for r in result.data}
        assert entity_ids == {"CF002"}, f"Leaked tenant IDs: {entity_ids - {'CF002'}}"


class TestToolTenantScoping:
    """Verify each tool correctly scopes by tenant_id."""

    def test_gl_tool_scopes_by_tenant(self, multi_tenant_db):
        result_a = query_gl_detail(tenant_id="CF001", period="2026-06", engine=multi_tenant_db)
        result_b = query_gl_detail(tenant_id="CF002", period="2026-06", engine=multi_tenant_db)
        assert result_a.tenant_id == "CF001"
        assert result_b.tenant_id == "CF002"
        # Different tenants should get different data sets
        assert result_a.row_count != result_b.row_count or result_a.data != result_b.data

    def test_trial_balance_tool_scopes_by_tenant(self, multi_tenant_db):
        result_a = query_trial_balance(tenant_id="CF001", period="2026-06", engine=multi_tenant_db)
        result_b = query_trial_balance(tenant_id="CF002", period="2026-06", engine=multi_tenant_db)
        assert result_a.tenant_id == "CF001"
        assert result_b.tenant_id == "CF002"

    def test_headcount_tool_scopes_by_tenant(self, multi_tenant_db):
        result_a = query_headcount(tenant_id="CF001", period="2026-06", engine=multi_tenant_db)
        result_b = query_headcount(tenant_id="CF002", period="2026-06", engine=multi_tenant_db)
        assert result_a.tenant_id == "CF001"
        assert result_b.tenant_id == "CF002"
        # CF001 has 5 departments, CF002 has 1
        assert result_a.row_count > result_b.row_count

    def test_vendor_tool_scopes_by_tenant(self, multi_tenant_db):
        result_a = query_vendor_spend(tenant_id="CF001", period="2026-06", engine=multi_tenant_db)
        result_b = query_vendor_spend(tenant_id="CF002", period="2026-06", engine=multi_tenant_db)
        assert result_a.tenant_id == "CF001"
        assert result_b.tenant_id == "CF002"
        # CF001 has 5 vendors, CF002 has 1
        assert result_a.row_count > result_b.row_count

    def test_pipeline_tool_scopes_by_tenant(self, multi_tenant_db):
        result_a = query_sales_pipeline(tenant_id="CF001", period="2026-06", engine=multi_tenant_db)
        result_b = query_sales_pipeline(tenant_id="CF002", period="2026-06", engine=multi_tenant_db)
        assert result_a.tenant_id == "CF001"
        assert result_b.tenant_id == "CF002"
        # CF001 has 3 deals, CF002 has 1
        assert result_a.row_count > result_b.row_count

    def test_all_tool_results_include_tenant_id(self, multi_tenant_db):
        """Every ToolResult must carry the tenant_id that was queried."""
        tools_and_kwargs = [
            (query_gl_detail, {"tenant_id": "CF001", "period": "2026-06", "engine": multi_tenant_db}),
            (query_trial_balance, {"tenant_id": "CF001", "period": "2026-06", "engine": multi_tenant_db}),
            (query_headcount, {"tenant_id": "CF001", "period": "2026-06", "engine": multi_tenant_db}),
            (query_vendor_spend, {"tenant_id": "CF001", "period": "2026-06", "engine": multi_tenant_db}),
            (query_sales_pipeline, {"tenant_id": "CF001", "period": "2026-06", "engine": multi_tenant_db}),
        ]
        for fn, kwargs in tools_and_kwargs:
            result = fn(**kwargs)
            assert result.tenant_id == "CF001", f"{fn.__name__} did not set tenant_id correctly"

    def test_all_tool_results_have_required_filters(self, multi_tenant_db):
        """All tool results must indicate required filters (tenant, period) were applied."""
        tools_and_kwargs = [
            (query_gl_detail, {"tenant_id": "CF001", "period": "2026-06", "engine": multi_tenant_db}),
            (query_trial_balance, {"tenant_id": "CF001", "period": "2026-06", "engine": multi_tenant_db}),
            (query_headcount, {"tenant_id": "CF001", "period": "2026-06", "engine": multi_tenant_db}),
            (query_vendor_spend, {"tenant_id": "CF001", "period": "2026-06", "engine": multi_tenant_db}),
            (query_sales_pipeline, {"tenant_id": "CF001", "period": "2026-06", "engine": multi_tenant_db}),
        ]
        for fn, kwargs in tools_and_kwargs:
            result = fn(**kwargs)
            assert result.required_filters_present is True, f"{fn.__name__} missing required filters"


class TestPipelineState:
    """Verify PipelineState uses tenant_id consistently."""

    def test_pipeline_state_requires_tenant_id(self):
        """PipelineState MUST have a tenant_id field (not entity_id)."""
        from backend.models.state import PipelineState
        import typing

        hints = typing.get_type_hints(PipelineState)
        assert "tenant_id" in hints, (
            "PipelineState must have 'tenant_id' field. "
            f"Available fields: {list(hints.keys())}"
        )

    def test_pipeline_state_entity_id_removed(self):
        """PipelineState MUST NOT have entity_id field (replaced by tenant_id)."""
        from backend.models.state import PipelineState
        import typing

        hints = typing.get_type_hints(PipelineState)
        assert "entity_id" not in hints, (
            "PipelineState must NOT have 'entity_id' — use 'tenant_id' instead"
        )

    def test_tenant_id_is_str_type(self):
        """tenant_id must be typed as str."""
        from backend.models.state import PipelineState
        import typing

        hints = typing.get_type_hints(PipelineState)
        assert hints["tenant_id"] is str

    def test_tenant_id_propagates_through_state(self):
        """Creating a state with tenant_id should work and be readable."""
        from backend.models.state import PipelineState

        state: PipelineState = {
            "period": "2026-06",
            "tenant_id": "CF001",
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
        assert state["tenant_id"] == "CF001"

    def test_tenant_id_is_required_field(self):
        """tenant_id must be declared (not Optional) in PipelineState type hints."""
        from backend.models.state import PipelineState
        import typing

        hints = typing.get_type_hints(PipelineState)
        tenant_hint = hints["tenant_id"]
        assert tenant_hint is str, (
            f"tenant_id must be str (required), got {tenant_hint}"
        )


class TestIngestionAgentTenantScoping:
    """Verify ingestion agent uses tenant_id from state."""

    def test_ingestion_node_uses_tenant_id(self, multi_tenant_db):
        """ingestion_node should read tenant_id (not entity_id) from state."""
        from backend.agents.ingestion_agent import ingestion_node
        from backend.models.state import PipelineState

        state: PipelineState = {
            "period": "2026-06",
            "tenant_id": "CF001",
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
        result = ingestion_node(state, engine=multi_tenant_db)
        assert result["actuals"]["entity_id"] == "CF001"
        assert result["budget"]["entity_id"] == "CF001"

    def test_ingestion_node_isolates_tenants(self, multi_tenant_db):
        """Ingestion for CF001 must not include CF002 data."""
        from backend.agents.ingestion_agent import ingestion_node
        from backend.models.state import PipelineState

        state_a: PipelineState = {
            "period": "2026-06",
            "tenant_id": "CF001",
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
        state_b: PipelineState = {
            "period": "2026-06",
            "tenant_id": "CF002",
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

        result_a = ingestion_node(state_a, engine=multi_tenant_db)
        result_b = ingestion_node(state_b, engine=multi_tenant_db)

        accounts_a = result_a["actuals"]["accounts"]
        accounts_b = result_b["actuals"]["accounts"]

        # CF001 has more GL accounts than CF002
        assert len(accounts_a) > len(accounts_b)


class TestAPITenantEnforcement:
    """Verify API request schemas enforce tenant_id."""

    def test_pipeline_run_request_has_tenant_id(self):
        """PipelineRunRequest must have tenant_id field."""
        from backend.api.schemas import PipelineRunRequest
        req = PipelineRunRequest(period="2026-06", tenant_id="CF001")
        assert req.tenant_id == "CF001"

    def test_pipeline_execute_request_has_tenant_id(self):
        """PipelineExecuteRequest must have tenant_id field."""
        from backend.api.schemas import PipelineExecuteRequest
        req = PipelineExecuteRequest(period="2026-06", tenant_id="CF001")
        assert req.tenant_id == "CF001"

    def test_pipeline_run_request_entity_id_removed(self):
        """PipelineRunRequest MUST NOT have entity_id."""
        from backend.api.schemas import PipelineRunRequest
        import pydantic
        fields = PipelineRunRequest.model_fields
        assert "entity_id" not in fields, (
            f"PipelineRunRequest still has 'entity_id'. Fields: {list(fields.keys())}"
        )

    def test_pipeline_execute_request_entity_id_removed(self):
        """PipelineExecuteRequest MUST NOT have entity_id."""
        from backend.api.schemas import PipelineExecuteRequest
        fields = PipelineExecuteRequest.model_fields
        assert "entity_id" not in fields, (
            f"PipelineExecuteRequest still has 'entity_id'. Fields: {list(fields.keys())}"
        )

    def test_commentary_response_has_tenant_id(self):
        """CommentaryResponse should use tenant_id."""
        from backend.api.schemas import CommentaryResponse
        resp = CommentaryResponse(period="2026-06", tenant_id="CF001")
        assert resp.tenant_id == "CF001"

    def test_pipeline_result_response_has_tenant_id(self):
        """PipelineResultResponse should use tenant_id."""
        from backend.api.schemas import PipelineResultResponse
        resp = PipelineResultResponse(
            run_id="abc", status="completed", period="2026-06",
            tenant_id="CF001", actuals_count=0, budget_count=0,
            variances=[], material_count=0, root_causes=[],
            commentary_sections=[],
        )
        assert resp.tenant_id == "CF001"


class TestSeedDataTenantScoping:
    """Verify seed data is correctly scoped by tenant."""

    def test_seed_creates_single_entity(self, multi_tenant_db):
        """Seed should create entities that are queryable."""
        with Session(multi_tenant_db) as session:
            count = session.query(Entity).count()
            assert count == 2  # CF001 + CF002

    def test_seed_gl_accounts_scoped(self, multi_tenant_db):
        """GL accounts must be scoped to their entity."""
        with Session(multi_tenant_db) as session:
            cf001_accounts = session.query(GLAccount).filter(
                GLAccount.entity_id == "CF001"
            ).count()
            cf002_accounts = session.query(GLAccount).filter(
                GLAccount.entity_id == "CF002"
            ).count()
            assert cf001_accounts > 0
            assert cf002_accounts > 0

    def test_seed_actuals_scoped(self, multi_tenant_db):
        """Actuals must be scoped to their entity."""
        with Session(multi_tenant_db) as session:
            cf001_actuals = session.query(Actual).filter(
                Actual.entity_id == "CF001"
            ).count()
            cf002_actuals = session.query(Actual).filter(
                Actual.entity_id == "CF002"
            ).count()
            assert cf001_actuals > 0
            assert cf002_actuals > 0

    def test_seed_headcount_scoped(self, multi_tenant_db):
        """Headcount data must be scoped to entity."""
        with Session(multi_tenant_db) as session:
            cf001_hc = session.query(HeadcountData).filter(
                HeadcountData.entity_id == "CF001"
            ).count()
            cf002_hc = session.query(HeadcountData).filter(
                HeadcountData.entity_id == "CF002"
            ).count()
            assert cf001_hc > 0
            assert cf002_hc > 0

    def test_seed_vendors_scoped(self, multi_tenant_db):
        """Vendor invoices must be scoped to entity."""
        with Session(multi_tenant_db) as session:
            cf001_vi = session.query(VendorInvoice).filter(
                VendorInvoice.entity_id == "CF001"
            ).count()
            cf002_vi = session.query(VendorInvoice).filter(
                VendorInvoice.entity_id == "CF002"
            ).count()
            assert cf001_vi > 0
            assert cf002_vi > 0

    def test_seed_pipeline_scoped(self, multi_tenant_db):
        """Sales pipeline must be scoped to entity."""
        with Session(multi_tenant_db) as session:
            cf001_sp = session.query(SalesPipeline).filter(
                SalesPipeline.entity_id == "CF001"
            ).count()
            cf002_sp = session.query(SalesPipeline).filter(
                SalesPipeline.entity_id == "CF002"
            ).count()
            assert cf001_sp > 0
            assert cf002_sp > 0


class TestCrossTenantQueryIsolation:
    """Advanced isolation tests — ensure no cross-tenant leakage at DB level."""

    def test_raw_sql_cannot_leak_across_tenants(self, multi_tenant_db):
        """Even raw queries should only return scoped data when using tool functions."""
        result = query_gl_detail(
            tenant_id="CF001", period="2026-06", engine=multi_tenant_db,
        )
        # Every row must be tenant CF001
        for row in result.data:
            assert row["entity_id"] == "CF001"

    def test_tenant_b_raw_query_excludes_tenant_a(self, multi_tenant_db):
        """CF002 query must not contain any CF001 data."""
        result = query_gl_detail(
            tenant_id="CF002", period="2026-06", engine=multi_tenant_db,
        )
        for row in result.data:
            assert row["entity_id"] == "CF002"

    def test_different_tenants_different_row_counts(self, multi_tenant_db):
        """CF001 and CF002 have different data volumes — verify isolation."""
        result_a = query_gl_detail(tenant_id="CF001", period="2026-06", engine=multi_tenant_db)
        result_b = query_gl_detail(tenant_id="CF002", period="2026-06", engine=multi_tenant_db)
        # CF001 has 18 GL accounts, CF002 has 3
        assert result_a.row_count > result_b.row_count

    def test_vendor_isolation_strong(self, multi_tenant_db):
        """CF001 vendors must be different from CF002 vendors."""
        result_a = query_vendor_spend(tenant_id="CF001", period="2026-06", engine=multi_tenant_db)
        result_b = query_vendor_spend(tenant_id="CF002", period="2026-06", engine=multi_tenant_db)
        vendors_a = {r["vendor_name"] for r in result_a.data}
        vendors_b = {r["vendor_name"] for r in result_b.data}
        # CF002's "Azure" must not appear in CF001's results
        assert "Azure" not in vendors_a
        # CF001's vendors must not appear in CF002's results
        assert vendors_a.isdisjoint(vendors_b) or vendors_b == {"Azure"}

    def test_pipeline_isolation_strong(self, multi_tenant_db):
        """CF001 deals must be different from CF002 deals."""
        result_a = query_sales_pipeline(tenant_id="CF001", period="2026-06", engine=multi_tenant_db)
        result_b = query_sales_pipeline(tenant_id="CF002", period="2026-06", engine=multi_tenant_db)
        deals_a = {r["deal_name"] for r in result_a.data}
        deals_b = {r["deal_name"] for r in result_b.data}
        assert "Acme Enterprise Deal" not in deals_a
        assert deals_a.isdisjoint(deals_b)
