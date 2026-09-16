"""Stripe webhook ingestion boundary: verify -> tenant -> persist -> ack.

Commit 2 owns the transport edge ONLY. The exact flow is:

1. Read the raw HTTP body FIRST via ``await request.body()`` (never
   JSON-parse before HMAC verification).
2. HMAC-SHA256 verify over the raw bytes (``t=<ts>.<raw>``, 300s symmetric
   tolerance). Missing/invalid/expired signatures are rejected with 400/401
   and no database write.
3. Parse and validate the envelope (``id`` + ``type`` required). Malformed
   envelopes are rejected with 400 and no database write.
4. Resolve the tenant through the explicit trusted ``stripe_account ->
   tenant_id`` map (env-only, ``STRIPE_TENANT_MAP``). There is NO default
   tenant: unknown or ambiguous accounts are quarantined (persisted under the
   ``UNROUTABLE`` sentinel with ``IGNORED`` status) and answered 404/400.
5. Compute the sha256 payload fingerprint over the raw bytes, set the tenant
   RLS context, then INSERT the immutable envelope via
   ``shared.webhook_repository.insert_or_get_duplicate`` (Postgres UNIQUE on
   ``(provider, event_id)`` is the ONLY idempotency mechanism — no in-memory
   state) and COMMIT before any downstream work.
6. Branch on the outcome: exact duplicate -> 200 OK no-op (no reprocessing);
   same ``(provider, event_id)`` with a different fingerprint -> 409
   Conflict + audit with no mutation; valid new envelope -> 202 Accepted.
   Database failures answer non-2xx so Stripe retries.

This route contains ZERO reconciliation, LLM, or QuickBooks logic, and
persists BEFORE any downstream processing (downstream is out of scope).
"""

import hashlib
import hmac
import json
import logging
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from shared.config import get_settings
from shared.models.database import AuditLog
from shared.webhook_repository import insert_or_get_duplicate

logger = logging.getLogger(__name__)

router = APIRouter()

SIGNATURE_TOLERANCE_SECONDS = 300

UNROUTABLE_TENANT = "UNROUTABLE"

STATUS_RECEIVED = "RECEIVED"
STATUS_IGNORED = "IGNORED"


class SignatureError(ValueError):
    """Raised when a webhook signature is missing, malformed, or invalid."""

    def __init__(self, reason: Literal["missing", "malformed", "mismatch", "expired"],
                 detail: str) -> None:
        """Record the machine-readable reason alongside the message."""
        self.reason = reason
        super().__init__(detail)


class EnvelopeError(ValueError):
    """Raised when the verified body is not a well-formed webhook envelope."""


@dataclass(frozen=True)
class TenantResolution:
    """Outcome of resolving an envelope to a tenant via the trusted map."""

    outcome: Literal["resolved", "unknown", "ambiguous"]
    tenant_id: str | None
    stripe_account: str | None


def verify_stripe_signature(
    payload: bytes,
    header: str | None,
    secret: str,
    now: int,
    tolerance: int = SIGNATURE_TOLERANCE_SECONDS,
) -> int:
    """Verify a Stripe-style signature header over the raw body bytes.

    Args:
        payload: Verbatim request body bytes (signing input, never re-encoded).
        header: Value of the ``Stripe-Signature`` header
            (``t=<unix_seconds>,v1=<hex>[,v1=<hex>...]``).
        secret: Endpoint webhook secret (env-only).
        now: Current unix time in seconds (injected for testability).
        tolerance: Symmetric clock-skew window in seconds (default 300).

    Returns:
        The embedded signature timestamp.

    Raises:
        SignatureError: Missing header (``missing``), unparseable header
            (``malformed``), digest mismatch such as a one-byte body mutation
            or wrong secret (``mismatch``), or ``|now - t| > tolerance``
            (``expired``, covering past and future skew).
    """
    if header is None or not header.strip():
        raise SignatureError("missing", "Missing Stripe-Signature header.")
    timestamp: int | None = None
    signatures: list[str] = []
    for part in header.split(","):
        item = part.strip()
        if item.startswith("t="):
            try:
                timestamp = int(item[2:])
            except ValueError as exc:
                raise SignatureError(
                    "malformed", "Malformed timestamp in signature header."
                ) from exc
        elif item.startswith("v1="):
            signatures.append(item[3:])
    if timestamp is None:
        raise SignatureError("malformed", "Malformed signature header: missing t=.")
    if not signatures:
        raise SignatureError("malformed", "Malformed signature header: missing v1=.")
    signed = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise SignatureError("mismatch", "Signature mismatch.")
    if abs(now - timestamp) > tolerance:
        raise SignatureError(
            "expired",
            f"Timestamp outside tolerance: skew={abs(now - timestamp)}s "
            f"exceeds {tolerance}s.",
        )
    return timestamp


def build_signature_header(payload: bytes, secret: str, timestamp: int) -> str:
    """Build a Stripe-style signature header (used by tests and tooling)."""
    signed = f"{timestamp}.".encode() + payload
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def parse_envelope(raw: bytes) -> dict[str, Any]:
    """Parse the verified body into a strict webhook envelope.

    Args:
        raw: Already signature-verified body bytes.

    Returns:
        The decoded envelope mapping (must carry non-empty ``id``/``type``).

    Raises:
        EnvelopeError: Body is not UTF-8 JSON, not an object, or lacks the
            required ``id``/``type`` string identifiers.
    """
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EnvelopeError(f"Body is not valid JSON: {exc}.") from exc
    if not isinstance(decoded, dict):
        raise EnvelopeError(f"Envelope must be a JSON object, got {type(decoded).__name__}.")
    for field_name in ("id", "type"):
        value = decoded.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise EnvelopeError(f"Field '{field_name}' must be a non-empty string.")
    return decoded


def resolve_tenant(
    envelope: Mapping[str, Any], mapping: Mapping[str, object]
) -> TenantResolution:
    """Resolve an envelope to a tenant through the explicit trusted map.

    The Stripe connected-account id is read from the top-level ``account``
    field (falling back to ``data.object.account``). Resolution NEVER falls
    back to a default tenant.

    Args:
        envelope: Verified, parsed webhook envelope.
        mapping: Trusted ``stripe_account -> tenant_id`` map (env-only).

    Returns:
        ``resolved`` with the tenant id; ``unknown`` when no account is
        present or the account is absent from the map; ``ambiguous`` when
        envelope candidates disagree or the map entry names several tenants.
    """
    nested: Any = envelope.get("data")
    nested_account: Any = None
    if isinstance(nested, dict):
        inner: Any = nested.get("object")
        if isinstance(inner, dict):
            nested_account = inner.get("account")
    candidates = {
        value.strip()
        for value in (envelope.get("account"), nested_account)
        if isinstance(value, str) and value.strip()
    }
    if len(candidates) > 1:
        logger.warning("Ambiguous tenant: conflicting accounts %s.", sorted(candidates))
        return TenantResolution(outcome="ambiguous", tenant_id=None, stripe_account=None)
    account = next(iter(candidates), None)
    if account is None:
        logger.warning("Unknown tenant: envelope carries no stripe account.")
        return TenantResolution(outcome="unknown", tenant_id=None, stripe_account=None)
    if account not in mapping:
        logger.warning("Unknown tenant: stripe account %s is not in the trusted map.", account)
        return TenantResolution(outcome="unknown", tenant_id=None, stripe_account=account)
    target = mapping[account]
    if isinstance(target, list):
        names = [item for item in target if isinstance(item, str) and item.strip()]
        if len(names) == 1:
            return TenantResolution(
                outcome="resolved", tenant_id=names[0], stripe_account=account
            )
        logger.warning("Ambiguous tenant: account %s maps to %d tenants.", account, len(names))
        return TenantResolution(outcome="ambiguous", tenant_id=None, stripe_account=account)
    if isinstance(target, str) and target.strip():
        return TenantResolution(
            outcome="resolved", tenant_id=target.strip(), stripe_account=account
        )
    logger.warning("Ambiguous tenant: map entry for account %s is not usable.", account)
    return TenantResolution(outcome="ambiguous", tenant_id=None, stripe_account=account)


def _event_period(envelope: Mapping[str, Any]) -> str:
    """Derive an audit period (``YYYY-MM``) from the envelope or the clock."""
    created = envelope.get("created")
    if isinstance(created, int) and not isinstance(created, bool):
        try:
            return datetime.fromtimestamp(created, tz=UTC).strftime("%Y-%m")
        except (OverflowError, OSError, ValueError):
            logger.debug("Unusable envelope timestamp %r; using current month.", created)
    return datetime.now(UTC).strftime("%Y-%m")


def _audit(
    session: Session,
    *,
    tenant_id: str,
    event_type: str,
    event_data: dict[str, Any],
    period: str,
) -> None:
    """Append one audit row; never masks the webhook response on failure.

    P5-06: ``event_data`` is redacted via :func:`shared.safety.secrets
    .redact_mapping` before persistence — secret-keyed values collapse
    to ``[REDACTED]`` so API keys and tokens never reach the audit log.
    """
    try:
        from shared.safety.secrets import redact_mapping

        session.add(
            AuditLog(
                id=f"wh_audit_{uuid4().hex[:16]}",
                tenant_id=tenant_id,
                period=period,
                event_type=event_type,
                event_data=redact_mapping(dict(event_data)),
            )
        )
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        logger.exception("Webhook audit write failed event_type=%s.", event_type)


def _set_tenant_context(session: Session, tenant_id: str) -> None:
    """Set the Postgres RLS tenant context before persisting.

    ``set_config`` exists only on Postgres, so non-Postgres dialects (SQLite
    in unit tests) skip the call. On Postgres a failure propagates and the
    handler answers non-2xx rather than persisting without isolation.
    """
    try:
        dialect = session.get_bind().dialect.name  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 - unbound session: nothing to set
        logger.debug("No bind dialect available; skipping RLS tenant context.")
        return
    if dialect != "postgresql":
        logger.debug("Skipping RLS tenant context on dialect %s.", dialect)
        return
    session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": tenant_id},
    )


_engine: Engine | None = None


def get_db_session() -> Iterator[Session]:
    """Yield a request-scoped SQLAlchemy session (override in tests)."""
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().postgres_uri)
    with Session(_engine) as session:
        yield session


@router.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request, session: Session = Depends(get_db_session)  # noqa: B008
) -> JSONResponse:
    """Ingest one raw Stripe delivery: verify -> tenant -> persist -> ack."""
    raw = await request.body()
    settings = get_settings()
    secret = settings.stripe_webhook_secret
    if not secret:
        logger.error("STRIPE_WEBHOOK_SECRET is not configured; rejecting delivery.")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": "webhook_not_configured"},
        )

    try:
        verify_stripe_signature(
            raw, request.headers.get("stripe-signature"), secret, int(time.time())
        )
    except SignatureError as exc:
        logger.warning("Stripe signature rejected reason=%s.", exc.reason)
        code = 400 if exc.reason == "malformed" else 401
        return JSONResponse(
            status_code=code,
            content={"status": "rejected", "error": f"invalid_signature_{exc.reason}"},
        )

    try:
        envelope = parse_envelope(raw)
    except EnvelopeError as exc:
        logger.warning("Malformed Stripe envelope rejected: %s.", exc)
        return JSONResponse(
            status_code=400,
            content={"status": "rejected", "error": "malformed_envelope", "detail": str(exc)},
        )

    event_id = str(envelope["id"]).strip()
    event_type = str(envelope["type"]).strip()
    fingerprint = hashlib.sha256(raw).hexdigest()
    period = _event_period(envelope)

    resolution = resolve_tenant(envelope, settings.stripe_tenant_mapping)
    quarantined = resolution.outcome != "resolved"
    tenant_id = resolution.tenant_id if not quarantined else UNROUTABLE_TENANT
    assert tenant_id is not None  # resolved branch always carries a tenant id

    try:
        _set_tenant_context(session, tenant_id)
        event, created = insert_or_get_duplicate(
            session,
            tenant_id=tenant_id,
            provider="stripe",
            event_id=event_id,
            event_type=event_type,
            raw=envelope,
            fingerprint=fingerprint,
            status=STATUS_IGNORED if quarantined else STATUS_RECEIVED,
        )
    except (ValueError, SQLAlchemyError) as exc:
        session.rollback()
        logger.exception("Stripe persist failed event_id=%s.", event_id)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": "storage_failure", "detail": str(exc)},
        )

    if not created:
        stored = event.fingerprint
        if stored is not None and hmac.compare_digest(stored, fingerprint):
            logger.info("Duplicate Stripe delivery event_id=%s; no-op.", event_id)
            return JSONResponse(
                status_code=200,
                content={
                    "status": "duplicate",
                    "event_id": event_id,
                    "stored_status": event.status,
                },
            )
        logger.warning("Stripe idempotency conflict event_id=%s; no mutation.", event_id)
        _audit(
            session,
            tenant_id=event.tenant_id,
            event_type="IDEMPOTENCY_CONFLICT",
            event_data={
                "provider": "stripe",
                "event_id": event_id,
                "stored_fingerprint": stored,
                "incoming_fingerprint": fingerprint,
            },
            period=period,
        )
        return JSONResponse(
            status_code=409,
            content={
                "status": "conflict",
                "error": "idempotency_conflict",
                "event_id": event_id,
            },
        )

    if quarantined:
        logger.warning(
            "Stripe delivery quarantined outcome=%s event_id=%s account=%s.",
            resolution.outcome,
            event_id,
            resolution.stripe_account,
        )
        _audit(
            session,
            tenant_id=UNROUTABLE_TENANT,
            event_type="WEBHOOK_QUARANTINED",
            event_data={
                "provider": "stripe",
                "event_id": event_id,
                "outcome": resolution.outcome,
                "stripe_account": resolution.stripe_account,
            },
            period=period,
        )
        code = 404 if resolution.outcome == "unknown" else 400
        return JSONResponse(
            status_code=code,
            content={
                "status": "quarantined",
                "error": f"{resolution.outcome}_tenant",
                "event_id": event_id,
            },
        )

    logger.info(
        "Stripe delivery accepted event_id=%s tenant_id=%s type=%s.",
        event_id,
        tenant_id,
        event_type,
    )
    return JSONResponse(
        status_code=202,
        content={"status": "accepted", "event_id": event_id, "tenant_id": tenant_id},
    )


__all__ = [
    "EnvelopeError",
    "SIGNATURE_TOLERANCE_SECONDS",
    "STATUS_IGNORED",
    "STATUS_RECEIVED",
    "SignatureError",
    "TenantResolution",
    "UNROUTABLE_TENANT",
    "build_signature_header",
    "get_db_session",
    "parse_envelope",
    "resolve_tenant",
    "router",
    "stripe_webhook",
    "verify_stripe_signature",
]
