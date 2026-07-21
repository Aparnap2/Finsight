"""TDD tests for all domain model DB tables — PRD §7.

Tests FIRST, implementation SECOND. Each table must:
- Be creatable via Base.metadata.create_all
- Have the required columns with correct types
- Support tenant_id scoping
- Support full CRUD lifecycle
"""
import json
import uuid
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from backend.models.database import (
    Base,
    Entity,
    GLAccount,
    # New tables under test
    ReviewDecision,
    ActionItemDB,
    CommentaryVersion,
    AuditLog,
    PipelineRun,
    AssertionDB,
    ToolResultCache,
    DataQualitySnapshot,
    PolicyDecisionLog,
    BridgeAnalysisResult,
    VarianceSnapshot,
    RootCauseFindingDB,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session(engine):
    with Session(engine) as s:
        yield s


def _uid() -> str:
    return str(uuid.uuid4())[:8]


def _seed_entity(session: Session, tenant_id: str = "tenant_001") -> Entity:
    entity = Entity(id=tenant_id, name="Acme Corp", currency="USD", fiscal_year_start="01")
    session.add(entity)
    session.flush()
    return entity


# ===========================================================================
# ReviewDecision
# ===========================================================================
class TestReviewDecisionTable:
    def test_table_exists(self, engine):
        tables = inspect(engine).get_table_names()
        assert "review_decisions" in tables

    def test_create_review_decision(self, session):
        _seed_entity(session)
        rd = ReviewDecision(
            id=_uid(), tenant_id="tenant_001", period="2026-06",
            assertion_id="assert_1", decision="approved",
            reviewer="cfo@example.com", confidence=0.92,
            notes="Looks good", created_at=datetime.utcnow(),
        )
        session.add(rd)
        session.commit()
        assert session.query(ReviewDecision).count() == 1

    def test_has_required_columns(self, engine):
        cols = {c["name"] for c in inspect(engine).get_columns("review_decisions")}
        required = {
            "id", "tenant_id", "period", "assertion_id",
            "decision", "reviewer", "confidence", "notes", "created_at",
        }
        assert required.issubset(cols)

    def test_tenant_scoping(self, session):
        _seed_entity(session, "t1")
        _seed_entity(session, "t2")
        session.add(ReviewDecision(
            id=_uid(), tenant_id="t1", period="2026-06",
            assertion_id="a1", decision="approved", reviewer="r1",
            confidence=1.0, created_at=datetime.utcnow(),
        ))
        session.add(ReviewDecision(
            id=_uid(), tenant_id="t2", period="2026-06",
            assertion_id="a2", decision="rejected", reviewer="r2",
            confidence=0.5, created_at=datetime.utcnow(),
        ))
        session.commit()
        t1_rows = session.query(ReviewDecision).filter_by(tenant_id="t1").all()
        t2_rows = session.query(ReviewDecision).filter_by(tenant_id="t2").all()
        assert len(t1_rows) == 1
        assert len(t2_rows) == 1
        assert t1_rows[0].decision == "approved"
        assert t2_rows[0].decision == "rejected"

    def test_update_review_decision(self, session):
        _seed_entity(session)
        rd = ReviewDecision(
            id=_uid(), tenant_id="tenant_001", period="2026-06",
            assertion_id="a1", decision="pending", reviewer="r1",
            confidence=0.5, created_at=datetime.utcnow(),
        )
        session.add(rd)
        session.commit()
        rd.decision = "approved"
        rd.confidence = Decimal("0.95")
        session.commit()
        updated = session.query(ReviewDecision).first()
        assert updated.decision == "approved"
        assert float(updated.confidence) == pytest.approx(0.95)

    def test_delete_review_decision(self, session):
        _seed_entity(session)
        rd = ReviewDecision(
            id=_uid(), tenant_id="tenant_001", period="2026-06",
            assertion_id="a1", decision="approved", reviewer="r1",
            confidence=1.0, created_at=datetime.utcnow(),
        )
        session.add(rd)
        session.commit()
        session.delete(rd)
        session.commit()
        assert session.query(ReviewDecision).count() == 0


# ===========================================================================
# ActionItemDB
# ===========================================================================
class TestActionItemDBTable:
    def test_table_exists(self, engine):
        tables = inspect(engine).get_table_names()
        assert "action_items" in tables

    def test_create_action_item(self, session):
        _seed_entity(session)
        ai = ActionItemDB(
            id=_uid(), tenant_id="tenant_001", period="2026-06",
            action="reduce", domain="cost", target="cloud spend",
            description="Cut cloud spend by 15%",
            status="proposed", owner="FinOps",
            impact_json=json.dumps({"savings": 50000}),
            cited_assertion_ids=json.dumps(["a1", "a2"]),
            blocked_reason=None,
            created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
        )
        session.add(ai)
        session.commit()
        assert session.query(ActionItemDB).count() == 1

    def test_has_required_columns(self, engine):
        cols = {c["name"] for c in inspect(engine).get_columns("action_items")}
        required = {
            "id", "tenant_id", "period", "action", "domain", "target",
            "description", "status", "owner", "impact_json",
            "cited_assertion_ids", "blocked_reason",
            "created_at", "updated_at",
        }
        assert required.issubset(cols)

    def test_tenant_scoping(self, session):
        _seed_entity(session, "t1")
        _seed_entity(session, "t2")
        session.add(ActionItemDB(
            id=_uid(), tenant_id="t1", period="2026-06",
            action="reduce", domain="cost", target="spend",
            description="...", status="proposed",
            cited_assertion_ids="[]", created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        ))
        session.add(ActionItemDB(
            id=_uid(), tenant_id="t2", period="2026-06",
            action="increase", domain="revenue", target="sales",
            description="...", status="approved",
            cited_assertion_ids="[]", created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        ))
        session.commit()
        assert session.query(ActionItemDB).filter_by(tenant_id="t1").count() == 1
        assert session.query(ActionItemDB).filter_by(tenant_id="t2").count() == 1

    def test_update_action_item(self, session):
        _seed_entity(session)
        ai = ActionItemDB(
            id=_uid(), tenant_id="tenant_001", period="2026-06",
            action="reduce", domain="cost", target="spend",
            description="...", status="proposed",
            cited_assertion_ids="[]", created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(ai)
        session.commit()
        ai.status = "approved"
        session.commit()
        assert session.query(ActionItemDB).first().status == "approved"

    def test_delete_action_item(self, session):
        _seed_entity(session)
        ai = ActionItemDB(
            id=_uid(), tenant_id="tenant_001", period="2026-06",
            action="reduce", domain="cost", target="spend",
            description="...", status="proposed",
            cited_assertion_ids="[]", created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(ai)
        session.commit()
        session.delete(ai)
        session.commit()
        assert session.query(ActionItemDB).count() == 0


# ===========================================================================
# CommentaryVersion
# ===========================================================================
class TestCommentaryVersionTable:
    def test_table_exists(self, engine):
        tables = inspect(engine).get_table_names()
        assert "commentary_versions" in tables

    def test_create_commentary_version(self, session):
        _seed_entity(session)
        cv = CommentaryVersion(
            id=_uid(), tenant_id="tenant_001", period="2026-06",
            version=1, content="Draft commentary text",
            status="draft", author="analyst@example.com",
            created_at=datetime.utcnow(),
        )
        session.add(cv)
        session.commit()
        assert session.query(CommentaryVersion).count() == 1

    def test_has_required_columns(self, engine):
        cols = {c["name"] for c in inspect(engine).get_columns("commentary_versions")}
        required = {
            "id", "tenant_id", "period", "version",
            "content", "status", "author", "created_at",
        }
        assert required.issubset(cols)

    def test_tenant_scoping(self, session):
        _seed_entity(session, "t1")
        _seed_entity(session, "t2")
        for tid in ("t1", "t2"):
            session.add(CommentaryVersion(
                id=_uid(), tenant_id=tid, period="2026-06",
                version=1, content=f"content-{tid}",
                status="draft", author="a@b.com",
                created_at=datetime.utcnow(),
            ))
        session.commit()
        assert session.query(CommentaryVersion).filter_by(tenant_id="t1").count() == 1
        assert session.query(CommentaryVersion).filter_by(tenant_id="t2").count() == 1

    def test_version_increment(self, session):
        _seed_entity(session)
        for v in range(1, 4):
            session.add(CommentaryVersion(
                id=_uid(), tenant_id="tenant_001", period="2026-06",
                version=v, content=f"version {v}",
                status="draft", author="a@b.com",
                created_at=datetime.utcnow(),
            ))
        session.commit()
        rows = session.query(CommentaryVersion).order_by(CommentaryVersion.version).all()
        assert [r.version for r in rows] == [1, 2, 3]


# ===========================================================================
# AuditLog
# ===========================================================================
class TestAuditLogTable:
    def test_table_exists(self, engine):
        tables = inspect(engine).get_table_names()
        assert "audit_logs" in tables

    def test_create_audit_log(self, session):
        _seed_entity(session)
        al = AuditLog(
            id=_uid(), tenant_id="tenant_001", period="2026-06",
            event_type="pipeline.start",
            event_data=json.dumps({"run_id": "r1"}),
            user_id="system",
            created_at=datetime.utcnow(),
        )
        session.add(al)
        session.commit()
        assert session.query(AuditLog).count() == 1

    def test_has_required_columns(self, engine):
        cols = {c["name"] for c in inspect(engine).get_columns("audit_logs")}
        required = {
            "id", "tenant_id", "period", "event_type",
            "event_data", "user_id", "created_at",
        }
        assert required.issubset(cols)

    def test_tenant_scoping(self, session):
        _seed_entity(session, "t1")
        _seed_entity(session, "t2")
        for tid in ("t1", "t2"):
            session.add(AuditLog(
                id=_uid(), tenant_id=tid, period="2026-06",
                event_type="comment.approve", event_data="{}",
                user_id="user1", created_at=datetime.utcnow(),
            ))
        session.commit()
        assert session.query(AuditLog).filter_by(tenant_id="t1").count() == 1
        assert session.query(AuditLog).filter_by(tenant_id="t2").count() == 1

    def test_event_type_filtering(self, session):
        _seed_entity(session)
        for evt in ("start", "complete", "error", "start"):
            session.add(AuditLog(
                id=_uid(), tenant_id="tenant_001", period="2026-06",
                event_type=evt, event_data="{}",
                user_id="sys", created_at=datetime.utcnow(),
            ))
        session.commit()
        starts = session.query(AuditLog).filter_by(event_type="start").count()
        assert starts == 2


# ===========================================================================
# PipelineRun
# ===========================================================================
class TestPipelineRunTable:
    def test_table_exists(self, engine):
        tables = inspect(engine).get_table_names()
        assert "pipeline_runs" in tables

    def test_create_pipeline_run(self, session):
        _seed_entity(session)
        pr = PipelineRun(
            id=_uid(), tenant_id="tenant_001", period="2026-06",
            status="running", started_at=datetime.utcnow(),
            completed_at=None, result_json=None, error=None,
        )
        session.add(pr)
        session.commit()
        assert session.query(PipelineRun).count() == 1

    def test_has_required_columns(self, engine):
        cols = {c["name"] for c in inspect(engine).get_columns("pipeline_runs")}
        required = {
            "id", "tenant_id", "period", "status",
            "started_at", "completed_at", "result_json", "error",
        }
        assert required.issubset(cols)

    def test_pipeline_run_lifecycle(self, session):
        _seed_entity(session)
        pr = PipelineRun(
            id=_uid(), tenant_id="tenant_001", period="2026-06",
            status="running", started_at=datetime.utcnow(),
        )
        session.add(pr)
        session.commit()
        pr.status = "completed"
        pr.completed_at = datetime.utcnow()
        pr.result_json = json.dumps({"variances": 5})
        session.commit()
        updated = session.query(PipelineRun).first()
        assert updated.status == "completed"
        assert updated.completed_at is not None

    def test_tenant_scoping(self, session):
        _seed_entity(session, "t1")
        _seed_entity(session, "t2")
        for tid in ("t1", "t2"):
            session.add(PipelineRun(
                id=_uid(), tenant_id=tid, period="2026-06",
                status="pending", started_at=datetime.utcnow(),
            ))
        session.commit()
        assert session.query(PipelineRun).filter_by(tenant_id="t1").count() == 1
        assert session.query(PipelineRun).filter_by(tenant_id="t2").count() == 1


# ===========================================================================
# AssertionDB
# ===========================================================================
class TestAssertionDBTable:
    def test_table_exists(self, engine):
        tables = inspect(engine).get_table_names()
        assert "assertions_db" in tables

    def test_create_assertion(self, session):
        _seed_entity(session)
        a = AssertionDB(
            id=_uid(), tenant_id="tenant_001", period="2026-06",
            assertion_id="assert_1", type="numeric",
            text="Revenue is up 12%", value=0.12,
            support_level="verified", confidence=0.95,
            evidence_ids_json=json.dumps(["ev1"]),
            metadata_json=json.dumps({"source": "deterministic"}),
            created_at=datetime.utcnow(),
        )
        session.add(a)
        session.commit()
        assert session.query(AssertionDB).count() == 1

    def test_has_required_columns(self, engine):
        cols = {c["name"] for c in inspect(engine).get_columns("assertions_db")}
        required = {
            "id", "tenant_id", "period", "assertion_id", "type",
            "text", "value", "support_level", "confidence",
            "evidence_ids_json", "metadata_json", "created_at",
        }
        assert required.issubset(cols)

    def test_tenant_scoping(self, session):
        _seed_entity(session, "t1")
        _seed_entity(session, "t2")
        for tid in ("t1", "t2"):
            session.add(AssertionDB(
                id=_uid(), tenant_id=tid, period="2026-06",
                assertion_id=f"a_{tid}", type="comparative",
                text="...", support_level="probable",
                confidence=0.7, created_at=datetime.utcnow(),
            ))
        session.commit()
        assert session.query(AssertionDB).filter_by(tenant_id="t1").count() == 1
        assert session.query(AssertionDB).filter_by(tenant_id="t2").count() == 1

    def test_support_level_filtering(self, session):
        _seed_entity(session)
        for sl in ("verified", "probable", "weak", "verified"):
            session.add(AssertionDB(
                id=_uid(), tenant_id="tenant_001", period="2026-06",
                assertion_id=_uid(), type="numeric", text="...",
                support_level=sl, confidence=0.8,
                created_at=datetime.utcnow(),
            ))
        session.commit()
        verified = session.query(AssertionDB).filter_by(support_level="verified").count()
        assert verified == 2


# ===========================================================================
# ToolResultCache
# ===========================================================================
class TestToolResultCacheTable:
    def test_table_exists(self, engine):
        tables = inspect(engine).get_table_names()
        assert "tool_result_cache" in tables

    def test_create_tool_result(self, session):
        _seed_entity(session)
        tr = ToolResultCache(
            id=_uid(), tenant_id="tenant_001", period="2026-06",
            tool_name="market_data", query_fingerprint="fp_abc123",
            result_json=json.dumps({"price": 100}),
            created_at=datetime.utcnow(),
            expires_at=datetime(2026, 7, 1),
        )
        session.add(tr)
        session.commit()
        assert session.query(ToolResultCache).count() == 1

    def test_has_required_columns(self, engine):
        cols = {c["name"] for c in inspect(engine).get_columns("tool_result_cache")}
        required = {
            "id", "tenant_id", "period", "tool_name",
            "query_fingerprint", "result_json",
            "created_at", "expires_at",
        }
        assert required.issubset(cols)

    def test_tenant_scoping(self, session):
        _seed_entity(session, "t1")
        _seed_entity(session, "t2")
        for tid in ("t1", "t2"):
            session.add(ToolResultCache(
                id=_uid(), tenant_id=tid, period="2026-06",
                tool_name="fx_rate", query_fingerprint="fp1",
                result_json="{}", created_at=datetime.utcnow(),
                expires_at=datetime(2026, 8, 1),
            ))
        session.commit()
        assert session.query(ToolResultCache).filter_by(tenant_id="t1").count() == 1
        assert session.query(ToolResultCache).filter_by(tenant_id="t2").count() == 1

    def test_fingerprint_uniqueness_in_practice(self, session):
        """Multiple tools can share a fingerprint, but same tool+fp is dedup-worthy."""
        _seed_entity(session)
        for i in range(3):
            session.add(ToolResultCache(
                id=_uid(), tenant_id="tenant_001", period="2026-06",
                tool_name="fx_rate", query_fingerprint="same_fp",
                result_json="{}", created_at=datetime.utcnow(),
                expires_at=datetime(2026, 8, 1),
            ))
        session.commit()
        rows = session.query(ToolResultCache).filter_by(
            tool_name="fx_rate", query_fingerprint="same_fp"
        ).all()
        assert len(rows) == 3


# ===========================================================================
# DataQualitySnapshot
# ===========================================================================
class TestDataQualitySnapshotTable:
    def test_table_exists(self, engine):
        tables = inspect(engine).get_table_names()
        assert "data_quality_snapshots" in tables

    def test_create_snapshot(self, session):
        _seed_entity(session)
        dq = DataQualitySnapshot(
            id=_uid(), tenant_id="tenant_001", period="2026-06",
            report_json=json.dumps({"completeness": 0.98, "timeliness": 0.95}),
            overall_score=0.965,
            created_at=datetime.utcnow(),
        )
        session.add(dq)
        session.commit()
        assert session.query(DataQualitySnapshot).count() == 1

    def test_has_required_columns(self, engine):
        cols = {c["name"] for c in inspect(engine).get_columns("data_quality_snapshots")}
        required = {
            "id", "tenant_id", "period", "report_json",
            "overall_score", "created_at",
        }
        assert required.issubset(cols)

    def test_tenant_scoping(self, session):
        _seed_entity(session, "t1")
        _seed_entity(session, "t2")
        for tid in ("t1", "t2"):
            session.add(DataQualitySnapshot(
                id=_uid(), tenant_id=tid, period="2026-06",
                report_json="{}", overall_score=0.9,
                created_at=datetime.utcnow(),
            ))
        session.commit()
        assert session.query(DataQualitySnapshot).filter_by(tenant_id="t1").count() == 1
        assert session.query(DataQualitySnapshot).filter_by(tenant_id="t2").count() == 1


# ===========================================================================
# PolicyDecisionLog
# ===========================================================================
class TestPolicyDecisionLogTable:
    def test_table_exists(self, engine):
        tables = inspect(engine).get_table_names()
        assert "policy_decision_logs" in tables

    def test_create_policy_decision(self, session):
        _seed_entity(session)
        pd = PolicyDecisionLog(
            id=_uid(), tenant_id="tenant_001", period="2026-06",
            autonomy_level="semi_autonomous",
            routing_target="human_review",
            reasons_json=json.dumps(["high_value", "unusual_pattern"]),
            confidence=0.65,
            created_at=datetime.utcnow(),
        )
        session.add(pd)
        session.commit()
        assert session.query(PolicyDecisionLog).count() == 1

    def test_has_required_columns(self, engine):
        cols = {c["name"] for c in inspect(engine).get_columns("policy_decision_logs")}
        required = {
            "id", "tenant_id", "period", "autonomy_level",
            "routing_target", "reasons_json", "confidence", "created_at",
        }
        assert required.issubset(cols)

    def test_tenant_scoping(self, session):
        _seed_entity(session, "t1")
        _seed_entity(session, "t2")
        for tid in ("t1", "t2"):
            session.add(PolicyDecisionLog(
                id=_uid(), tenant_id=tid, period="2026-06",
                autonomy_level="autonomous", routing_target="auto_approve",
                reasons_json="[]", confidence=0.9,
                created_at=datetime.utcnow(),
            ))
        session.commit()
        assert session.query(PolicyDecisionLog).filter_by(tenant_id="t1").count() == 1
        assert session.query(PolicyDecisionLog).filter_by(tenant_id="t2").count() == 1

    def test_routing_target_filtering(self, session):
        _seed_entity(session)
        for rt in ("auto_approve", "human_review", "auto_approve"):
            session.add(PolicyDecisionLog(
                id=_uid(), tenant_id="tenant_001", period="2026-06",
                autonomy_level="semi", routing_target=rt,
                reasons_json="[]", confidence=0.8,
                created_at=datetime.utcnow(),
            ))
        session.commit()
        auto = session.query(PolicyDecisionLog).filter_by(routing_target="auto_approve").count()
        assert auto == 2


# ===========================================================================
# BridgeAnalysisResult
# ===========================================================================
class TestBridgeAnalysisResultTable:
    def test_table_exists(self, engine):
        tables = inspect(engine).get_table_names()
        assert "bridge_analysis_results" in tables

    def test_create_bridge_result(self, session):
        _seed_entity(session)
        br = BridgeAnalysisResult(
            id=_uid(), tenant_id="tenant_001", period="2026-06",
            account_id="acc_1",
            bridge_json=json.dumps({"opening": 1000, "closing": 1200}),
            reconciles=True, confidence=0.91,
            created_at=datetime.utcnow(),
        )
        session.add(br)
        session.commit()
        assert session.query(BridgeAnalysisResult).count() == 1

    def test_has_required_columns(self, engine):
        cols = {c["name"] for c in inspect(engine).get_columns("bridge_analysis_results")}
        required = {
            "id", "tenant_id", "period", "account_id",
            "bridge_json", "reconciles", "confidence", "created_at",
        }
        assert required.issubset(cols)

    def test_tenant_scoping(self, session):
        _seed_entity(session, "t1")
        _seed_entity(session, "t2")
        for tid in ("t1", "t2"):
            session.add(BridgeAnalysisResult(
                id=_uid(), tenant_id=tid, period="2026-06",
                account_id="a1", bridge_json="{}",
                reconciles=True, confidence=0.9,
                created_at=datetime.utcnow(),
            ))
        session.commit()
        assert session.query(BridgeAnalysisResult).filter_by(tenant_id="t1").count() == 1
        assert session.query(BridgeAnalysisResult).filter_by(tenant_id="t2").count() == 1

    def test_reconciles_filtering(self, session):
        _seed_entity(session)
        for rec in (True, False, True):
            session.add(BridgeAnalysisResult(
                id=_uid(), tenant_id="tenant_001", period="2026-06",
                account_id="a1", bridge_json="{}",
                reconciles=rec, confidence=0.8,
                created_at=datetime.utcnow(),
            ))
        session.commit()
        assert session.query(BridgeAnalysisResult).filter_by(reconciles=True).count() == 2
        assert session.query(BridgeAnalysisResult).filter_by(reconciles=False).count() == 1


# ===========================================================================
# VarianceSnapshot
# ===========================================================================
class TestVarianceSnapshotTable:
    def test_table_exists(self, engine):
        tables = inspect(engine).get_table_names()
        assert "variance_snapshots" in tables

    def test_create_variance_snapshot(self, session):
        _seed_entity(session)
        vs = VarianceSnapshot(
            id=_uid(), tenant_id="tenant_001", period="2026-06",
            account_id="acc_4000",
            variance_json=json.dumps({
                "actual": 450000, "budget": 500000,
                "variance": -50000, "pct": -0.10,
            }),
            is_material=True,
            created_at=datetime.utcnow(),
        )
        session.add(vs)
        session.commit()
        assert session.query(VarianceSnapshot).count() == 1

    def test_has_required_columns(self, engine):
        cols = {c["name"] for c in inspect(engine).get_columns("variance_snapshots")}
        required = {
            "id", "tenant_id", "period", "account_id",
            "variance_json", "is_material", "created_at",
        }
        assert required.issubset(cols)

    def test_tenant_scoping(self, session):
        _seed_entity(session, "t1")
        _seed_entity(session, "t2")
        for tid in ("t1", "t2"):
            session.add(VarianceSnapshot(
                id=_uid(), tenant_id=tid, period="2026-06",
                account_id="a1", variance_json="{}",
                is_material=False, created_at=datetime.utcnow(),
            ))
        session.commit()
        assert session.query(VarianceSnapshot).filter_by(tenant_id="t1").count() == 1
        assert session.query(VarianceSnapshot).filter_by(tenant_id="t2").count() == 1

    def test_material_filtering(self, session):
        _seed_entity(session)
        for mat in (True, False, True, True):
            session.add(VarianceSnapshot(
                id=_uid(), tenant_id="tenant_001", period="2026-06",
                account_id="a1", variance_json="{}",
                is_material=mat, created_at=datetime.utcnow(),
            ))
        session.commit()
        assert session.query(VarianceSnapshot).filter_by(is_material=True).count() == 3
        assert session.query(VarianceSnapshot).filter_by(is_material=False).count() == 1


# ===========================================================================
# RootCauseFindingDB
# ===========================================================================
class TestRootCauseFindingDBTable:
    def test_table_exists(self, engine):
        tables = inspect(engine).get_table_names()
        assert "root_cause_findings_db" in tables

    def test_create_root_cause_finding(self, session):
        _seed_entity(session)
        rcf = RootCauseFindingDB(
            id=_uid(), tenant_id="tenant_001", period="2026-06",
            account_id="acc_7000",
            finding_json=json.dumps({
                "summary": "AWS spend surge due to unoptimized instances",
                "evidence": ["ev1", "ev2"],
                "recommended_action": "Right-size EC2 fleet",
            }),
            confidence=0.88,
            created_at=datetime.utcnow(),
        )
        session.add(rcf)
        session.commit()
        assert session.query(RootCauseFindingDB).count() == 1

    def test_has_required_columns(self, engine):
        cols = {c["name"] for c in inspect(engine).get_columns("root_cause_findings_db")}
        required = {
            "id", "tenant_id", "period", "account_id",
            "finding_json", "confidence", "created_at",
        }
        assert required.issubset(cols)

    def test_tenant_scoping(self, session):
        _seed_entity(session, "t1")
        _seed_entity(session, "t2")
        for tid in ("t1", "t2"):
            session.add(RootCauseFindingDB(
                id=_uid(), tenant_id=tid, period="2026-06",
                account_id="a1", finding_json="{}",
                confidence=0.8, created_at=datetime.utcnow(),
            ))
        session.commit()
        assert session.query(RootCauseFindingDB).filter_by(tenant_id="t1").count() == 1
        assert session.query(RootCauseFindingDB).filter_by(tenant_id="t2").count() == 1

    def test_confidence_filtering(self, session):
        _seed_entity(session)
        for c in (0.9, 0.5, 0.95, 0.9):
            session.add(RootCauseFindingDB(
                id=_uid(), tenant_id="tenant_001", period="2026-06",
                account_id="a1", finding_json="{}",
                confidence=c, created_at=datetime.utcnow(),
            ))
        session.commit()
        high_conf = session.query(RootCauseFindingDB).filter(
            RootCauseFindingDB.confidence >= 0.9
        ).count()
        assert high_conf == 3


# ===========================================================================
# Cross-cutting: all 12 new tables exist
# ===========================================================================
class TestAllNewTablesExist:
    EXPECTED_NEW_TABLES = [
        "review_decisions",
        "action_items",
        "commentary_versions",
        "audit_logs",
        "pipeline_runs",
        "assertions_db",
        "tool_result_cache",
        "data_quality_snapshots",
        "policy_decision_logs",
        "bridge_analysis_results",
        "variance_snapshots",
        "root_cause_findings_db",
    ]

    def test_all_12_new_tables_created(self, engine):
        tables = set(inspect(engine).get_table_names())
        missing = [t for t in self.EXPECTED_NEW_TABLES if t not in tables]
        assert not missing, f"Missing tables: {missing}"

    def test_original_tables_still_exist(self, engine):
        tables = set(inspect(engine).get_table_names())
        originals = {
            "entities", "gl_accounts", "trial_balance", "budget_lines",
            "forecast_lines", "actuals", "headcount_data", "vendor_invoices",
            "sales_pipeline", "agent_runs", "variances", "root_causes",
            "commentary_drafts", "scenarios", "review_logs",
        }
        missing = originals - tables
        assert not missing, f"Original tables missing: {missing}"


# ===========================================================================
# Cross-cutting: ALL tables support tenant_id
# ===========================================================================
class TestTenantScoping:
    """Every new table must have a tenant_id column for multi-tenant isolation."""

    TENANT_TABLES = [
        "review_decisions", "action_items", "commentary_versions",
        "audit_logs", "pipeline_runs", "assertions_db",
        "tool_result_cache", "data_quality_snapshots",
        "policy_decision_logs", "bridge_analysis_results",
        "variance_snapshots", "root_cause_findings_db",
    ]

    def test_all_new_tables_have_tenant_id(self, engine):
        inspector = inspect(engine)
        for table_name in self.TENANT_TABLES:
            cols = {c["name"] for c in inspector.get_columns(table_name)}
            assert "tenant_id" in cols, f"{table_name} missing tenant_id"


# ===========================================================================
# Cross-table integration: seed data round-trip
# ===========================================================================
class TestSeedDataIntegration:
    """Verify that seed data can be inserted and queried across the new tables."""

    def test_seed_review_decision_and_query(self, session):
        _seed_entity(session)
        rd = ReviewDecision(
            id="rd_001", tenant_id="tenant_001", period="2026-06",
            assertion_id="assert_rev_1", decision="approved",
            reviewer="cfo@acme.com", confidence=Decimal("0.95"),
            notes="Revenue assertion verified",
            created_at=datetime.utcnow(),
        )
        session.add(rd)
        session.commit()
        result = session.query(ReviewDecision).filter_by(assertion_id="assert_rev_1").one()
        assert result.decision == "approved"
        assert float(result.confidence) == pytest.approx(0.95)

    def test_seed_full_pipeline_run_cycle(self, session):
        _seed_entity(session)
        pr = PipelineRun(
            id="pr_001", tenant_id="tenant_001", period="2026-06",
            status="running", started_at=datetime.utcnow(),
        )
        session.add(pr)
        session.commit()

        # Create an audit log for the start
        session.add(AuditLog(
            id="al_001", tenant_id="tenant_001", period="2026-06",
            event_type="pipeline.start", event_data=json.dumps({"run_id": "pr_001"}),
            user_id="system", created_at=datetime.utcnow(),
        ))
        session.commit()

        # Complete the run
        pr.status = "completed"
        pr.completed_at = datetime.utcnow()
        pr.result_json = json.dumps({"status": "ok", "variances_found": 5})
        session.commit()

        # Verify the audit trail
        logs = session.query(AuditLog).filter_by(tenant_id="tenant_001").all()
        assert len(logs) == 1
        assert logs[0].event_type == "pipeline.start"

        # Verify the run completed
        run = session.query(PipelineRun).first()
        assert run.status == "completed"
        assert run.result_json is not None

    def test_cross_table_tenant_isolation(self, session):
        """Ensure tenant A cannot see tenant B data across any table."""
        _seed_entity(session, "alpha")
        _seed_entity(session, "beta")

        # Insert into every new table for tenant alpha
        now = datetime.utcnow()
        session.add(ReviewDecision(
            id=_uid(), tenant_id="alpha", period="2026-06",
            assertion_id="a1", decision="ok", reviewer="r1",
            confidence=0.9, created_at=now,
        ))
        session.add(ActionItemDB(
            id=_uid(), tenant_id="alpha", period="2026-06",
            action="reduce", domain="cost", target="x",
            description="...", status="proposed",
            cited_assertion_ids="[]", created_at=now, updated_at=now,
        ))
        session.add(CommentaryVersion(
            id=_uid(), tenant_id="alpha", period="2026-06",
            version=1, content="draft", status="draft",
            author="a@b.com", created_at=now,
        ))
        session.add(AuditLog(
            id=_uid(), tenant_id="alpha", period="2026-06",
            event_type="x", event_data="{}", user_id="u",
            created_at=now,
        ))
        session.add(PipelineRun(
            id=_uid(), tenant_id="alpha", period="2026-06",
            status="done", started_at=now,
        ))
        session.add(AssertionDB(
            id=_uid(), tenant_id="alpha", period="2026-06",
            assertion_id="a1", type="numeric", text="...",
            support_level="verified", confidence=0.9, created_at=now,
        ))
        session.add(ToolResultCache(
            id=_uid(), tenant_id="alpha", period="2026-06",
            tool_name="t", query_fingerprint="fp",
            result_json="{}", created_at=now, expires_at=now,
        ))
        session.add(DataQualitySnapshot(
            id=_uid(), tenant_id="alpha", period="2026-06",
            report_json="{}", overall_score=0.9, created_at=now,
        ))
        session.add(PolicyDecisionLog(
            id=_uid(), tenant_id="alpha", period="2026-06",
            autonomy_level="auto", routing_target="auto",
            reasons_json="[]", confidence=0.9, created_at=now,
        ))
        session.add(BridgeAnalysisResult(
            id=_uid(), tenant_id="alpha", period="2026-06",
            account_id="a1", bridge_json="{}", reconciles=True,
            confidence=0.9, created_at=now,
        ))
        session.add(VarianceSnapshot(
            id=_uid(), tenant_id="alpha", period="2026-06",
            account_id="a1", variance_json="{}", is_material=True,
            created_at=now,
        ))
        session.add(RootCauseFindingDB(
            id=_uid(), tenant_id="alpha", period="2026-06",
            account_id="a1", finding_json="{}", confidence=0.9,
            created_at=now,
        ))
        session.commit()

        # Verify beta sees nothing across all tables
        for model, label in [
            (ReviewDecision, "review_decisions"),
            (ActionItemDB, "action_items"),
            (CommentaryVersion, "commentary_versions"),
            (AuditLog, "audit_logs"),
            (PipelineRun, "pipeline_runs"),
            (AssertionDB, "assertions_db"),
            (ToolResultCache, "tool_result_cache"),
            (DataQualitySnapshot, "data_quality_snapshots"),
            (PolicyDecisionLog, "policy_decision_logs"),
            (BridgeAnalysisResult, "bridge_analysis_results"),
            (VarianceSnapshot, "variance_snapshots"),
            (RootCauseFindingDB, "root_cause_findings_db"),
        ]:
            alpha_count = session.query(model).filter_by(tenant_id="alpha").count()
            beta_count = session.query(model).filter_by(tenant_id="beta").count()
            assert alpha_count == 1, f"{label}: expected 1 for alpha, got {alpha_count}"
            assert beta_count == 0, f"{label}: expected 0 for beta, got {beta_count}"
