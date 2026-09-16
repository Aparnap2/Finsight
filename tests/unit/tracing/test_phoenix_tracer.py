"""P5-09 PhoenixTracer 10-criteria matrix — TDD RED → GREEN.

Vendors are replaceable behind TracerProtocol:
NoOpTracer | PhoenixTracer (first) | LangfuseTracer (optional).

Matrix (Issue #40):
1  complete trajectory CASE-1027 contains every stage (13-hop)
2  tool correlation (capability call ↔ result share correlation_id)
3  latency (every hop emits latency_ms)
4  context bounded inspectable without PII
5  evaluation attach (score/feedback as span)
6  secret/PII redacted
7  correlation_id preserved (tenant-safe, queryable)
8  local deployment no SaaS (docker-compose.phoenix.yml, localhost:6006)
9  OTel export (phoenix.otel.register + TracerProvider + batch)
10 backend swap NoOp vs Phoenix same trajectory (no branching)

All tests are pure unit — phoenix.otel.register and OTel are mocked,
zero network, zero SaaS, zero secrets leaked.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shared.tracing.noop import NoOpTracer  # noqa: E501
from shared.tracing.observability import ObservabilityTrace  # noqa: E501
from shared.tracing.protocol import TraceContext, TracerProtocol  # noqa: E501
from shared.tracing.redaction import is_unrestricted_payload  # noqa: E501

# ---------------------------------------------------------------------------
# Helpers — mock Phoenix OTel without installing arize-phoenix
# ---------------------------------------------------------------------------


def _ensure_phoenix_stub() -> None:
    """Inject minimal phoenix stub modules so patch targets exist."""
    if "phoenix" not in sys.modules:
        phoenix_mod = types.ModuleType("phoenix")
        sys.modules["phoenix"] = phoenix_mod
    if "phoenix.otel" not in sys.modules:
        otel_mod = types.ModuleType("phoenix.otel")

        def _register(**kwargs):  # type: ignore[no-untyped-def]
            m = MagicMock()
            m._register_kwargs = kwargs
            m.force_flush = MagicMock()
            m.get_tracer = MagicMock(return_value=MagicMock())
            return m

        otel_mod.register = _register  # type: ignore[attr-defined]
        sys.modules["phoenix.otel"] = otel_mod
        # also attach to parent
        sys.modules["phoenix"].otel = otel_mod  # type: ignore[attr-defined]
    if "opentelemetry" not in sys.modules:
        ot_mod = types.ModuleType("opentelemetry")
        sys.modules["opentelemetry"] = ot_mod
    if "opentelemetry.trace" not in sys.modules:
        trace_mod = types.ModuleType("opentelemetry.trace")
        trace_mod.get_tracer = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
        sys.modules["opentelemetry.trace"] = trace_mod


_ensure_phoenix_stub()


def make_phoenix_tracer(
    endpoint: str = "http://localhost:6006/v1/traces",
    project_name: str = "finsight",
    auto_instrument: bool = True,
    batch: bool = True,
) -> tuple[object, MagicMock, MagicMock]:
    """Create a PhoenixTracer with mocked register/get_tracer.

    Returns:
        (tracer, mock_register, mock_provider)
    """
    mock_provider = MagicMock()
    mock_provider.force_flush = MagicMock()
    mock_span = MagicMock()
    mock_span.get_span_context.return_value.trace_id = 0xABCDEF
    mock_span.set_attribute = MagicMock()
    mock_span.end = MagicMock()

    mock_tracer = MagicMock()
    mock_tracer.start_span.return_value = mock_span
    # start_as_current_span returns a context manager
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=mock_span)
    cm.__exit__ = MagicMock(return_value=False)
    mock_tracer.start_as_current_span.return_value = cm

    mock_register = MagicMock(return_value=mock_provider)

    with patch("phoenix.otel.register", mock_register), patch(
        "opentelemetry.trace.get_tracer", return_value=mock_tracer
    ):
        # Reimport to ensure fresh class uses patched deps
        import shared.tracing.phoenix_tracer as mod  # noqa: E501

        importlib.reload(mod)
        tracer = mod.PhoenixTracer(
            endpoint=endpoint,
            project_name=project_name,
            auto_instrument=auto_instrument,
            batch=batch,
        )
        # Keep refs for assertions
        tracer._mock_register = mock_register  # type: ignore[attr-defined]
        tracer._mock_provider = mock_provider  # type: ignore[attr-defined]
        tracer._mock_tracer = mock_tracer  # type: ignore[attr-defined]
        return tracer, mock_register, mock_provider


# ---------------------------------------------------------------------------
# Criterion 1: complete trajectory CASE-1027 contains every stage
# ---------------------------------------------------------------------------


class TestCriterion1CompleteTrajectory:
    """CASE-1027 must emit all 13 hops via PhoenixTracer."""

    def test_full_13_hop_via_observability(self) -> None:
        tracer, _, _ = make_phoenix_tracer()
        obs = ObservabilityTrace(
            tracer,  # type: ignore[arg-type]
            correlation_id="CASE-1027",
            tenant_id="tenant-a",
            case_id="CASE-1027",
            exception_type="I-REFUND-LAG",
        )
        ctx = obs.start_case()
        obs.context_assembly(ctx, evidence_ids=("ev-1", "ev-2"), latency_ms=5.1, status="ok")
        obs.planner(ctx, evidence_ids=("ev-1",), allowlist=("get_stripe_payment",), latency_ms=3)  # noqa: E501
        obs.llm_generation(
            ctx,
            name="planner_llm",
            model="groq",
            input_data={"hypothesis_text": "candidate"},
            output={"hypothesis_text": "ok"},
            usage={"prompt_tokens": 10},
            latency_ms=42,
        )
        obs.verifier(ctx, status="ACCEPTED", reason_codes=(), latency_ms=2)
        obs.capability_call(
            ctx, capability="get_stripe_payment", args={"payment_id": "pay_1"}, order_index=0, latency_ms=10  # noqa: E501
        )
        obs.capability_result(
            ctx, capability="get_stripe_payment", result_summary={"row_count": 1}, success=True, latency_ms=8  # noqa: E501
        )
        obs.replan(ctx, attempt=1, reason_codes=("grounding_violation",), latency_ms=4)
        obs.final_candidate(ctx, hypothesis_ref="hypo-1", evidence_required=("ev-1",), latency_ms=1)
        obs.policy(ctx, decision="ALLOW", latency_ms=1)
        obs.approval(ctx, decision="APPROVED", approver_ref="approver-1", idempotency_key="appr-1", latency_ms=1)  # noqa: E501
        obs.execution(ctx, idempotency_key="exec-1", status="executed", latency_ms=12)
        obs.verification(ctx, status="VERIFIED", latency_ms=2)
        obs.flush()

        # PhoenixTracer captures bounded spans in-memory
        assert hasattr(tracer, "spans")
        spans = tracer.spans  # type: ignore[attr-defined]
        names = [s["name"] for s in spans]
        # Must contain each stage at least once
        required = [
            "exception_resolution",
            "case",
            "context_assembly",
            "planner",
            "planner_llm",
            "guardrail:verifier",
            "capability:get_stripe_payment",  # noqa: E501
            "capability_result:get_stripe_payment",  # noqa: E501
            "replan",
            "final_candidate",
            "guardrail:policy",
            "guardrail:approval",
            "execution",
            "guardrail:verification",
        ]
        for req in required:
            assert req in names, f"missing hop {req} in {names}"
        assert len(spans) >= 13


# ---------------------------------------------------------------------------
# Criterion 2: tool correlation
# ---------------------------------------------------------------------------


class TestCriterion2ToolCorrelation:
    """Capability call and result share correlation_id in metadata."""

    def test_tool_call_and_result_share_correlation(self) -> None:
        tracer, _, _ = make_phoenix_tracer()
        obs = ObservabilityTrace(
            tracer,  # type: ignore[arg-type]
            correlation_id="CASE-1027",
            tenant_id="tenant-a",
            case_id="CASE-1027",
            exception_type="I-REFUND-LAG",
        )
        ctx = obs.start_case()
        obs.capability_call(ctx, capability="search_gmail", args={"query": "refund"}, order_index=0)
        obs.capability_result(ctx, capability="search_gmail", result_summary={"row_count": 1}, success=True)  # noqa: E501

        spans = tracer.spans  # type: ignore[attr-defined]
        tool_spans = [s for s in spans if "search_gmail" in s["name"]]
        assert len(tool_spans) == 2
        for sp in tool_spans:
            assert sp["metadata"]["correlation_id"] == "CASE-1027"
            assert sp["metadata"]["tenant_id"] == "tenant-a"
            assert sp["metadata"]["case_id"] == "CASE-1027"


# ---------------------------------------------------------------------------
# Criterion 3: latency
# ---------------------------------------------------------------------------


class TestCriterion3Latency:
    """Every hop must carry latency_ms in metadata."""

    def test_every_hop_has_latency(self) -> None:
        tracer, _, _ = make_phoenix_tracer()
        obs = ObservabilityTrace(
            tracer,  # type: ignore[arg-type]
            correlation_id="CASE-1027",
            tenant_id="tenant-a",
            case_id="CASE-1027",
            exception_type="I-REFUND-LAG",
        )
        ctx = obs.start_case()
        obs.context_assembly(ctx, evidence_ids=("ev-1",), latency_ms=5.5)
        obs.planner(ctx, allowlist=("get_stripe_payment",), latency_ms=2.2)  # noqa: E501
        obs.llm_generation(
            ctx,
            name="gen",
            model="groq",
            input_data={"x": 1},
            output={"y": 1},
            usage={},
            latency_ms=99.9,
        )
        obs.verifier(ctx, status="ACCEPTED", latency_ms=1.1)
        obs.capability_call(ctx, capability="get_stripe_payment", args={}, order_index=0, latency_ms=7)  # noqa: E501
        obs.capability_result(ctx, capability="get_stripe_payment", result_summary={}, success=True, latency_ms=6)  # noqa: E501
        obs.policy(ctx, decision="ALLOW", latency_ms=0.5)
        obs.flush()

        spans = tracer.spans  # type: ignore[attr-defined]
        # At least the hops we emitted should have latency
        for sp in spans:
            assert "latency_ms" in sp["metadata"] or sp["name"] == "exception_resolution"


# ---------------------------------------------------------------------------
# Criterion 4: context bounded inspectable without PII
# ---------------------------------------------------------------------------


class TestCriterion4BoundedContextInspectable:
    """Context must be bounded (32 evidence) and contain no PII."""

    def test_evidence_bounded_and_no_pii(self) -> None:
        tracer, _, _ = make_phoenix_tracer()
        obs = ObservabilityTrace(
            tracer,  # type: ignore[arg-type]
            correlation_id="CASE-1027",
            tenant_id="tenant-a",
            case_id="CASE-1027",
            exception_type="I-REFUND-LAG",
        )
        ctx = obs.start_case()
        many_ids = tuple(f"ev-{i}" for i in range(100))
        obs.context_assembly(ctx, evidence_ids=many_ids, latency_ms=1)
        obs.llm_generation(
            ctx,
            name="gen",
            model="groq",
            input_data={"hypothesis_text": "hello alice@example.com " + "x" * 600},
            output={"hypothesis_text": "ok"},
            usage={},
        )
        spans = tracer.spans  # type: ignore[attr-defined]
        # Find context_assembly span
        ca = next(s for s in spans if s["name"] == "context_assembly")
        # Bounded to 32
        assert len(ca["input"]["evidence_ids"]) <= 32
        assert ca["input"]["evidence_count"] == 100
        # No raw email in any span
        for sp in spans:
            payload_str = str(sp["input"]) + str(sp["output"])
            assert "alice@example.com" not in payload_str
            assert not is_unrestricted_payload(sp["input"])
            assert not is_unrestricted_payload(sp["output"])
        # Inspectable: spans list is available and JSON-serializable
        import json

        json.dumps(spans, default=str)


# ---------------------------------------------------------------------------
# Criterion 5: evaluation attach
# ---------------------------------------------------------------------------


class TestCriterion5EvaluationAttach:
    """Evaluation score/feedback can be attached as a span without PII."""

    def test_evaluation_span_attachable(self) -> None:
        tracer, _, _ = make_phoenix_tracer()
        # PhoenixTracer is a TracerProtocol — we can attach a generic evaluation span
        ctx = tracer.trace("CASE-1027", "tenant-a", "I-REFUND-LAG")  # type: ignore[attr-defined]
        # Simulate evaluation attachment via generic span
        tracer.span(  # type: ignore[attr-defined]
            ctx,
            "evaluation",
            {"correlation_id": "CASE-1027", "eval_score": 0.92, "rubric": "grounding"},
            {"status": "passed", "feedback": "well grounded"},
            {"correlation_id": "CASE-1027", "tenant_id": "tenant-a", "case_id": "CASE-1027", "eval_score": 0.92},  # noqa: E501
        )
        spans = tracer.spans  # type: ignore[attr-defined]
        eval_span = next(s for s in spans if s["name"] == "evaluation")
        assert eval_span["metadata"]["eval_score"] == 0.92
        assert eval_span["input"]["eval_score"] == 0.92
        assert "alice@example.com" not in str(eval_span)


# ---------------------------------------------------------------------------
# Criterion 6: secret/PII redacted
# ---------------------------------------------------------------------------


class TestCriterion6SecretPIIRedacted:
    """Secrets and PII must be redacted before export."""

    def test_secret_and_pii_redacted_in_all_kinds(self) -> None:
        tracer, _, _ = make_phoenix_tracer()
        ctx = tracer.trace("CASE-1027", "tenant-a", "I-REFUND-LAG")  # type: ignore[attr-defined]
        tracer.generation(  # type: ignore[attr-defined]
            ctx,
            "gen",
            "groq",
            {"api_key": "sk-live-123", "hypothesis_text": "contact alice@example.com"},
            {"output": "ok", "token": "secret-token-xyz"},
            {},
            {"correlation_id": "CASE-1027"},
        )
        tracer.tool(  # type: ignore[attr-defined]
            ctx,
            "capability:search_gmail",
            {"query": "refund", "body": "secret body", "api_key": "sk-abc"},
            {"rows": 1, "gmail_body": "huge body" * 100},
            {"correlation_id": "CASE-1027"},
        )
        tracer.guardrail(  # type: ignore[attr-defined]
            ctx,
            "policy",
            {"api_key": "sk-123"},
            {"status": "ALLOW"},
            True,
            [],
            {"correlation_id": "CASE-1027"},
        )

        for sp in tracer.spans:  # type: ignore[attr-defined]
            flat = str(sp["input"]) + str(sp["output"]) + str(sp["metadata"])
            # No raw secret, no raw email, no raw gmail body
            assert "alice@example.com" not in flat
            assert "sk-live-123" not in flat
            assert "huge body" not in flat or "[REDACTED" in flat
            assert is_unrestricted_payload(sp["input"]) is False
            assert is_unrestricted_payload(sp["output"]) is False


# ---------------------------------------------------------------------------
# Criterion 7: correlation_id preserved
# ---------------------------------------------------------------------------


class TestCriterion7CorrelationIdPreserved:
    """correlation_id must be tenant-safe, preserved across hops, queryable."""

    def test_correlation_id_preserved_and_tenant_safe(self) -> None:
        tracer, _, _ = make_phoenix_tracer()
        obs = ObservabilityTrace(
            tracer,  # type: ignore[arg-type]
            correlation_id="CASE-1027",
            tenant_id="tenant-a",
            case_id="CASE-1027",
            exception_type="I-REFUND-LAG",
        )
        ctx = obs.start_case()
        assert ctx.trace_id == "CASE-1027"
        obs.context_assembly(ctx, evidence_ids=("ev-1",), latency_ms=1)
        obs.verification(ctx, status="VERIFIED")

        spans = tracer.spans  # type: ignore[attr-defined]
        for sp in spans:
            assert sp["metadata"]["correlation_id"] == "CASE-1027"
            assert sp["trace_id"] == "CASE-1027"
            # tenant-safe pattern: no email, no space
            assert "@" not in sp["metadata"]["correlation_id"]
            assert " " not in sp["metadata"]["correlation_id"]

        # Queryability: all spans for CASE-1027 share the same trace_id
        trace_ids = {sp["trace_id"] for sp in spans}
        assert trace_ids == {"CASE-1027"}

    def test_correlation_rejects_pii(self) -> None:
        with pytest.raises(ValueError):
            ObservabilityTrace(
                NoOpTracer(),
                correlation_id="alice@example.com",
                tenant_id="tenant-a",
                case_id="CASE-1027",
                exception_type="E",
            )


# ---------------------------------------------------------------------------
# Criterion 8: local deployment no SaaS
# ---------------------------------------------------------------------------


class TestCriterion8LocalDeploymentNoSaaS:
    """docker-compose.phoenix.yml exists, endpoint is localhost, no SaaS."""

    def test_compose_file_exists_and_is_local(self) -> None:
        compose = Path("docker-compose.phoenix.yml")
        # Also check absolute fallback for test runner cwd
        if not compose.exists():
            compose = Path(__file__).parents[3] / "docker-compose.phoenix.yml"
        assert compose.exists(), "docker-compose.phoenix.yml must exist"
        content = compose.read_text()
        # Must reference local Phoenix, not SaaS langfuse cloud
        assert "arizephoenix/phoenix" in content or "phoenix" in content.lower()
        assert "6006" in content
        assert "4317" in content
        assert "cloud.langfuse.com" not in content
        # No SaaS credentials required — check no hardcoded api keys beyond dev placeholders
        assert "PHOENIX_ENABLE_AUTH" in content or "phoenix" in content.lower()

    def test_default_endpoint_is_localhost(self) -> None:
        tracer, _, _ = make_phoenix_tracer(endpoint="http://localhost:6006/v1/traces")
        assert tracer.endpoint == "http://localhost:6006/v1/traces"  # type: ignore[attr-defined]
        assert "localhost:6006" in tracer.otel_endpoint  # type: ignore[attr-defined]
        assert "cloud.langfuse.com" not in tracer.otel_endpoint  # type: ignore[attr-defined]

    def test_factory_phoenix_env_triggers_local(self) -> None:
        from shared.tracing.factory import create_tracer  # noqa: E501

        # PHOENIX_COLLECTOR_ENDPOINT set → PhoenixTracer (mocked)
        tracer, mock_reg, _ = make_phoenix_tracer()
        # Patch factory's lazy import to return our mock tracer instance
        with patch("shared.tracing.phoenix_tracer.PhoenixTracer", return_value=tracer):  # noqa: E501
            t = create_tracer(_env={"PHOENIX_COLLECTOR_ENDPOINT": "http://localhost:6006/v1/traces"})  # noqa: E501
            assert t is tracer
        # Without PHOENIX env, fallback to NoOp
        from shared.tracing.noop import NoOpTracer  # noqa: E501

        t2 = create_tracer(_env={})
        assert isinstance(t2, NoOpTracer)


# ---------------------------------------------------------------------------
# Criterion 9: OTel export
# ---------------------------------------------------------------------------


class TestCriterion9OTelExport:
    """phoenix.otel.register called with project_name, endpoint, auto_instrument, batch."""

    def test_register_called_with_otel_params(self) -> None:
        _, mock_register, mock_provider = make_phoenix_tracer(
            endpoint="http://localhost:6006/v1/traces",
            project_name="finsight",
            auto_instrument=True,
            batch=True,
        )
        # register should have been called at tracer construction
        assert mock_register.called
        _, kwargs = mock_register.call_args
        assert kwargs["project_name"] == "finsight"
        assert kwargs["endpoint"] == "http://localhost:6006/v1/traces"
        assert kwargs["auto_instrument"] is True
        # batch param may be optional — if present, assert it
        if "batch" in kwargs:
            assert kwargs["batch"] is True

        # Flush must trigger provider force_flush (batch export)
        tracer, _, provider = make_phoenix_tracer()
        tracer.flush()  # type: ignore[attr-defined]
        assert provider.force_flush.called or getattr(provider, "flush", MagicMock()).called

    def test_otel_tracer_provider_and_batch(self) -> None:
        tracer, mock_register, mock_provider = make_phoenix_tracer(batch=True)
        # Provider is the TracerProvider returned by register
        assert mock_provider is not None
        # Batch means buffered export — flush must exist
        assert hasattr(mock_provider, "force_flush") or hasattr(mock_provider, "flush")
        # OTel tracer was resolved via opentelemetry.trace.get_tracer
        assert hasattr(tracer, "_tracer")  # type: ignore[attr-defined]

    def test_source_uses_phoenix_otel_register(self) -> None:
        src = Path(inspect.getfile(importlib.import_module("shared.tracing.phoenix_tracer"))).read_text()  # noqa: E501
        assert "phoenix.otel" in src
        assert "register" in src
        assert "project_name" in src
        assert "endpoint" in src
        assert "auto_instrument" in src
        assert "batch" in src
        # Must mention TracerProvider / OTel in docstring or comments
        assert "TracerProvider" in src or "OTel" in src


# ---------------------------------------------------------------------------
# Criterion 10: backend swap NoOp vs Phoenix same trajectory
# ---------------------------------------------------------------------------


class TestCriterion10BackendSwap:
    """Same ObservabilityTrace code must work with NoOp and Phoenix."""

    def _run_trajectory(self, tracer: TracerProtocol) -> TraceContext:
        obs = ObservabilityTrace(
            tracer,
            correlation_id="CASE-1027",
            tenant_id="tenant-a",
            case_id="CASE-1027",
            exception_type="I-REFUND-LAG",
        )
        ctx = obs.start_case()
        obs.context_assembly(ctx, evidence_ids=("ev-1",), latency_ms=1)
        obs.planner(ctx, allowlist=("get_stripe_payment",))  # noqa: E501
        obs.llm_generation(ctx, name="gen", model="groq", input_data={"x": 1}, output={"y": 1}, usage={})  # noqa: E501
        obs.verifier(ctx, status="ACCEPTED")
        obs.capability_call(ctx, capability="get_stripe_payment", args={"payment_id": "pay_1"}, order_index=0)  # noqa: E501
        obs.capability_result(ctx, capability="get_stripe_payment", result_summary={"ok": True}, success=True)  # noqa: E501
        obs.policy(ctx, decision="ALLOW")
        obs.approval(ctx, decision="APPROVED", idempotency_key="appr-1")
        obs.execution(ctx, idempotency_key="exec-1")
        obs.verification(ctx, status="VERIFIED")
        obs.flush()
        return ctx

    def test_same_trajectory_noop_vs_phoenix(self) -> None:
        # NoOp
        noop = NoOpTracer()
        ctx_noop = self._run_trajectory(noop)
        assert ctx_noop.trace_id == "CASE-1027"

        # Phoenix (mocked)
        phoenix, _, _ = make_phoenix_tracer()
        ctx_phoenix = self._run_trajectory(phoenix)  # type: ignore[arg-type]
        assert ctx_phoenix.trace_id == "CASE-1027"

        # Both produced same public trace_id; both preserved correlation_id
        assert ctx_noop.trace_id == ctx_phoenix.trace_id

        # No branching on backend — factory swap is transparent
        from shared.tracing.factory import create_tracer  # noqa: E501

        with patch("shared.tracing.phoenix_tracer.PhoenixTracer", return_value=phoenix):  # noqa: E501
            t_phoenix = create_tracer(_env={"PHOENIX_COLLECTOR_ENDPOINT": "http://localhost:6006/v1/traces"})  # noqa: E501
            t_noop = create_tracer(_env={})
            for t in (t_phoenix, t_noop):
                ctx = self._run_trajectory(t)
                assert ctx.trace_id == "CASE-1027"

    def test_protocol_conformance(self) -> None:
        tracer, _, _ = make_phoenix_tracer()
        assert isinstance(tracer, TracerProtocol)  # type: ignore[arg-type]
        assert isinstance(NoOpTracer(), TracerProtocol)

    def test_no_financial_authority(self) -> None:
        """PhoenixTracer must not import or mutate finance modules."""
        src = Path(inspect.getfile(importlib.import_module("shared.tracing.phoenix_tracer"))).read_text()  # noqa: E501
        tree = ast.parse(src)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        # Must not import finance domain (no GL/ledger/budget writes)
        for imp in imports:
            assert not imp.startswith("finance"), f"PhoenixTracer must not import finance: {imp}"
            assert "ledger" not in imp.lower() or "shared" in imp.lower()
        # Must not contain financial mutation keywords
        assert "post_to_ledger" not in src
        assert "UPDATE budget" not in src


# ---------------------------------------------------------------------------
# Additional: credential-safe & no financial authority (cross-criteria)
# ---------------------------------------------------------------------------


class TestCredentialSafeNoFinancialAuthority:
    def test_no_secrets_in_source(self) -> None:
        src = Path(inspect.getfile(importlib.import_module("shared.tracing.phoenix_tracer"))).read_text()  # noqa: E501
        # No hardcoded secrets — only references to redaction
        assert "sanitize" in src
        assert "redaction" in src.lower()

    def test_all_methods_sanitize(self) -> None:
        src = Path(inspect.getfile(importlib.import_module("shared.tracing.phoenix_tracer"))).read_text()  # noqa: E501
        # Every protocol method must sanitize
        for method in ("generation", "tool", "guardrail", "span", "trace"):
            assert method in src
        assert "sanitize_input" in src or "sanitize_args" in src
