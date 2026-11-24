"""Behavioural tests for the API error contract (Stage 1).

The contract has three parts and each is tested at the level it actually
behaves at:

* :mod:`shared.errors.catalog` — the registry. Tested for structural
  invariants (every code classified, statuses sane, retryability factual).
* :func:`apps.api.errors.build_error_body` — the derivation. Tested for the
  compatibility guarantee that ``detail`` is echoed verbatim and the
  ``error`` object agrees with the registry.
* The mounted handlers — tested end-to-end through a real FastAPI app so a
  regression in registration, not just in a helper, is caught.

Expected values are written out explicitly rather than recomputed from the
production helpers, so a bug in the helper cannot become the expectation.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from apps.api.errors import (
    GENERIC_INTERNAL_MESSAGE,
    ApiError,
    build_error_body,
    register_error_handlers,
)
from shared.errors import (
    REGISTRY,
    ErrorCategory,
    ErrorCode,
    code_for_status,
    is_retryable,
    spec_for,
)


def _request(
    *,
    request_id: str = "",
    correlation_id: str = "",
    headers: dict[str, str] | None = None,
) -> Request:
    """Build a minimal HTTP ``Request`` with optional pre-set IDs."""
    raw_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in (headers or {}).items()
    ]
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/probe",
        "headers": raw_headers,
        "query_string": b"",
        "state": {"request_id": request_id, "correlation_id": correlation_id},
    }
    return Request(scope)


class TestRegistryInvariants:
    """The registry must classify every code, with no silent gaps."""

    def test_every_code_is_registered(self) -> None:
        missing = [code for code in ErrorCode if code not in REGISTRY]
        assert missing == []

    def test_registry_keys_match_their_codes(self) -> None:
        # A code must be its own key: iterate the mapping, not the enum, so an
        # aliased enum member cannot hide behind the wrong key.
        assert {code.value for code in REGISTRY} == {code.value for code in ErrorCode}

    def test_no_aliased_codes(self) -> None:
        """Duplicate values would collapse two codes into one silently."""
        assert len(ErrorCode.__members__) == len(list(ErrorCode))

    @pytest.mark.parametrize("code", list(ErrorCode))
    def test_http_status_is_a_client_or_server_error(self, code: ErrorCode) -> None:
        status = spec_for(code).http_status
        assert 400 <= status <= 599, f"{code} has non-error status {status}"

    @pytest.mark.parametrize("code", list(ErrorCode))
    def test_every_category_has_an_owner(self, code: ErrorCode) -> None:
        spec = spec_for(code)
        assert spec.owner, f"{code} has no owner"
        assert spec.category in ErrorCategory

    @pytest.mark.parametrize("code", list(ErrorCode))
    def test_every_code_has_recovery_guidance(self, code: ErrorCode) -> None:
        assert spec_for(code).recovery.strip(), f"{code} has no recovery guidance"

    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            (ErrorCode.VALIDATION_FAILED, False),
            (ErrorCode.IDEMPOTENCY_CONFLICT, False),
            (ErrorCode.DUPLICATE_DECISION, False),
            (ErrorCode.ILLEGAL_TRANSITION, False),
            (ErrorCode.STATE_VERSION_CONFLICT, True),
            (ErrorCode.PERSISTENCE_UNAVAILABLE, True),
            (ErrorCode.SERVICE_UNAVAILABLE, True),
            (ErrorCode.GATEWAY_TIMEOUT, True),
            (ErrorCode.RATE_LIMITED, True),
            (ErrorCode.BUDGET_EXHAUSTED, True),
            (ErrorCode.PROVIDER_TIMEOUT, True),
            (ErrorCode.PROVIDER_UNAVAILABLE, True),
            (ErrorCode.PROVIDER_AUTH, False),
        ],
    )
    def test_retryability_is_explicit(self, code: ErrorCode, expected: bool) -> None:
        """Retryability is a safety claim, so pin the ones that matter."""
        assert is_retryable(code) is expected


class TestStatusFallback:
    """A status without an explicit code still yields a classified code."""

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (400, ErrorCode.BAD_REQUEST),
            (401, ErrorCode.UNAUTHORIZED),
            (403, ErrorCode.FORBIDDEN),
            (404, ErrorCode.RESOURCE_NOT_FOUND),
            (405, ErrorCode.METHOD_NOT_ALLOWED),
            (409, ErrorCode.CONFLICT),
            (413, ErrorCode.PAYLOAD_TOO_LARGE),
            (422, ErrorCode.VALIDATION_FAILED),
            (429, ErrorCode.RATE_LIMITED),
            (500, ErrorCode.INTERNAL_ERROR),
            (503, ErrorCode.SERVICE_UNAVAILABLE),
            (504, ErrorCode.GATEWAY_TIMEOUT),
        ],
    )
    def test_known_status_maps_to_its_code(self, status: int, expected: ErrorCode) -> None:
        assert code_for_status(status) is expected

    def test_unknown_4xx_falls_back_to_bad_request(self) -> None:
        assert code_for_status(418) is ErrorCode.BAD_REQUEST

    def test_unknown_5xx_falls_back_to_internal_error(self) -> None:
        assert code_for_status(599) is ErrorCode.INTERNAL_ERROR

    def test_fallback_status_agrees_with_registry(self) -> None:
        """The status that produced a code must match that code's own status."""
        for status in (400, 401, 403, 404, 405, 409, 413, 422, 429, 500, 503, 504):
            assert spec_for(code_for_status(status)).http_status == status


class TestBuildErrorBody:
    """The body is derived from the registry and preserves ``detail``."""

    def test_detail_is_echoed_verbatim_for_a_string(self) -> None:
        body = build_error_body(
            code=ErrorCode.CONFLICT,
            legacy_detail="Idempotency conflict.",
            request=_request(request_id="rid", correlation_id="cid"),
        )
        assert body["detail"] == "Idempotency conflict."

    def test_detail_is_echoed_verbatim_for_a_structured_payload(self) -> None:
        errors = [{"loc": ["body", "amount"], "msg": "field required"}]
        body = build_error_body(
            code=ErrorCode.VALIDATION_FAILED,
            legacy_detail=errors,
            request=_request(),
            message="1 field(s) failed validation.",
        )
        assert body["detail"] == errors

    def test_error_object_agrees_with_registry(self) -> None:
        body = build_error_body(
            code=ErrorCode.PERSISTENCE_UNAVAILABLE,
            legacy_detail="Database unavailable.",
            request=_request(),
        )
        error = body["error"]
        assert error["code"] == "PERSISTENCE_UNAVAILABLE"
        assert error["category"] == "infrastructure"
        assert error["retryable"] is True

    def test_ids_come_from_request_state(self) -> None:
        body = build_error_body(
            code=ErrorCode.BAD_REQUEST,
            legacy_detail="Bad.",
            request=_request(request_id="rid-1", correlation_id="cid-1"),
        )
        assert body["request_id"] == "rid-1"
        assert body["correlation_id"] == "cid-1"

    def test_ids_fall_back_to_headers_when_state_is_empty(self) -> None:
        body = build_error_body(
            code=ErrorCode.BAD_REQUEST,
            legacy_detail="Bad.",
            request=_request(headers={"X-Request-ID": "hdr-rid", "X-Correlation-ID": "hdr-cid"}),
        )
        assert body["request_id"] == "hdr-rid"
        assert body["correlation_id"] == "hdr-cid"

    def test_message_defaults_to_detail_text(self) -> None:
        body = build_error_body(
            code=ErrorCode.RESOURCE_NOT_FOUND,
            legacy_detail="Run not found.",
            request=_request(),
        )
        assert body["error"]["message"] == "Run not found."

    def test_explicit_message_overrides_detail(self) -> None:
        body = build_error_body(
            code=ErrorCode.FORBIDDEN,
            legacy_detail="Unknown role: ceo",
            request=_request(),
            message="Insufficient permissions for this action.",
        )
        assert body["detail"] == "Unknown role: ceo"
        assert body["error"]["message"] == "Insufficient permissions for this action."

    def test_details_payload_is_passed_through(self) -> None:
        body = build_error_body(
            code=ErrorCode.VALIDATION_FAILED,
            legacy_detail="bad",
            request=_request(),
            details={"errors": [{"field": "amount"}]},
        )
        assert body["error"]["details"] == {"errors": [{"field": "amount"}]}


def _app_raising(handler: Any) -> FastAPI:
    """Mount ``handler`` at ``/boom`` with the real error handlers installed."""
    app = FastAPI()
    register_error_handlers(app)
    app.add_api_route("/boom", handler, methods=["GET"])
    return app


class TestMountedHandlers:
    """Registration, not just the helper, must produce the contract."""

    def test_typed_error_keeps_its_code_and_status(self) -> None:
        async def boom() -> None:
            raise ApiError(
                status_code=409,
                detail="Idempotency conflict.",
                code=ErrorCode.IDEMPOTENCY_CONFLICT,
            )

        response = TestClient(_app_raising(boom)).get("/boom")
        assert response.status_code == 409
        body = response.json()
        assert body["detail"] == "Idempotency conflict."
        assert body["error"]["code"] == "IDEMPOTENCY_CONFLICT"
        assert body["error"]["retryable"] is False

    def test_bare_http_exception_gets_status_derived_code(self) -> None:
        async def boom() -> None:
            raise HTTPException(status_code=409, detail="Some conflict")

        response = TestClient(_app_raising(boom)).get("/boom")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONFLICT"

    def test_unhandled_exception_is_generic_and_leaks_nothing(self) -> None:
        async def boom() -> None:
            raise RuntimeError("password=hunter2 host=db.internal")

        client = TestClient(_app_raising(boom), raise_server_exceptions=False)
        response = client.get("/boom")
        assert response.status_code == 500
        body = response.json()
        assert body["error"]["code"] == "INTERNAL_ERROR"
        assert body["detail"] == GENERIC_INTERNAL_MESSAGE
        assert "hunter2" not in response.text
        assert "db.internal" not in response.text
        assert "RuntimeError" not in response.text

    def test_response_headers_carry_the_ids(self) -> None:
        async def boom() -> None:
            raise HTTPException(status_code=400, detail="Bad.")

        response = TestClient(_app_raising(boom)).get("/boom")
        body = response.json()
        assert response.headers["X-Request-ID"] == body["request_id"]
        assert response.headers["X-Correlation-ID"] == body["correlation_id"]
        assert body["request_id"]  # never empty

    def test_metamorphic_detail_is_stable_across_requests(self) -> None:
        """Two identical failures differ only in correlation, never in detail."""

        async def boom() -> None:
            raise ApiError(status_code=400, detail="Stable text.", code=ErrorCode.BAD_REQUEST)

        client = TestClient(_app_raising(boom))
        first = client.get("/boom").json()
        second = client.get("/boom").json()
        assert first["detail"] == second["detail"] == "Stable text."
        assert first["error"] == second["error"]


class TestMainAppWiring:
    """The production app must actually install the contract."""

    def test_main_app_registers_both_handlers(self) -> None:
        from starlette.exceptions import HTTPException as StarletteHTTPException

        from apps.api.main import app

        assert StarletteHTTPException in app.exception_handlers
        assert Exception in app.exception_handlers

    def test_unauthenticated_request_returns_the_envelope(self) -> None:
        from apps.api.main import app

        response = TestClient(app).get("/api/v1/runs/does-not-exist/matches")
        assert response.status_code == 401
        body = response.json()
        assert body["error"]["code"] == "TENANT_CONTEXT_MISSING"
        assert body["detail"] == "Missing X-Tenant-ID or X-Role header"
        assert body["correlation_id"]
        assert response.headers["X-Correlation-ID"] == body["correlation_id"]

    def test_health_endpoint_stays_ungated(self) -> None:
        from apps.api.main import app

        assert TestClient(app).get("/live").status_code == 200


class TestSingleSourceOfTruth:
    """Ingestion must borrow the registry, not maintain a second copy."""

    def test_every_registered_code_is_documented(self) -> None:
        """The catalog is normative; an undocumented code is drift."""
        from pathlib import Path

        doc = Path(__file__).resolve().parents[3] / "docs" / "specs" / "ERROR_CATALOG.md"
        text = doc.read_text(encoding="utf-8")
        undocumented = [code.value for code in ErrorCode if f"`{code.value}`" not in text]
        assert undocumented == []

    def test_ingestion_error_codes_are_registry_codes(self) -> None:
        from finance.source_ingestion.issues import ApiErrorCode, IngestionError

        assert ApiErrorCode is ErrorCode
        error = IngestionError(ErrorCode.INVALID_SCHEMA, "bad headers")
        assert isinstance(error.code, ErrorCode)
        assert error.code in REGISTRY

    def test_ingestion_rejects_a_code_outside_the_registry(self) -> None:
        from finance.source_ingestion.issues import IngestionError

        with pytest.raises(TypeError):
            IngestionError("INVALID_SCHEMA", "bad headers")  # type: ignore[arg-type]
