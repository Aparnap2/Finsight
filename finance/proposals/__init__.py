"""P3.3 proposal builder: drafts, history, and the approval pin shape.

``build_proposal`` drafts the v1 proposal from a verified aggregate and
canonical legs; ``mutate_proposal`` chains history without edits. The
approval triple (``proposal_id``, ``proposal_version``,
``content_hash``) reuses ``ApprovalPin``'s exact field names.

Only the Python standard library plus ``finance.*`` are used. This
package imports nothing from ``apps/``, ``agents/``, or ``shared/``.
"""

from finance.proposals.builder import (
    EmptyEvidenceError,
    ProposalBuildError,
    UnverifiedEvidenceError,
    build_proposal,
    mutate_proposal,
    verify_hash,
)
from finance.proposals.proposal import Proposal, ProposalAction, compute_content_hash

__all__ = [
    "EmptyEvidenceError",
    "Proposal",
    "ProposalAction",
    "ProposalBuildError",
    "UnverifiedEvidenceError",
    "build_proposal",
    "compute_content_hash",
    "mutate_proposal",
    "verify_hash",
]
