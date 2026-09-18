"""P6-07 explicit E5 stage: legacy RESULT observation (HOLD-1).

E5 observes what the ledger reported — verbatim per-record codes and
details — with no cross-checks, no totals math, and no recording.
All agreement checks (version/batch/sequence shape, control totals,
recording, UNKNOWN) belong to E6 ingestion, which consumes the
``ObservedBatch`` produced here. Malformed bytes refuse at observation
so E6 never reasons over corrupt input.
"""

from __future__ import annotations

import hashlib
import logging

from pydantic import BaseModel, ConfigDict, Field

from finance.legacy.protocol import (
    LegacyChecksumError,
    LegacyParseError,
    LegacyRecordResult,
)

logger = logging.getLogger(__name__)


class ObservationRefused(Exception):  # noqa: N818 -- contract refusal signal, not an error
    """Malformed RESULT bytes: E5 cannot observe (``EXEC_RESULT_CORRUPT``)."""

    code = "EXEC_RESULT_CORRUPT"

    def __init__(self, detail: str) -> None:
        super().__init__(f"EXEC_RESULT_CORRUPT: {detail}")


class ObservedRecord(BaseModel):
    """One ledger-reported per-record outcome, consumed exactly as given."""

    model_config = ConfigDict(frozen=True, strict=True)

    sequence: int = Field(..., ge=1)
    """1-based sequence within the RESULT file."""

    code: str = Field(..., min_length=2, max_length=2)
    """Verbatim ledger code (``AC``/``RJ``/``DU``); never reinterpreted."""

    detail: str = Field(default="", max_length=50)
    """Verbatim detail text (e.g. ``INVALID_ACCOUNT_CODE``)."""

    batch_id: str
    """Batch id as the ledger line states it (skew checked at E6)."""

    version: str = Field(..., min_length=1)
    """Protocol version as the ledger line states it (checked at E6)."""


class ObservedBatch(BaseModel):
    """The verbatim observed RESULT: records plus raw integrity."""

    model_config = ConfigDict(frozen=True, strict=True)

    records: tuple[ObservedRecord, ...]
    """Per-record outcomes in file order."""

    raw_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    """SHA-256 over the exact RESULT bytes observed."""


def observe_legacy_result(
    result_bytes: bytes, *, batch_id: str, company_id: str
) -> ObservedBatch:
    """Parse RESULT bytes into verbatim per-record observations (E5).

    Decodes ascii, enforces 80-char lines, and parses each line with
    the frozen codec (checksum-first). Records the batch id each line
    states without judging skew — agreement with the OUTBOUND batch is
    E6's job. The ``batch_id``/``company_id`` arguments scope logging
    only; observation never refuses on content mismatch.

    Args:
        result_bytes: Exact RESULT file bytes.
        batch_id: Expected logical batch (log context only).
        company_id: Bound company (log context only).

    Returns:
        The observed batch with raw integrity digest.

    Raises:
        ObservationRefused: Non-ascii bytes, bad line width, or any
            line failing shape/checksum parse.
    """
    raw_sha256 = hashlib.sha256(result_bytes).hexdigest()
    try:
        text = result_bytes.decode("ascii")
    except UnicodeDecodeError as exc:
        logger.warning(
            "E5 observe: non-ascii RESULT bytes company=%s batch=%s sha=%s size=%d",
            company_id, batch_id, raw_sha256, len(result_bytes),
        )
        raise ObservationRefused(
            f"RESULT bytes are not ascii for {batch_id!r}."
        ) from exc
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    for line in lines:
        if len(line) != 80:
            logger.warning(
                "E5 observe: bad line width company=%s batch=%s sha=%s lines=%d",
                company_id, batch_id, raw_sha256, len(lines),
            )
            raise ObservationRefused(
                f"RESULT line width != 80 for {batch_id!r}; raw bytes logged."
            )
    records: list[ObservedRecord] = []
    for position, line in enumerate(lines, start=1):
        try:
            parsed = LegacyRecordResult.from_line(line)
        except (LegacyChecksumError, LegacyParseError) as exc:
            logger.warning(
                "E5 observe: line %d unparseable company=%s batch=%s sha=%s",
                position, company_id, batch_id, raw_sha256,
            )
            raise ObservationRefused(
                f"RESULT line {position} fails shape/checksum "
                f"for {batch_id!r}."
            ) from exc
        records.append(
            ObservedRecord(
                sequence=parsed.sequence,
                code=parsed.result_code.value,
                detail=parsed.detail,
                batch_id=parsed.batch_id,
                version=parsed.version,
            )
        )
    return ObservedBatch(records=tuple(records), raw_sha256=raw_sha256)
