"""Unit tests: Stripe webhook signature verification (P2.1).

Contract under test (mirrors Stripe's ``t=...,v1=...`` scheme):

* ``signed_payload = "<timestamp>.<raw_body>"`` HMAC-SHA256 with the
  endpoint secret, hex-encoded as ``v1``.
* Header form is ``t=<unix_seconds>,v1=<hex>[,v1=<hex>...]`` (rollover).
* Tolerance is 300 seconds symmetric (past and future); ``|now - t| <= 300``
  passes, ``>= 301`` fails. A 600s-old timestamp is therefore expired.

The reference verifier below is test-local on purpose: it pins the exact
bytes-and-tolerance contract the future ``finance/ingest`` implementation
must satisfy, without importing any app code. Pure unit: no DB, no network,
no LLM, no clock reads (``now`` is injected).

Style: Arrange-Act-Assert, class-grouped, independent tests.
"""

from __future__ import annotations

import hashlib
import hmac

import pytest

from apps.api import webhooks as app_webhooks
from apps.api.webhooks import SignatureError as AppSignatureError

SIGNATURE_TOLERANCE_SECONDS = 300
FIXED_NOW = 1_746_105_600
SECRET = "whsec_test_flagship_secret_001"
WRONG_SECRET = "whsec_wrong_secret_002"
PAYLOAD = b'{"id":"evt-flagship-charge","object":"event"}'


class SignatureError(ValueError):
    """Raised when a webhook signature is missing, malformed, or invalid."""


def build_header(payload: bytes, secret: str, timestamp: int) -> str:
    """Build a Stripe-style signature header for the given payload."""
    signed = f"{timestamp}.".encode() + payload
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def verify_or_raise(
    payload: bytes,
    header: str | None,
    secret: str,
    now: int,
    tolerance: int = SIGNATURE_TOLERANCE_SECONDS,
) -> int:
    """Verify a webhook signature, returning the embedded timestamp.

    Raises:
        SignatureError: On missing/malformed header, digest mismatch,
            or timestamp outside ``tolerance`` (expired or future skew).
    """
    if header is None or not header.strip():
        raise SignatureError("Missing Stripe-Signature header.")
    timestamp: int | None = None
    signatures: list[str] = []
    for part in header.split(","):
        item = part.strip()
        if item.startswith("t="):
            try:
                timestamp = int(item[2:])
            except ValueError as exc:
                raise SignatureError("Malformed timestamp in signature header.") from exc
        elif item.startswith("v1="):
            signatures.append(item[3:])
    if timestamp is None:
        raise SignatureError("Malformed signature header: missing t=.")
    if not signatures:
        raise SignatureError("Malformed signature header: missing v1=.")
    signed = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise SignatureError("Signature mismatch.")
    if abs(now - timestamp) > tolerance:
        raise SignatureError(
            f"Timestamp outside tolerance: skew={abs(now - timestamp)}s "
            f"exceeds {tolerance}s."
        )
    return timestamp


class TestValidSignature:
    """A correctly signed payload verifies."""

    def test_valid_signature_passes(self) -> None:
        """Arrange a fresh header; Act verify; Assert timestamp returned."""
        header = build_header(PAYLOAD, SECRET, FIXED_NOW)
        assert verify_or_raise(PAYLOAD, header, SECRET, FIXED_NOW) == FIXED_NOW

    def test_rollover_second_v1_accepted(self) -> None:
        """Any matching v1 in a rollover header verifies."""
        good = build_header(PAYLOAD, SECRET, FIXED_NOW)
        good_sig = good.split("v1=")[1]
        header = f"t={FIXED_NOW},v1={'0' * 64},v1={good_sig}"
        assert verify_or_raise(PAYLOAD, header, SECRET, FIXED_NOW) == FIXED_NOW


class TestInvalidAndMissing:
    """Bad, absent, or malformed signatures are rejected."""

    def test_tampered_signature_rejected(self) -> None:
        """A flipped hex digit fails verification."""
        header = build_header(PAYLOAD, SECRET, FIXED_NOW)
        tampered = header[:-1] + ("0" if header[-1] != "0" else "1")
        with pytest.raises(SignatureError, match="mismatch"):
            verify_or_raise(PAYLOAD, tampered, SECRET, FIXED_NOW)

    def test_missing_header_rejected(self) -> None:
        """None and blank headers raise before any crypto."""
        with pytest.raises(SignatureError, match="Missing"):
            verify_or_raise(PAYLOAD, None, SECRET, FIXED_NOW)
        with pytest.raises(SignatureError, match="Missing"):
            verify_or_raise(PAYLOAD, "   ", SECRET, FIXED_NOW)

    def test_malformed_header_missing_v1_rejected(self) -> None:
        """A header without v1 is malformed, not merely invalid."""
        with pytest.raises(SignatureError, match="missing v1"):
            verify_or_raise(PAYLOAD, f"t={FIXED_NOW}", SECRET, FIXED_NOW)

    def test_malformed_header_missing_timestamp_rejected(self) -> None:
        """A header without t= is malformed."""
        with pytest.raises(SignatureError, match="missing t="):
            verify_or_raise(PAYLOAD, "v1=abcdef", SECRET, FIXED_NOW)

    def test_wrong_secret_rejected(self) -> None:
        """A header built with another secret never verifies."""
        header = build_header(PAYLOAD, WRONG_SECRET, FIXED_NOW)
        with pytest.raises(SignatureError, match="mismatch"):
            verify_or_raise(PAYLOAD, header, SECRET, FIXED_NOW)

    def test_modified_body_rejected(self) -> None:
        """Signing body A but delivering body B fails."""
        header = build_header(PAYLOAD, SECRET, FIXED_NOW)
        other = b'{"id":"evt-flagship-charge","object":"event","tampered":true}'
        with pytest.raises(SignatureError, match="mismatch"):
            verify_or_raise(other, header, SECRET, FIXED_NOW)


class TestTimestampTolerance:
    """300s tolerance: 600s-old is expired; boundary is inclusive."""

    def test_timestamp_600s_old_is_expired(self) -> None:
        """A 600s-old delivery exceeds the 300s window."""
        header = build_header(PAYLOAD, SECRET, FIXED_NOW - 600)
        with pytest.raises(SignatureError, match="outside tolerance"):
            verify_or_raise(PAYLOAD, header, SECRET, FIXED_NOW)

    def test_recent_timestamp_within_tolerance_passes(self) -> None:
        """A 100s-old delivery verifies."""
        header = build_header(PAYLOAD, SECRET, FIXED_NOW - 100)
        assert verify_or_raise(PAYLOAD, header, SECRET, FIXED_NOW) == FIXED_NOW - 100

    def test_past_boundary_minus_300_passes(self) -> None:
        """Exactly -300s is inside the inclusive window."""
        header = build_header(PAYLOAD, SECRET, FIXED_NOW - 300)
        assert verify_or_raise(PAYLOAD, header, SECRET, FIXED_NOW) == FIXED_NOW - 300

    def test_past_boundary_minus_301_fails(self) -> None:
        """-301s is one second past the window."""
        header = build_header(PAYLOAD, SECRET, FIXED_NOW - 301)
        with pytest.raises(SignatureError, match="outside tolerance"):
            verify_or_raise(PAYLOAD, header, SECRET, FIXED_NOW)

    def test_future_boundary_plus_300_passes(self) -> None:
        """Exactly +300s (clock skew) is inside the inclusive window."""
        header = build_header(PAYLOAD, SECRET, FIXED_NOW + 300)
        assert verify_or_raise(PAYLOAD, header, SECRET, FIXED_NOW) == FIXED_NOW + 300

    def test_future_boundary_plus_301_fails(self) -> None:
        """+301s future skew is rejected."""
        header = build_header(PAYLOAD, SECRET, FIXED_NOW + 301)
        with pytest.raises(SignatureError, match="outside tolerance"):
            verify_or_raise(PAYLOAD, header, SECRET, FIXED_NOW)


class TestAppVerifierParity:
    """Parity: apps.api.webhooks.verify_stripe_signature matches this contract.

    Pins the real transport verifier (raw ``t=<ts>.<bytes>`` HMAC-SHA256,
    300s symmetric tolerance) against the test-local reference above: a
    valid header passes, a one-byte body mutation mismatches, and the
    +/-300s boundary is inclusive while +/-301s expires.
    """

    def test_app_valid_signature_passes(self) -> None:
        """Arrange an app-built header; Act verify; Assert timestamp."""
        # Arrange: header built by the implementation under test.
        header = app_webhooks.build_signature_header(PAYLOAD, SECRET, FIXED_NOW)
        # Act: verify through the real verifier.
        timestamp = app_webhooks.verify_stripe_signature(
            PAYLOAD, header, SECRET, FIXED_NOW
        )
        # Assert: embedded timestamp is returned.
        assert timestamp == FIXED_NOW

    def test_app_one_byte_mutation_mismatches(self) -> None:
        """A single mutated body byte fails with reason ``mismatch``."""
        # Arrange: valid header for the pristine payload.
        header = app_webhooks.build_signature_header(PAYLOAD, SECRET, FIXED_NOW)
        mutated = PAYLOAD[:-1] + (b"}" if PAYLOAD[-1:] != b"}" else b"]")
        # Act + Assert: delivering mutated bytes mismatches.
        with pytest.raises(AppSignatureError) as exc_info:
            app_webhooks.verify_stripe_signature(
                mutated, header, SECRET, FIXED_NOW
            )
        assert exc_info.value.reason == "mismatch"

    def test_app_past_boundary_minus_300_passes(self) -> None:
        """Exactly -300s is inside the inclusive window."""
        # Arrange: header stamped at the past boundary.
        header = app_webhooks.build_signature_header(
            PAYLOAD, SECRET, FIXED_NOW - 300
        )
        # Act: verify at the fixed now.
        timestamp = app_webhooks.verify_stripe_signature(
            PAYLOAD, header, SECRET, FIXED_NOW
        )
        # Assert: boundary timestamp is accepted.
        assert timestamp == FIXED_NOW - 300

    def test_app_past_boundary_minus_301_fails(self) -> None:
        """-301s expires with reason ``expired``."""
        # Arrange: header one second past the window.
        header = app_webhooks.build_signature_header(
            PAYLOAD, SECRET, FIXED_NOW - 301
        )
        # Act + Assert: expired rejection.
        with pytest.raises(AppSignatureError) as exc_info:
            app_webhooks.verify_stripe_signature(
                PAYLOAD, header, SECRET, FIXED_NOW
            )
        assert exc_info.value.reason == "expired"

    def test_app_future_boundary_plus_300_passes(self) -> None:
        """Exactly +300s clock skew is inside the inclusive window."""
        # Arrange: header stamped at the future boundary.
        header = app_webhooks.build_signature_header(
            PAYLOAD, SECRET, FIXED_NOW + 300
        )
        # Act: verify at the fixed now.
        timestamp = app_webhooks.verify_stripe_signature(
            PAYLOAD, header, SECRET, FIXED_NOW
        )
        # Assert: boundary timestamp is accepted.
        assert timestamp == FIXED_NOW + 300

    def test_app_future_boundary_plus_301_fails(self) -> None:
        """+301s future skew expires with reason ``expired``."""
        # Arrange: header one second past the future window.
        header = app_webhooks.build_signature_header(
            PAYLOAD, SECRET, FIXED_NOW + 301
        )
        # Act + Assert: expired rejection.
        with pytest.raises(AppSignatureError) as exc_info:
            app_webhooks.verify_stripe_signature(
                PAYLOAD, header, SECRET, FIXED_NOW
            )
        assert exc_info.value.reason == "expired"
