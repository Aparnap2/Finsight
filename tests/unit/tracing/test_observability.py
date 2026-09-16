"""P5-08 observability: correlation_id, tenant-safe, no PII, 13-hop trace.

TDD RED: shared/tracing/correlation|redaction|observability must exist and
wire Planner+Executor+Verifier through TracerProtocol with NoOp fallback
and no unrestricted Gmail bodies.
"""

from __future__ import annotations

import hashlib

import pytest

from shared.tracing.correlation import (
    derive_correlation_id,
    from_fingerprint,
    from_s3_key,
    validate_correlation_id,
)
from shared.tracing.factory import create_tracer
from shared.tracing.noop import NoOpTracer
from shared.tracing.observability import ObservabilityTrace
from shared.tracing.protocol import TraceContext
from shared.tracing.redaction import (
    is_unrestricted_payload,
    sanitize_args,
    sanitize_input,
    sanitize_output,
)


# ---------------------------------------------------------------------------
# Correlation: tenant-safe derivation webhook → S3 → LLM → execution
# ---------------------------------------------------------------------------


class TestCorrelationTenantSafe:
    def test_validate_accepts_tenant_safe(self) -> None:
        assert validate_correlation_id("CASE-1027") == "CASE-1027"
        assert validate_correlation_id("tenant-a") == "tenant-a"

    def test_validate_rejects_pii_email(self) -> None:
        with pytest.raises(ValueError):
            validate_correlation_id("alice@example.com")

    def test_validate_rejects_space(self) -> None:
        with pytest.raises(ValueError):
            validate_correlation_id("CASE 1027")

    def test_from_fingerprint_is_tenant_safe(self) -> None:
        fp = hashlib.sha256(b"raw webhook body").hexdigest()
        cid = from_fingerprint(fp)
        assert cid == fp
        assert validate_correlation_id(cid) == fp

    def test_from_fingerprint_rejects_malformed(self) -> None:
        with pytest.raises(ValueError):
            from_fingerprint("not-hex")

    def test_from_s3_key_extracts_case(self) -> None:
        assert from_s3_key("tenant-a/CASE-1027/batch.csv") == "CASE-1027"
        assert from_s3_key("tenant-a/CASE-1027") == "CASE-1027"

    def test_from_s3_key_rejects_no_tenant(self) -> None:
        with pytest.raises(ValueError):
            from_s3_key("no-prefix.csv")

    def test_derive_precedence_exception_over_s3(self) -> None:
        fp = hashlib.sha256(b"x").hexdigest()
        cid = derive_correlation_id(
            fingerprint=fp,
            s3_key="tenant-a/CASE-1027/file.csv",
            exception_id="CASE-1027",
        )
        assert cid == "CASE-1027"

    def test_derive_mismatch_s3_vs_exception(self) -> None:
        with pytest.raises(ValueError):
            derive_correlation_id(
                s3_key="tenant-a/CASE-999/file.csv",
                exception_id="CASE-1027",
            )

    def test_derive_requires_at_least_one(self) -> None:
        with pytest.raises(ValueError):
            derive_correlation_id()


# ---------------------------------------------------------------------------
# Redaction: no unrestricted Gmail/Sheets bodies in traces
# ---------------------------------------------------------------------------


class TestRedaction:
    def test_sanitize_gmail_body_redacted(self) -> None:
        args = {"query": "refund", "body": "Dear Alice, invoice 123 ... alice@example.com"}
        sanitized = sanitize_args(args, capability="search_gmail")
        assert sanitized["body"] == "[REDACTED Gmail body]"
        assert sanitized["query"] == "refund"

    def test_sanitize_email_redacted(self) -> None:
        data = {"snippet": "Contact alice@example.com for details"}
        sanitized = sanitize_input(data)
        assert "[REDACTED_EMAIL]" in sanitized["snippet"]

    def test_sanitize_secret_redacted(self) -> None:
        data = {"api_key": "sk-live-123", "other": "ok"}
        sanitized = sanitize_input(data)
        assert sanitized["api_key"] == "[REDACTED_SECRET]"

    def test_is_unrestricted_false_for_redacted(self) -> None:
        assert is_unrestricted_payload({"gmail_body": "[REDACTED sensitive payload]"}) is False

    def test_is_unrestricted_true_for_raw_body(self) -> None:
        long_body = "a" * 1200 + " alice@example.com "
        assert is_unrestricted_payload({"gmail_body": long_body}) is True

    def test_sanitize_output_drops_gmail_body(self) -> None:
        out = {"gmail_body": "huge body" * 500, "success": True}
        sanitized = sanitize_output(out)
        assert sanitized["gmail_body"] == "[REDACTED sensitive payload]"

    def test_sanitize_truncates_long(self) -> None:
        long_val = "x" * 5000
        sanitized = sanitize_input({"hypothesis_text": long_val})
        assert len(sanitized["hypothesis_text"]) <= 501


# ---------------------------------------------------------------------------
# Observability facade: 13-hop trace via TracerProtocol, tenant-safe, no PII
# ---------------------------------------------------------------------------


class TestObservabilityTraceNoOp:
    def test_start_case_returns_trace_context(self) -> None:
        tracer = create_tracer(_env={})
        obs = ObservabilityTrace(
            tracer,
            correlation_id="CASE-1027",
            tenant_id="tenant-a",
            case_id="CASE-1027",
            exception_type="I-REFUND-LAG",
        )
        ctx = obs.start_case()
        assert isinstance(ctx, TraceContext)
        assert ctx.trace_id  # NoOp uses case_id as trace_id

    def test_full_trace_no_unrestricted_payload(self) -> None:
        # Use recording tracer to capture sanitized payloads
        class RecordingTracer:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            def trace(self, exception_id, tenant_id, exception_type):
                return TraceContext(trace_id=exception_id, _ref=None)

            def generation(self, ctx, name, model, input_data, output, usage, metadata=None):
                self.calls.append({"kind": "generation", "input": input_data, "output": output})
                assert not is_unrestricted_payload(input_data)
                assert not is_unrestricted_payload(output)

            def tool(self, ctx, name, input_data, output, metadata=None):
                self.calls.append({"kind": "tool", "input": input_data, "output": output})
                assert not is_unrestricted_payload(input_data)
                assert not is_unrestricted_payload(output)

            def guardrail(self, ctx, stage, input_data, output, passed, reasons, metadata=None):
                self.calls.append({"kind": "guardrail", "input": input_data})
                assert not is_unrestricted_payload(input_data)

            def span(self, ctx, name, input_data, output, metadata=None):
                self.calls.append({"kind": "span", "name": name, "input": input_data})
                assert not is_unrestricted_payload(input_data)

            def flush(self):
                pass

        tracer = RecordingTracer()
        obs = ObservabilityTrace(
            tracer,  # type: ignore[arg-type]
            correlation_id="CASE-1027",
            tenant_id="tenant-a",
            case_id="CASE-1027",
            exception_type="I-REFUND-LAG",
        )
        ctx = obs.start_case()
        obs.context_assembly(ctx, evidence_ids=("ev-1", "ev-2"), latency_ms=5, status="ok")
        obs.planner(ctx, evidence_ids=("ev-1",), allowlist=("get_stripe_payment",))
        obs.llm_generation(
            ctx,
            name="planner_llm",
            model="groq",
            input_data={"hypothesis_text": "candidate with alice@example.com", "gmail_body": "huge"},
            output={"hypothesis_text": "ok", "evidence_required": ["ev-1"]},
            usage={},
        )
        obs.verifier(ctx, status="ACCEPTED", reason_codes=())
        obs.capability_call(ctx, capability="search_gmail", args={"query": "refund", "body": "secret"}, order_index=0)
        obs.capability_result(ctx, capability="search_gmail", result_summary={"row_count": 1}, success=True)
        obs.replan(ctx, attempt=1, reason_codes=("grounding_violation",))
        obs.final_candidate(ctx, hypothesis_ref="hypo", evidence_required=("ev-1",))
        obs.policy(ctx, decision="ALLOW")
        obs.approval(ctx, decision="APPROVED", approver_ref="approver-1", idempotency_key="appr-1234567890123456")
        obs.execution(ctx, idempotency_key="exec-1234567890123456", status="executed")
        obs.verification(ctx, status="VERIFIED")
        obs.flush()
        # Every span should be tenant-safe and not contain raw Gmail body
        for call in tracer.calls:
            for payload in (call.get("input"), call.get("output")):
                if isinstance(payload, dict):
                    for v in payload.values():
                        if isinstance(v, str):
                            assert "alice@example.com" not in v
                            assert "huge" not in v or "[REDACTED" in v

    def test_tenant_safe_ids_only(self) -> None:
        tracer = NoOpTracer()
        obs = ObservabilityTrace(tracer, correlation_id="CASE-1027", tenant_id="tenant-a", case_id="CASE-1027", exception_type="I-REFUND-LAG")
        ctx = obs.start_case()
        # Should not raise when ids are tenant-safe
        obs.context_assembly(ctx, evidence_ids=("ev-1",), status="ok")

    def test_noop_tracer_when_langfuse_unset(self) -> None:
        tracer = create_tracer(_env={})
        assert isinstance(tracer, NoOpTracer)
        # Flow completes with no network
        obs = ObservabilityTrace(tracer, correlation_id="CASE-1027", tenant_id="tenant-a", case_id="CASE-1027", exception_type="I-REFUND-LAG")
        ctx = obs.start_case()
        obs.verification(ctx, status="VERIFIED")
        tracer.flush()  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Wiring: Planner+Executor+Verifier through TracerProtocol (no Gmail bodies)
# ---------------------------------------------------------------------------


class TestWiringThroughTracer:
    def test_planner_emits_sanitized_generation(self) -> None:
        from agents.investigation.plan import InvestigationPlan
        from agents.investigation.planner import Planner
        from agents.investigation.request import InvestigationRequest
        from shared.llm.fake import FakeLLM

        class CaptureTracer:
            def __init__(self):
                self.gens: list[dict] = []

            def trace(self, exception_id, tenant_id, exception_type):
                return TraceContext(trace_id=exception_id, _ref=None)

            def generation(self, ctx, name, model, input_data, output, usage, metadata=None):
                self.gens.append({"input": input_data, "output": output})
                assert not is_unrestricted_payload(input_data)

            def span(self, ctx, name, input_data, output, metadata=None):
                assert not is_unrestricted_payload(input_data)

            def tool(self, ctx, name, input_data, output, metadata=None):
                pass

            def guardrail(self, ctx, stage, input_data, output, passed, reasons, metadata=None):
                pass

            def flush(self):
                pass

        tracer = CaptureTracer()
        fake = FakeLLM(
            scripted={
                "InvestigationPlan": {
                    "hypothesis_text": "candidate hypothesis with alice@example.com",
                    "capability_calls": [
                        {"capability": "get_stripe_payment", "args": {"payment_id": "pay_1"}, "order_index": 0}
                    ],
                    "evidence_required": ["ev-1"],
                    "escalation": False,
                }
            }
        )
        planner = Planner(fake, tracer=tracer)  # type: ignore[arg-type]
        req = InvestigationRequest(
            exception_id="CASE-1027",
            exception_type="I-REFUND-LAG",
            tenant_id="tenant-a",
            actor="analyst",
            evidence_ids=("ev-1",),
            capability_allowlist=("get_stripe_payment",),
        )
        ctx = tracer.trace("CASE-1027", "tenant-a", "I-REFUND-LAG")
        plan = planner.plan(req, ctx)  # type: ignore[call-arg]
        assert isinstance(plan, InvestigationPlan)
        # Generation should have been sanitized (email redacted) — input is sanitized
        for g in tracer.gens:
            for v in g["input"].values():
                if isinstance(v, str):
                    assert "alice@example.com" not in v

    def test_executor_emits_sanitized_tool(self) -> None:
        from agents.capabilities.capabilities import AdapterBundle
        from agents.capabilities.executor import CapabilityExecutor
        from agents.investigation.plan import CapabilityCall, InvestigationPlan
        from finance.accounting.mock import MockQuickBooksAdapter
        from finance.reconciliation.ledger_resolution import InMemoryLedgerRepository

        class CaptureTracer:
            def __init__(self):
                self.tools: list[dict] = []

            def trace(self, exception_id, tenant_id, exception_type):
                return TraceContext(trace_id=exception_id, _ref=None)

            def generation(self, ctx, name, model, input_data, output, usage, metadata=None):
                pass

            def tool(self, ctx, name, input_data, output, metadata=None):
                self.tools.append({"name": name, "input": input_data})
                assert not is_unrestricted_payload(input_data)
                if "search_gmail" in name:
                    for v in input_data.values():
                        if isinstance(v, str):
                            assert "[REDACTED" in v or "body" not in v.lower() or v != "secret body"

            def span(self, ctx, name, input_data, output, metadata=None):
                pass

            def guardrail(self, ctx, stage, input_data, output, passed, reasons, metadata=None):
                pass

            def flush(self):
                pass

        tracer = CaptureTracer()
        bundle = AdapterBundle(
            gmail_corpus={"tenant-a": [{"message_id": "m1", "subject": "hi", "body": "secret body with alice@example.com"}]},
            qb_adapter=MockQuickBooksAdapter(),
            ledger_repository=InMemoryLedgerRepository(),
        )
        executor = CapabilityExecutor(bundle, tracer=tracer)  # type: ignore[arg-type]
        plan = InvestigationPlan(
            hypothesis_text="hypo",
            capability_calls=(CapabilityCall(capability="search_gmail", args={"query": "hi"}, order_index=0),),
            evidence_required=("ev-1",),
            escalation=False,
        )
        ctx = tracer.trace("CASE-1027", "tenant-a", "I-REFUND-LAG")
        outcomes = executor.execute(plan, "tenant-a", ctx)  # type: ignore[call-arg]
        assert len(outcomes) == 1
        # First tool call is capability:search_gmail with sanitized query
        assert any(
            t["name"] == "capability:search_gmail" and t["input"].get("query") == "hi"
            for t in tracer.tools
        )

    def test_verifier_emits_guardrail_without_pii(self) -> None:
        from agents.investigation.plan import CapabilityCall, InvestigationPlan
        from agents.verification.verifier import Verifier

        class CaptureTracer:
            def __init__(self):
                self.guardrails: list[dict] = []

            def trace(self, exception_id, tenant_id, exception_type):
                return TraceContext(trace_id=exception_id, _ref=None)

            def generation(self, ctx, name, model, input_data, output, usage, metadata=None):
                pass

            def tool(self, ctx, name, input_data, output, metadata=None):
                pass

            def span(self, ctx, name, input_data, output, metadata=None):
                pass

            def guardrail(self, ctx, stage, input_data, output, passed, reasons, metadata=None):
                self.guardrails.append({"input": input_data, "output": output})
                assert not is_unrestricted_payload(input_data)

            def flush(self):
                pass

        tracer = CaptureTracer()
        verifier = Verifier(tracer=tracer)  # type: ignore[arg-type]
        plan = InvestigationPlan(
            hypothesis_text="candidate",
            capability_calls=(CapabilityCall(capability="get_stripe_payment", args={"payment_id": "pay_1"}, order_index=0),),
            evidence_required=("ev-1",),
            escalation=False,
        )
        ctx = tracer.trace("CASE-1027", "tenant-a", "I-REFUND-LAG")
        verdict = verifier.verify(plan, ("ev-1",), 0, ctx)  # type: ignore[call-arg]
        assert verdict.status == "ACCEPTED"
        assert len(tracer.guardrails) == 1

    def test_orchestrator_full_trace_queryable_by_correlation(self) -> None:
        from agents.capabilities.capabilities import AdapterBundle
        from agents.capabilities.executor import CapabilityExecutor
        from agents.investigation.request import InvestigationRequest
        from agents.orchestrator.orchestrator import InvestigateOrchestrator
        from agents.verification.verifier import Verifier
        from finance.accounting.mock import MockQuickBooksAdapter
        from finance.reconciliation.ledger_resolution import InMemoryLedgerRepository
        from shared.llm.fake import FakeLLM

        class RecordingTracer:
            def __init__(self):
                self.spans: list[str] = []

            def trace(self, exception_id, tenant_id, exception_type):
                self.spans.append(f"trace:{exception_id}")
                return TraceContext(trace_id=exception_id, _ref=None)

            def span(self, ctx, name, input_data, output, metadata=None):
                self.spans.append(name)

            def generation(self, ctx, name, model, input_data, output, usage, metadata=None):
                self.spans.append(f"gen:{name}")

            def guardrail(self, ctx, stage, input_data, output, passed, reasons, metadata=None):
                self.spans.append(f"guard:{stage}")

            def tool(self, ctx, name, input_data, output, metadata=None):
                self.spans.append(f"tool:{name}")

            def flush(self):
                pass

        tracer = RecordingTracer()
        fake = FakeLLM(
            scripted={
                "InvestigationPlan": {
                    "hypothesis_text": "hypo",
                    "capability_calls": [
                        {"capability": "get_stripe_payment", "args": {"payment_id": "pay_1"}, "order_index": 0}
                    ],
                    "evidence_required": ["ev-1"],
                    "escalation": False,
                }
            }
        )
        bundle = AdapterBundle(
            qb_adapter=MockQuickBooksAdapter(),
            ledger_repository=InMemoryLedgerRepository(),
        )
        executor = CapabilityExecutor(bundle, tracer=tracer)  # type: ignore[arg-type]
        verifier = Verifier(tracer=tracer)  # type: ignore[arg-type]
        orch = InvestigateOrchestrator(fake, executor, verifier, tracer=tracer)  # type: ignore[arg-type]
        req = InvestigationRequest(
            exception_id="CASE-1027",
            exception_type="I-REFUND-LAG",
            tenant_id="tenant-a",
            actor="analyst",
            evidence_ids=("ev-1",),
            capability_allowlist=("get_stripe_payment",),
        )
        # Derive correlation from s3_key (tenant-a/CASE-1027/file)
        result = orch.run(req, "tenant-a", correlation_id="CASE-1027", s3_key="tenant-a/CASE-1027/batch.csv")
        assert result.request_id == "CASE-1027"
        # Correlation_id trace should contain hops
        assert any("trace:CASE-1027" in s for s in tracer.spans)
        assert any("planner" in s for s in tracer.spans)
