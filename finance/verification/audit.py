"""P6-08 track B audit spine (F6): one append-only entry per run.

Every verification run records exactly one frozen entry: the handoff digest,
the available re-read digests, the VERIFIED/FAILED/INCOMPLETE outcome with
its reason code, and the report hash when a report was minted (None on the
incomplete path). Money appears only as 2-dp totals inside hashed payloads,
never as raw fields. The log exposes no removal or rewrite API.
"""

from __future__ import annotations

from hashlib import sha256
from threading import Lock

from pydantic import BaseModel, ConfigDict, field_validator

from finance.domain.verification import VerificationReport
from finance.legacy_execution.handoff import ExecutionHandoff
from finance.verification.reason_codes import require_registered

_OUTCOMES: tuple[str, str, str] = ("VERIFIED", "FAILED", "INCOMPLETE")

__all__ = ["AuditEntry", "AuditLog", "digest_handoff", "hash_report"]


def digest_handoff(handoff: ExecutionHandoff) -> str:
    """Return the case-binding digest identifying what was verified (F6).

    The digest covers the stable case bindings (company, situation, batch,
    authorization, proposal pin, outbound provenance, control total, record
    count, record time) and excludes per-execution claim fields
    (execution_id, outcome, counts, totals, result refs, unknown flag) so
    that replays and sibling executions of one case share one audit
    identity; per-execution identity travels in the report hash instead.
    """
    parts = (
        handoff.company_id,
        handoff.situation_id,
        handoff.batch_id,
        handoff.authorization_id,
        handoff.proposal_hash,
        str(handoff.proposal_version),
        handoff.s3_outbound_key,
        handoff.outbound_sha256,
        str(handoff.control_total),
        str(handoff.record_count),
        handoff.recorded_at.isoformat(),
    )
    return sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def hash_report(report: VerificationReport) -> str:
    """Return the SHA-256 hash over the frozen report JSON (F6)."""
    return sha256(report.model_dump_json().encode("utf-8")).hexdigest()


class AuditEntry(BaseModel):
    """One frozen audit fact for a single verification run (F6)."""

    model_config = ConfigDict(frozen=True, strict=True)

    execution_id: str
    """Execution the run attempted to verify."""

    situation_id: str
    """Case binding carried from the handoff."""

    handoff_digest: str
    """Case-binding digest from digest_handoff."""

    reread_digests: tuple[str, ...] = ()
    """Hex digests of the R1/R2/R3 observations available on this run."""

    outcome: str
    """VERIFIED, FAILED, or INCOMPLETE (incomplete mints no report)."""

    reason_code: str | None = None
    """Registered code, or None for VERIFIED and model-owned refusals."""

    report_hash: str | None = None
    """Hash of the minted/returned report; None when nothing was minted."""

    @field_validator("outcome")
    @classmethod
    def _check_outcome(cls, value: str) -> str:
        """Require one of the three terminal run outcomes."""
        if value not in _OUTCOMES:
            raise ValueError(f"outcome must be one of {_OUTCOMES}, got {value!r}.")
        return value

    @field_validator("reason_code")
    @classmethod
    def _check_reason_registered(cls, value: str | None) -> str | None:
        """Refuse unregistered codes; None passes for codeless outcomes."""
        if value is None:
            return None
        return require_registered(value)


class AuditLog:
    """Append-only audit spine: one entry appended per verification run."""

    def __init__(self) -> None:
        """Create an empty log; entries accumulate only via append."""
        self._lock = Lock()
        self._entries: list[AuditEntry] = []

    def append(self, entry: AuditEntry) -> AuditEntry:
        """Append one entry and return it; entries are never rewritten."""
        with self._lock:
            self._entries.append(entry)
        return entry

    @property
    def entries(self) -> tuple[AuditEntry, ...]:
        """Return the recorded entries as an immutable snapshot tuple."""
        with self._lock:
            return tuple(self._entries)

    def __len__(self) -> int:
        """Return the number of recorded entries (one per run)."""
        with self._lock:
            return len(self._entries)
