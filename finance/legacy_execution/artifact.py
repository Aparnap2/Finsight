"""P6-07 T2 outbound artifact writer — stage E3 (artifact build).

Builds the fixed-width OUTBOUND batch that stage E4 uploads byte-for-byte.
Serialization failures refuse before any transport with
``EXEC_ARTIFACT_REFUSED``; a second batch id for one execution key refuses
with ``AUTHORIZATION_REPLAYED`` (X21/X32).

Type-01 payload layout — the E2→E3 landing for (amount_exact,
account_code). The 52-char wire record field (cols 25–76) is the 2-char
record type plus a 50-char payload with explicit positions::

    payload[0:20]   amount_exact as 2-dp decimal text, right-justified,
                    space-padded (e.g. ``"            10000.00"``).
    payload[20:30]  account_code, left-justified, space-padded to 10 chars.
    payload[30:50]  reserved padding (20 spaces).

The control record (type ``99``) carries the Decimal control total (sum of
data-record amounts, Decimal-only) in the same amount window::

    payload[0:20]   control total as 2-dp decimal text, right-justified.
    payload[20:50]  reserved padding (30 spaces).

Wire identity (A1): the logical id ``LEGACY-YYYYMMDD-NNNN`` (21 chars) is
used everywhere except cols 3–16 of the 80-char lines, which carry the
compact ``LEGYYMMDD-NNNN`` (14 chars) via the frozen protocol codec
(:func:`make_record_line` / :func:`_batch_id_to_compact`). Self-verify
expands the wire id back before comparing with logical ids; a line
carrying a 21-char id on the wire refuses.

Naming (A5): ``CORRECTION_<YYYYMMDD>_<SEQ>.DAT`` where ``SEQ`` is the last
three digits of the owning situation's sequence component
(``FS-…-00231`` → ``231``), derived — never hard-coded.

Only frozen protocol helpers are wrapped (``make_record_line``,
``LegacyRecord.from_line`` self-verify, ``_batch_id_to_compact`` /
``_compact_to_batch_id`` codec, ``validate_s3_key_tenant`` key-shape
check); nothing is reimplemented. No LLM, no network, no wall-clock.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from finance.legacy.protocol import (
    LegacyChecksumError,
    LegacyParseError,
    LegacyRecord,
    _batch_id_to_compact,
    _compact_to_batch_id,
    make_record_line,
    validate_s3_key_tenant,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ARTIFACT_REFUSED_CODE = "EXEC_ARTIFACT_REFUSED"
BINDING_REFUSED_CODE = "AUTHORIZATION_REPLAYED"

AMOUNT_FIELD_WIDTH = 20
ACCOUNT_FIELD_WIDTH = 10
TYPE01_RESERVED_WIDTH = 20
CONTROL_RESERVED_WIDTH = 30
TYPE01_PAYLOAD_WIDTH = 50

DATA_RECORD_TYPE = "01"
CONTROL_RECORD_TYPE = "99"
ALLOWED_OUTBOUND_TYPES = frozenset({DATA_RECORD_TYPE, CONTROL_RECORD_TYPE})

BATCH_ID_RE = re.compile(r"^LEGACY-\d{8}-\d{4}$")
PROCESSING_DATE_RE = re.compile(r"^\d{8}$")

DEFAULT_MAX_DATA_RECORDS = 100_000

_TWO_DP = Decimal("0.01")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ArtifactRefusedError(Exception):
    """E3 refuse-before-transport failure (``EXEC_ARTIFACT_REFUSED``).

    The message names the first bad line/field per X22.
    """

    code = ARTIFACT_REFUSED_CODE

    def __init__(self, detail: str) -> None:
        super().__init__(f"{ARTIFACT_REFUSED_CODE}: {detail}")


class ArtifactBindingError(Exception):
    """Second batch id for one execution key (``AUTHORIZATION_REPLAYED``)."""

    code = BINDING_REFUSED_CODE

    def __init__(self, detail: str) -> None:
        super().__init__(f"{BINDING_REFUSED_CODE}: {detail}")


# ---------------------------------------------------------------------------
# Models (frozen, strict, Decimal-only)
# ---------------------------------------------------------------------------


class ExecutionIntent(BaseModel):
    """T2 view of the E2 execution intent (mirrors the T1 producer fields).

    ``execution_id`` must equal ``idempotency_key``; when ``scope_batch``
    is present the artifact batch must reuse it (X17/X21).
    """

    model_config = ConfigDict(frozen=True, strict=True)

    action: str = Field(..., min_length=1)
    amount_exact: Decimal
    account_code: str = Field(..., min_length=1)
    company_id: str = Field(..., min_length=1)
    situation_id: str = Field(..., min_length=1)
    scope_batch: str | None = Field(default=None)
    idempotency_key: str = Field(..., min_length=1)
    execution_id: str = Field(..., min_length=1)
    proposal_hash: str = Field(..., min_length=1)
    proposal_version: int


class CorrectionRecordSpec(BaseModel):
    """One data-record spec: amount plus account code (Decimal-only)."""

    model_config = ConfigDict(frozen=True, strict=True)

    amount: Decimal
    account_code: str = Field(..., min_length=1)


class OutboundArtifact(BaseModel):
    """E3 permit output — the exact bytes E4 uploads (X23).

    ``company_id``/``situation_id`` travel as envelope fields so E4 can
    enforce the X24 prefix check without re-reading the token.
    """

    model_config = ConfigDict(frozen=True, strict=True)

    execution_id: str = Field(..., min_length=1)
    batch_id: str = Field(..., pattern=r"^LEGACY-\d{8}-\d{4}$")
    company_id: str = Field(..., min_length=1)
    situation_id: str = Field(..., min_length=1)
    file_name: str = Field(..., pattern=r"^CORRECTION_\d{8}_\d{3}\.DAT$")
    record_count: int = Field(..., ge=1)
    control_total: Decimal
    file_bytes: bytes = Field(..., min_length=1)
    outbound_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------------------
# Execution-key -> batch-id binding (X21: same key, same batch id)
# ---------------------------------------------------------------------------

_EXECUTION_BATCH_BINDINGS: dict[str, str] = {}


def clear_artifact_bindings() -> None:
    """Reset the execution->batch binding registry (test isolation only)."""
    _EXECUTION_BATCH_BINDINGS.clear()


# ---------------------------------------------------------------------------
# A5 naming
# ---------------------------------------------------------------------------


def derive_file_seq(situation_id: str) -> str:
    """Derive ``SEQ`` as the last three digits of the situation sequence.

    ``FS-2026-0916-00231`` → ``"231"``; ``FS-2026-0916-00042`` → ``"042"``
    (verbatim chars, never int-stripped, never hard-coded).
    """
    tail = situation_id.rsplit("-", 1)[-1]
    digits = "".join(ch for ch in tail if ch.isdigit())
    if not digits:
        raise ArtifactRefusedError(f"situation_id {situation_id!r} carries no digits")
    seq = digits[-3:].zfill(3)
    if len(seq) != 3 or not seq.isdigit():
        raise ArtifactRefusedError(f"situation_id {situation_id!r} yields bad SEQ")
    return seq


def derive_file_name(
    processing_date: str, situation_id: str, file_seq: str | None = None
) -> str:
    """Return ``CORRECTION_<YYYYMMDD>_<SEQ>.DAT`` (A5 generic rule)."""
    if not PROCESSING_DATE_RE.match(processing_date):
        raise ArtifactRefusedError(f"bad processing_date {processing_date!r}")
    seq = file_seq if file_seq is not None else derive_file_seq(situation_id)
    if len(seq) != 3 or not seq.isdigit():
        raise ArtifactRefusedError(f"bad file SEQ {seq!r}")
    return f"CORRECTION_{processing_date}_{seq}.DAT"


# ---------------------------------------------------------------------------
# Payload builders (explicit 50-char positions)
# ---------------------------------------------------------------------------


def _quantize_or_refuse(amount: Decimal, where: str) -> Decimal:
    """Normalize to 2 dp; refuse amounts carrying more than 2 dp."""
    if not isinstance(amount, Decimal):
        raise ArtifactRefusedError(f"{where} is not Decimal: {amount!r}")
    try:
        quantized = amount.quantize(_TWO_DP)
    except InvalidOperation as exc:
        raise ArtifactRefusedError(f"{where} not quantizable to 2 dp") from exc
    if amount != quantized:
        raise ArtifactRefusedError(f"{where} carries more than 2 dp: {amount!r}")
    return quantized


def build_type01_payload(amount: Decimal, account_code: str) -> str:
    """Build the 50-char type-01 payload (amount[0:20] + account[20:30])."""
    total = _quantize_or_refuse(amount, "record amount")
    if not account_code or len(account_code) > ACCOUNT_FIELD_WIDTH:
        raise ArtifactRefusedError(f"bad account_code {account_code!r}")
    amount_text = format(total, ".2f")
    if len(amount_text) > AMOUNT_FIELD_WIDTH:
        raise ArtifactRefusedError(f"amount {amount_text!r} exceeds 20-char window")
    payload = (
        amount_text.rjust(AMOUNT_FIELD_WIDTH)
        + account_code.ljust(ACCOUNT_FIELD_WIDTH)
        + " " * TYPE01_RESERVED_WIDTH
    )
    assert len(payload) == TYPE01_PAYLOAD_WIDTH
    return payload


def build_control_payload(control_total: Decimal) -> str:
    """Build the 50-char type-99 control payload (total[0:20] + padding)."""
    total = _quantize_or_refuse(control_total, "control total")
    amount_text = format(total, ".2f")
    if len(amount_text) > AMOUNT_FIELD_WIDTH:
        raise ArtifactRefusedError(f"control total {amount_text!r} exceeds 20-char window")
    payload = amount_text.rjust(AMOUNT_FIELD_WIDTH) + " " * CONTROL_RESERVED_WIDTH
    assert len(payload) == TYPE01_PAYLOAD_WIDTH
    return payload


def _parse_amount_window(payload: str, line_no: int) -> Decimal:
    """Parse payload[0:20] back to a 2-dp Decimal (self-verify path)."""
    cleaned = payload[0:AMOUNT_FIELD_WIDTH].strip()
    try:
        value = Decimal(cleaned) if cleaned else Decimal("0")
    except InvalidOperation as exc:
        raise ArtifactRefusedError(f"line {line_no}: bad amount {cleaned!r}") from exc
    return _quantize_or_refuse(value, f"line {line_no} amount")


# ---------------------------------------------------------------------------
# Self-verify (wrapped codec; refuse-before-transport per X22)
# ---------------------------------------------------------------------------


def verify_outbound_lines(
    lines: Sequence[str], *, batch_id: str, control_total: Decimal
) -> None:
    """Self-verify wire lines; refuse naming the first bad line/field.

    Checks 80-char width, 21-char wire-id escape (A1), legal record types,
    per-line checksums via the frozen codec, contiguous sequences from 1,
    single trailing control record, and Decimal control-total match.
    """
    if len(lines) == 0:
        raise ArtifactRefusedError("empty batch: zero data records")
    if not BATCH_ID_RE.match(batch_id):
        raise ArtifactRefusedError(f"bad batch_id {batch_id!r}")
    _quantize_or_refuse(control_total, "control total")

    sequences: list[int] = []
    parsed_types: list[str] = []
    data_sum = Decimal("0")
    control_seen = 0
    control_value: Decimal | None = None

    for index, line in enumerate(lines, start=1):
        if len(line) != 80:
            raise ArtifactRefusedError(f"line {index}: width {len(line)}, want 80")
        if line[2:16].startswith("LEGACY"):
            raise ArtifactRefusedError(f"line {index}: 21-char logical id on wire")
        record_raw = line[24:76]
        record_type = record_raw[:2]
        if record_type not in ALLOWED_OUTBOUND_TYPES:
            raise ArtifactRefusedError(f"line {index}: illegal record type {record_type!r}")
        try:
            parsed = LegacyRecord.from_line(line)
        except LegacyChecksumError as exc:
            raise ArtifactRefusedError(f"line {index}: checksum failure") from exc
        except LegacyParseError as exc:
            raise ArtifactRefusedError(f"line {index}: parse failure ({exc})") from exc
        if parsed.batch_id != batch_id:
            raise ArtifactRefusedError(
                f"line {index}: batch {parsed.batch_id!r} != {batch_id!r}"
            )
        sequences.append(parsed.sequence)
        parsed_types.append(record_type)
        payload = record_raw[2:]
        if record_type == DATA_RECORD_TYPE:
            data_sum += _parse_amount_window(payload, index)
        else:
            control_seen += 1
            control_value = _parse_amount_window(payload, index)

    if sorted(sequences) != list(range(1, len(lines) + 1)):
        raise ArtifactRefusedError(f"sequence gap or duplication: {sequences!r}")
    if control_seen != 1 or parsed_types[-1] != CONTROL_RECORD_TYPE:
        raise ArtifactRefusedError("control record must be exactly one trailing type-99")
    assert control_value is not None
    if control_value != data_sum:
        raise ArtifactRefusedError(
            f"control mismatch: lines sum {data_sum}, control {control_value}"
        )
    if control_value != control_total:
        raise ArtifactRefusedError(
            f"control mismatch: lines sum {control_value}, want {control_total}"
        )


# ---------------------------------------------------------------------------
# Artifact build (E3)
# ---------------------------------------------------------------------------


def _coerce_intent(intent: ExecutionIntent | Mapping[str, Any]) -> ExecutionIntent:
    """Accept the frozen intent model or an equivalent mapping (T1 seam)."""
    if isinstance(intent, ExecutionIntent):
        return intent
    if isinstance(intent, Mapping):
        return ExecutionIntent(**dict(intent))
    raise ArtifactRefusedError(f"intent must be a mapping, got {type(intent).__name__}")


def _normalize_specs(
    intent: ExecutionIntent, records: Sequence[Any] | None
) -> list[CorrectionRecordSpec]:
    """Normalize the records-spec to data-record specs (default: intent)."""
    if records is None:
        return [
            CorrectionRecordSpec(
                amount=intent.amount_exact, account_code=intent.account_code
            )
        ]
    specs: list[CorrectionRecordSpec] = []
    for index, item in enumerate(records, start=1):
        if isinstance(item, CorrectionRecordSpec):
            specs.append(item)
        elif isinstance(item, Decimal):
            specs.append(
                CorrectionRecordSpec(amount=item, account_code=intent.account_code)
            )
        elif isinstance(item, Mapping):
            account = item.get("account_code", intent.account_code)
            specs.append(
                CorrectionRecordSpec(amount=item["amount"], account_code=account)
            )
        else:
            raise ArtifactRefusedError(f"record {index}: bad spec {item!r}")
    return specs


def build_artifact(
    intent: ExecutionIntent | Mapping[str, Any],
    records: Sequence[Any] | None,
    *,
    batch_id: str,
    processing_date: str,
    file_seq: str | None = None,
    max_records: int = DEFAULT_MAX_DATA_RECORDS,
) -> OutboundArtifact:
    """Build the OUTBOUND artifact: exact bytes plus envelope (X18-X23).

    Order: intent hygiene (execution/idempotency match, scope pin) →
    batch binding (same key → same id) → line build via the frozen codec →
    self-verify → whole-file SHA-256 seal.
    """
    coerced = _coerce_intent(intent)
    if coerced.execution_id != coerced.idempotency_key:
        raise ArtifactRefusedError("execution_id != idempotency_key")
    if coerced.scope_batch is not None and coerced.scope_batch != batch_id:
        raise ArtifactRefusedError(
            f"scope_batch {coerced.scope_batch!r} != batch_id {batch_id!r}"
        )
    if not BATCH_ID_RE.match(batch_id):
        raise ArtifactRefusedError(f"bad batch_id {batch_id!r}")

    bound = _EXECUTION_BATCH_BINDINGS.get(coerced.execution_id)
    if bound is not None and bound != batch_id:
        raise ArtifactBindingError(
            f"execution {coerced.execution_id!r} bound to {bound!r}, "
            f"refusing second id {batch_id!r}"
        )

    specs = _normalize_specs(coerced, records)
    if len(specs) == 0:
        raise ArtifactRefusedError("empty batch: zero data records")
    if len(specs) > max_records:
        raise ArtifactRefusedError(
            f"oversized batch: {len(specs)} records above ceiling {max_records}"
        )

    file_name = derive_file_name(processing_date, coerced.situation_id, file_seq)
    # Key-shape check via the frozen tenant validator (no network here).
    validate_s3_key_tenant(
        f"{coerced.company_id}/{batch_id}/{file_name}", coerced.company_id
    )

    control_total = Decimal("0")
    lines: list[str] = []
    for sequence, spec in enumerate(specs, start=1):
        amount = _quantize_or_refuse(spec.amount, f"record {sequence} amount")
        control_total += amount
        payload = build_type01_payload(amount, spec.account_code)
        lines.append(
            make_record_line(
                batch_id=batch_id,
                sequence=sequence,
                record_type=DATA_RECORD_TYPE,
                record_payload=payload,
            )
        )
    control_total = control_total.quantize(_TWO_DP)
    lines.append(
        make_record_line(
            batch_id=batch_id,
            sequence=len(specs) + 1,
            record_type=CONTROL_RECORD_TYPE,
            record_payload=build_control_payload(control_total),
        )
    )

    verify_outbound_lines(lines, batch_id=batch_id, control_total=control_total)

    file_bytes = ("\n".join(lines) + "\n").encode("ascii")
    outbound_sha256 = hashlib.sha256(file_bytes).hexdigest()
    # Touch the compact codec explicitly (A1 documents the wrapping).
    _batch_id_to_compact(batch_id)
    _compact_to_batch_id(_batch_id_to_compact(batch_id))

    artifact = OutboundArtifact(
        execution_id=coerced.execution_id,
        batch_id=batch_id,
        company_id=coerced.company_id,
        situation_id=coerced.situation_id,
        file_name=file_name,
        record_count=len(specs),
        control_total=control_total,
        file_bytes=file_bytes,
        outbound_sha256=outbound_sha256,
    )
    _EXECUTION_BATCH_BINDINGS[coerced.execution_id] = batch_id
    return artifact
