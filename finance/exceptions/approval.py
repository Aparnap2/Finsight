"""Approval pinning shape: the ``(proposal_id, version, content_hash)`` triple.

Approvals MUST bind all three coordinates at approval time; an approval
without the full triple is invalid. Proposal mutation bumps ``version``,
recomputes ``content_hash``, and invalidates prior pins — invalidated pins
are never resurrected. No approval API lives here in P3.2; this module
defines the pinned shape plus a ``verify`` helper reserved for P3.4, which
raises :class:`ApprovalSkewError` on mismatch.

Only the Python standard library is used.
"""

from dataclasses import dataclass

from finance.exceptions.errors import ApprovalSkewError


@dataclass(frozen=True)
class ApprovalPin:
    """Immutable binding of an approval to one proposal version.

    Attributes:
        proposal_id: Proposal the approval was granted against.
        proposal_version: Proposal version at approval time (>= 1).
        content_hash: Content hash at approval time (non-empty).
        approval_id: Approval record identity (non-empty).
    """

    proposal_id: str
    proposal_version: int
    content_hash: str
    approval_id: str

    def __post_init__(self) -> None:
        """Reject unbound triples: every coordinate is mandatory."""
        for field_name in ("proposal_id", "content_hash", "approval_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"ApprovalPin field '{field_name}' must be a non-empty string.")
        version = self.proposal_version
        if not isinstance(version, int) or isinstance(version, bool):
            raise TypeError("ApprovalPin field 'proposal_version' must be an int.")
        if version < 1:
            raise ValueError("ApprovalPin field 'proposal_version' must be >= 1.")

    def matches(self, proposal_id: str, proposal_version: int, content_hash: str) -> bool:
        """Return True when the pin exactly equals the presented triple."""
        return (
            self.proposal_id == proposal_id
            and self.proposal_version == proposal_version
            and self.content_hash == content_hash
        )

    def verify(self, proposal_id: str, proposal_version: int, content_hash: str) -> None:
        """Enforce exact triple equality, raising ``ApprovalSkewError`` on drift.

        Reserved for the P3.4 approval/execution path; P3.2 carries the
        shape only and never calls this from the aggregate.

        Raises:
            ApprovalSkewError: If any coordinate of the triple differs.
        """
        if not self.matches(proposal_id, proposal_version, content_hash):
            raise ApprovalSkewError(
                f"Approval {self.approval_id} pins "
                f"({self.proposal_id}, v{self.proposal_version}, "
                f"{self.content_hash}) but current proposal is "
                f"({proposal_id}, v{proposal_version}, {content_hash})"
            )
