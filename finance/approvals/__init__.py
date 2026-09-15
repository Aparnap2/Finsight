"""T2 HITL approval boundary: ten ordered gates plus crash-safe CAS.

``ApprovalService.decide`` is the only path from ``AWAITING_APPROVAL`` to
``APPROVED``/``REJECTED``; approvals persist with NO execution
scheduling, so a crashed worker resumes from the database alone.
"""

from finance.approvals.decision import (
    ApprovalCommand,
    ApprovalDecision,
    ApprovalRecord,
    approval_id_for,
)
from finance.approvals.service import ApprovalRow, ApprovalService

__all__ = [
    "ApprovalCommand",
    "ApprovalDecision",
    "ApprovalRecord",
    "ApprovalRow",
    "ApprovalService",
    "approval_id_for",
]
