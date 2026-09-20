"""P6-08 track A independent re-readers — R1/R2/R3 fresh observations.

Every re-read is a fresh external observation made at verify time;
handoff bytes, labels, and digests are comparison targets, never the
observation itself (F8, F21). Missing sources raise IncompleteRead —
never zero-filled, never a FAILED verdict (verdicts belong to track B,
per F36). Every observation records ``observed_at`` from a
caller-supplied run time; this module never reads the clock.

R2 derives the accepted sum from digest-verified RESULT bytes via the
frozen codec only: each ACCEPTED line carries its posted amount as the
leading whitespace-separated token of the 50-char detail field (for
example ``"10000.00 POSTED 4812"``). REJECTED and DUPLICATE lines
contribute 0 — DUPLICATE lines resolve to their original outcome with
no double-count (F23) — but all three codes are counted.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, field_validator

from finance.legacy.protocol import (
    PROTOCOL_VERSION,
    LegacyChecksumError,
    LegacyParseError,
    LegacyRecordResult,
    RecordResult,
)
from finance.object_store.errors import (
    ObjectNotFoundError,
    ObjectStoreError,
    TenantIsolationError,
)
from finance.verification.ports import (
    ExpectedSettlementReader,
    ProviderPendingReader,
    ReReadStore,
)

logger = logging.getLogger(__name__)

_TWO_DP = Decimal("0.01")
_INR = "INR"


# ---------------------------------------------------------------------------
# Errors — incomplete runs versus corrupt observations versus boundary refusals
# ---------------------------------------------------------------------------


class IncompleteRead(Exception):  # noqa: N818 -- contract signal, not an error
    """A re-read source is missing or unreadable: the run is incomplete.

    Missing RESULT keys note VERIFY_RESULT_MISSING semantics; tenant or
    prefix violations note the VERIFY_PREFIX_ESCAPE engine mapping. The
    run mints no report and zero-fills nothing. The orchestrator reads
    ``code`` to route the signal into the audited incomplete path.
    """

    def __init__(self, message: str, *, code: str = "VERIFY_RESULT_MISSING") -> None:
        """Carry the message plus the machine code for boundary routing."""
        super().__init__(message)
        self.code = code


class CorruptResultRead(Exception):  # noqa: N818 -- contract signal, not an error
    """RESULT bytes fail integrity or shape checks (VERIFY_RESULT_MUTATED)."""

    code = "VERIFY_RESULT_MUTATED"
    """Machine code the orchestration boundary routes to FAILED."""


class WrongBatchRead(CorruptResultRead):  # noqa: N818 -- contract signal, not an error
    """RESULT header batch differs from the expected batch (VERIFY_BATCH_SKEW)."""

    code = "VERIFY_BATCH_SKEW"
    """Machine code the orchestration boundary routes to FAILED."""


class CountSkewRead(CorruptResultRead):  # noqa: N818 -- contract signal, not an error
    """Version, sequence, or line-population skew (VERIFY_COUNT_SKEW)."""

    code = "VERIFY_COUNT_SKEW"
    """Machine code the orchestration boundary routes to FAILED."""


class BoundaryRefused(Exception):  # noqa: N818 -- contract signal, not an error
    """A Decimal, scale, or currency boundary violation on an R2/R3 value.

    Currency mismatch notes the F66 rule: the engine maps it to the
    closest existing reason code and mints no new code.
    """


# ---------------------------------------------------------------------------
# Observation models — frozen, strict, caller-stamped
# ---------------------------------------------------------------------------


def _require_tz_aware(name: str, value: datetime) -> datetime:
    """Return the value when tz-aware, else raise ValueError."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be tz-aware (caller-supplied run time).")
    return value


def _require_two_dp(name: str, value: Decimal) -> Decimal:
    """Return the value when it is an exact 2-dp Decimal, else refuse."""
    if not isinstance(value, Decimal):
        raise BoundaryRefused(f"{name} must be Decimal, got {type(value).__name__}.")
    try:
        quantized = value.quantize(_TWO_DP)
    except InvalidOperation as exc:
        raise BoundaryRefused(f"{name} is not quantizable to 2 dp: {value!r}.") from exc
    if value != quantized:
        raise BoundaryRefused(f"{name} must carry exactly 2 dp, got {value!r}.")
    return value


class ResultBytesRead(BaseModel):
    """The fresh R1 RESULT observation: exact bytes plus their digest."""

    model_config = ConfigDict(frozen=True, strict=True)

    key: str = Field(..., min_length=1)
    data: bytes = Field(..., min_length=1)
    sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _check_observed_tz(cls, value: datetime) -> datetime:
        """Require the caller-supplied tz-aware run time."""
        return _require_tz_aware("observed_at", value)


class AcceptedDerivation(BaseModel):
    """The R2 derivation: accepted sum plus per-code counts from verified bytes."""

    model_config = ConfigDict(frozen=True, strict=True)

    batch_id: str = Field(..., min_length=1)
    accepted_total: Decimal
    accepted_count: int = Field(..., ge=0)
    rejected_count: int = Field(..., ge=0)
    duplicate_count: int = Field(..., ge=0)
    line_count: int = Field(..., ge=1)
    observed_at: datetime

    @field_validator("accepted_total")
    @classmethod
    def _check_total_two_dp(cls, value: Decimal) -> Decimal:
        """Require the exact 2-dp accepted sum."""
        return _require_two_dp("accepted_total", value)

    @field_validator("observed_at")
    @classmethod
    def _check_observed_tz(cls, value: datetime) -> datetime:
        """Require the caller-supplied tz-aware run time."""
        return _require_tz_aware("observed_at", value)


class ExpectedSettlementRead(BaseModel):
    """The R3 expectation observation: Decimal total plus as-of passthrough."""

    model_config = ConfigDict(frozen=True, strict=True)

    case_key: str = Field(..., min_length=1)
    total: Decimal
    as_of: datetime | None = None
    observed_at: datetime

    @field_validator("total")
    @classmethod
    def _check_total_two_dp(cls, value: Decimal) -> Decimal:
        """Require the exact 2-dp expected total."""
        return _require_two_dp("total", value)

    @field_validator("observed_at")
    @classmethod
    def _check_observed_tz(cls, value: datetime) -> datetime:
        """Require the caller-supplied tz-aware run time."""
        return _require_tz_aware("observed_at", value)


class ProviderPendingRead(BaseModel):
    """The R3 pending observation: Decimal total plus as-of passthrough."""

    model_config = ConfigDict(frozen=True, strict=True)

    batch_key: str = Field(..., min_length=1)
    pending: Decimal
    as_of: datetime | None = None
    observed_at: datetime

    @field_validator("pending")
    @classmethod
    def _check_pending_two_dp(cls, value: Decimal) -> Decimal:
        """Require the exact 2-dp pending total."""
        return _require_two_dp("pending", value)

    @field_validator("observed_at")
    @classmethod
    def _check_observed_tz(cls, value: datetime) -> datetime:
        """Require the caller-supplied tz-aware run time."""
        return _require_tz_aware("observed_at", value)


# ---------------------------------------------------------------------------
# R1 — RESULT re-read plus byte-exact digest compare
# ---------------------------------------------------------------------------


def sha256_hex(data: bytes) -> str:
    """Return the SHA-256 hex digest over the exact bytes given."""
    return hashlib.sha256(data).hexdigest()


def digests_agree(recomputed_hex: str, expected_hex: str) -> bool:
    """Compare two hex digests byte-exactly (F22); one bit of drift fails."""
    if not isinstance(recomputed_hex, str) or not isinstance(expected_hex, str):
        raise TypeError("digests_agree compares hex strings only.")
    return hmac.compare_digest(recomputed_hex, expected_hex)


def read_result_bytes(
    store: ReReadStore, key: str, *, timeout_s: float = 10.0, observed_at: datetime
) -> ResultBytesRead:
    """Fresh-GET the RESULT object by key (R1); the key shape is consumed as given.

    Args:
        store: The existing S3 read seam (timeout rides this caller param,
            never the port; production adapters honor it).
        key: The handoff ``result_key`` locator, carried verbatim.
        timeout_s: Per-object read budget in seconds (must be positive).
        observed_at: Caller-supplied tz-aware verification run time.

    Returns:
        The exact bytes plus their recomputed digest.

    Raises:
        ValueError: On an empty key or a non-positive timeout.
        IncompleteRead: When the key is absent (VERIFY_RESULT_MISSING
            semantics), tenant-escaped (VERIFY_PREFIX_ESCAPE mapping
            noted), or otherwise unreadable. Never zero-fills.
    """
    if not isinstance(key, str) or not key.strip():
        raise ValueError("key must be a non-empty string.")
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)):
        raise ValueError("timeout_s must be a positive number of seconds.")
    if timeout_s <= 0:
        raise ValueError("timeout_s must be a positive number of seconds.")
    _require_tz_aware("observed_at", observed_at)
    try:
        data, _meta = store.get_object(key)
    except ObjectNotFoundError as exc:
        raise IncompleteRead(
            f"VERIFY_RESULT_MISSING: RESULT absent at {key!r}; run incomplete, "
            "mint no report, zero-fill nothing."
        ) from exc
    except TenantIsolationError as exc:
        raise IncompleteRead(
            f"VERIFY_PREFIX_ESCAPE mapping: tenant refused key {key!r}; "
            "run incomplete, engine maps to the closest existing code.",
            code="VERIFY_PREFIX_ESCAPE",
        ) from exc
    except ObjectStoreError as exc:
        raise IncompleteRead(
            f"RESULT unreadable at {key!r} ({exc}); run incomplete, "
            "mint no report, zero-fill nothing."
        ) from exc
    logger.info("R1 RESULT re-read key=%s bytes=%d", key, len(data))
    return ResultBytesRead(key=key, data=data, sha256=sha256_hex(data), observed_at=observed_at)


# ---------------------------------------------------------------------------
# R2 — books-side accepted-total derivation from verified bytes
# ---------------------------------------------------------------------------


def _parse_accepted_amount(detail: str, sequence: int) -> Decimal:
    """Parse the posted amount leading an ACCEPTED line's detail field."""
    parts = detail.split()
    if not parts:
        raise CorruptResultRead(
            f"AC line {sequence} carries no amount token; VERIFY_RESULT_MUTATED."
        )
    try:
        amount = Decimal(parts[0])
    except InvalidOperation as exc:
        raise CorruptResultRead(
            f"AC line {sequence} amount {parts[0]!r} is not Decimal; "
            "VERIFY_RESULT_MUTATED."
        ) from exc
    if not amount.is_finite():
        raise CorruptResultRead(
            f"AC line {sequence} amount {parts[0]!r} is non-finite; "
            "VERIFY_RESULT_MUTATED."
        )
    try:
        quantized = amount.quantize(_TWO_DP)
    except InvalidOperation as exc:
        raise CorruptResultRead(
            f"AC line {sequence} amount {parts[0]!r} is not 2-dp money; "
            "VERIFY_RESULT_MUTATED."
        ) from exc
    if amount != quantized or amount < 0:
        raise CorruptResultRead(
            f"AC line {sequence} amount {parts[0]!r} is not exact 2-dp money; "
            "VERIFY_RESULT_MUTATED."
        )
    return amount


def derive_accepted_total(
    result_bytes: bytes, *, batch_id: str, observed_at: datetime
) -> AcceptedDerivation:
    """Parse verified RESULT bytes with the frozen codec into the accepted sum.

    Args:
        result_bytes: Exact RESULT bytes from the fresh R1 GET (digest
            agreement is checked by the caller before semantics are read).
        batch_id: Expected full-format batch id; wire-compact lines expand
            via the frozen codec before compare.
        observed_at: Caller-supplied tz-aware verification run time.

    Returns:
        The accepted Decimal sum plus per-code counts; REJECTED and
        DUPLICATE lines contribute 0 but are counted.

    Raises:
        ValueError: On an empty batch id.
        CorruptResultRead: On non-ascii, misshapen, or bad-checksum bytes
            (VERIFY_RESULT_MUTATED semantics noted in the message).
        WrongBatchRead: When any line states another batch (carries
            VERIFY_BATCH_SKEW).
        CountSkewRead: On version, sequence, or population skew (carries
            VERIFY_COUNT_SKEW).
    """
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise ValueError("batch_id must be a non-empty string.")
    _require_tz_aware("observed_at", observed_at)
    try:
        text = result_bytes.decode("ascii")
    except UnicodeDecodeError as exc:
        raise CorruptResultRead(
            "RESULT bytes are not ascii; VERIFY_RESULT_MUTATED."
        ) from exc
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    if not lines:
        raise CorruptResultRead("RESULT carries no lines; VERIFY_RESULT_MUTATED.")
    parsed: list[LegacyRecordResult] = []
    for position, line in enumerate(lines, start=1):
        if len(line) != 80:
            raise CorruptResultRead(
                f"RESULT line {position} width != 80; VERIFY_RESULT_MUTATED."
            )
        try:
            parsed.append(LegacyRecordResult.from_line(line))
        except (LegacyChecksumError, LegacyParseError) as exc:
            raise CorruptResultRead(
                f"RESULT line {position} fails shape/checksum; VERIFY_RESULT_MUTATED."
            ) from exc
    for entry in parsed:
        if entry.version != PROTOCOL_VERSION:
            raise CountSkewRead(
                f"RESULT version skew {entry.version!r}; VERIFY_COUNT_SKEW."
            )
        if entry.batch_id != batch_id:
            raise WrongBatchRead(
                f"RESULT batch skew {entry.batch_id!r} != {batch_id!r}; "
                "VERIFY_BATCH_SKEW."
            )
    sequences = sorted(entry.sequence for entry in parsed)
    if sequences != list(range(1, len(parsed) + 1)):
        raise CountSkewRead(
            f"RESULT sequence skew got {sequences}; VERIFY_COUNT_SKEW."
        )
    accepted_total = Decimal("0.00")
    accepted_count = 0
    rejected_count = 0
    duplicate_count = 0
    for entry in parsed:
        if entry.result_code == RecordResult.ACCEPTED:
            accepted_total += _parse_accepted_amount(entry.detail, entry.sequence)
            accepted_count += 1
        elif entry.result_code == RecordResult.REJECTED:
            rejected_count += 1
        else:
            duplicate_count += 1
    logger.info(
        "R2 accepted derivation batch=%s lines=%d accepted=%s",
        batch_id, len(parsed), accepted_total,
    )
    return AcceptedDerivation(
        batch_id=batch_id,
        accepted_total=accepted_total,
        accepted_count=accepted_count,
        rejected_count=rejected_count,
        duplicate_count=duplicate_count,
        line_count=len(parsed),
        observed_at=observed_at,
    )


def compose_legacy_after(prior_total: Decimal, accepted_total: Decimal) -> Decimal:
    """Compose ``legacy_total_after`` as prior total plus the fresh accepted sum.

    The prior total arrives as a caller-supplied run input tagged with its
    provenance (a detection fact, never a handoff field per F65); the
    accepted sum comes only from digest-verified RESULT bytes.

    Raises:
        BoundaryRefused: When either input is not an exact 2-dp Decimal.
    """
    _require_two_dp("prior_total", prior_total)
    _require_two_dp("accepted_total", accepted_total)
    return prior_total + accepted_total


# ---------------------------------------------------------------------------
# R3 — expectation and pending reads with boundary enforcement
# ---------------------------------------------------------------------------


def _require_inr(currency: str, what: str) -> None:
    """Refuse any non-INR source currency at the boundary (F66)."""
    if currency != _INR:
        raise BoundaryRefused(
            f"{what} source currency {currency!r} refused: INR-only; "
            "engine maps to the closest existing code, no new code minted."
        )


def read_expected(
    port: ExpectedSettlementReader,
    case_key: str,
    *,
    currency: str = _INR,
    observed_at: datetime,
) -> ExpectedSettlementRead:
    """Re-read the expected settlement total from its authoritative source (R3).

    The port carries no currency field by design (minimal F66 seam), so
    the caller attests the source currency and anything but INR is
    refused. The source as-of timestamp passes through verbatim —
    staleness beyond the run window is track B's judgment, never this
    reader's. A missing value is incomplete, never zero-filled.
    """
    if not isinstance(case_key, str) or not case_key.strip():
        raise ValueError("case_key must be a non-empty string.")
    _require_tz_aware("observed_at", observed_at)
    _require_inr(currency, "expected settlement")
    try:
        total, as_of = port.read_expected(case_key)
    except Exception as exc:
        raise IncompleteRead(
            f"Expected settlement unreadable for {case_key!r} ({exc}); "
            "run incomplete, mint no report, zero-fill nothing."
        ) from exc
    if total is None:
        raise IncompleteRead(
            f"Expected settlement missing for {case_key!r}; run incomplete, "
            "mint no report, zero-fill nothing."
        )
    checked = _require_two_dp("expected_total", total)
    logger.info("R3 expected re-read case=%s total=%s", case_key, checked)
    return ExpectedSettlementRead(
        case_key=case_key, total=checked, as_of=as_of, observed_at=observed_at
    )


def read_pending(
    port: ProviderPendingReader,
    batch_key: str,
    *,
    currency: str = _INR,
    observed_at: datetime,
) -> ProviderPendingRead:
    """Re-read the recognised provider pending total from its source (R3).

    Same boundary contract as read_expected: caller-attested INR-only
    currency, verbatim as-of passthrough, and incomplete (never
    zero-filled, never FAILED) on missing or unreadable sources.
    """
    if not isinstance(batch_key, str) or not batch_key.strip():
        raise ValueError("batch_key must be a non-empty string.")
    _require_tz_aware("observed_at", observed_at)
    _require_inr(currency, "provider pending")
    try:
        pending, as_of = port.read_pending(batch_key)
    except Exception as exc:
        raise IncompleteRead(
            f"Provider pending unreadable for {batch_key!r} ({exc}); "
            "run incomplete, mint no report, zero-fill nothing."
        ) from exc
    if pending is None:
        raise IncompleteRead(
            f"Provider pending missing for {batch_key!r}; run incomplete, "
            "mint no report, zero-fill nothing."
        )
    checked = _require_two_dp("pending_total", pending)
    logger.info("R3 pending re-read batch=%s pending=%s", batch_key, checked)
    return ProviderPendingRead(
        batch_key=batch_key, pending=checked, as_of=as_of, observed_at=observed_at
    )
