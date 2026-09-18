"""P6-06 policy-approval-authorization engine (re-exports only).

Core invariant (contract A3):

    a valid proposal is evidence of what FinSight recommends; it is never
    evidence that FinSight is authorized to do it.

Approval is a capability grant for ONE immutable proposal execution identity
(proposal hash + version + execution identity bound in the token P6-07 will
consume), not a general permission to execute financial actions.
"""

from finance.approval.authorization import (
    AuthorizationToken,
    assert_single_decision,
    binding_digest_for,
    mint_authorization,
    verify_authorization,
)
from finance.approval.decision import (
    ApprovalDecision,
    DecisionOutcome,
    ProposalSnapshot,
    approval_id_for,
    assert_pin_frozen,
    canonical_amount,
    compute_proposal_hash,
    decide,
    idempotency_key_for,
)
from finance.approval.refusals import ApprovalRefused, RefusalCode
from finance.approval.tiers import (
    APPROVER_ROLES,
    KNOWN_ROLES,
    required_authority,
    role_may_approve,
)

__all__ = [
    "APPROVER_ROLES",
    "KNOWN_ROLES",
    "ApprovalDecision",
    "ApprovalRefused",
    "AuthorizationToken",
    "DecisionOutcome",
    "ProposalSnapshot",
    "RefusalCode",
    "approval_id_for",
    "assert_pin_frozen",
    "assert_single_decision",
    "binding_digest_for",
    "canonical_amount",
    "compute_proposal_hash",
    "decide",
    "idempotency_key_for",
    "mint_authorization",
    "required_authority",
    "role_may_approve",
    "verify_authorization",
]
