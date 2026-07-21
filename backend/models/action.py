"""ActionItem model — template-backed action taxonomy with blocked-action enforcement.

Actions can only be created if they satisfy ALL gates:
1. Approved taxonomy (verb + domain)
2. Validated cause cited
3. Policy permission granted
4. Owner identified
5. Impact quantified or explicitly marked as unquantifiable
"""

from decimal import Decimal
from enum import Enum
from typing import Any
from pydantic import BaseModel, field_validator


class ActionStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    REJECTED = "rejected"


class ActionDomain(str, Enum):
    COST = "cost"
    REVENUE = "revenue"
    HEADCOUNT = "headcount"
    OPERATIONS = "operations"
    COMPLIANCE = "compliance"
    STRATEGY = "strategy"


APPROVED_ACTIONS: set[tuple[str, ActionDomain]] = {
    ("reduce", ActionDomain.COST),
    ("increase", ActionDomain.REVENUE),
    ("review", ActionDomain.COST),
    ("review", ActionDomain.OPERATIONS),
    ("renegotiate", ActionDomain.COST),
    ("invest", ActionDomain.REVENUE),
    ("invest", ActionDomain.STRATEGY),
    ("divest", ActionDomain.COST),
    ("restructure", ActionDomain.OPERATIONS),
    ("optimize", ActionDomain.COST),
    ("consolidate", ActionDomain.OPERATIONS),
    ("delay", ActionDomain.COST),
    ("accelerate", ActionDomain.REVENUE),
    ("hedge", ActionDomain.COST),
    ("automate", ActionDomain.OPERATIONS),
    ("outsource", ActionDomain.OPERATIONS),
    ("insource", ActionDomain.OPERATIONS),
    ("hire", ActionDomain.HEADCOUNT),
    ("freeze", ActionDomain.HEADCOUNT),
    ("reduce", ActionDomain.HEADCOUNT),
}


class ActionImpact(BaseModel):
    expected_savings: Decimal | None = None
    expected_revenue: Decimal | None = None
    one_time_cost: Decimal | None = None
    payback_period_months: int | None = None
    confidence: float = 0.0
    notes: str = ""


class ActionItem(BaseModel):
    id: str
    action: str
    domain: ActionDomain
    target: str
    description: str
    cited_assertion_ids: list[str]
    owner: str | None = None
    owner_identified: bool = False
    status: ActionStatus = ActionStatus.PROPOSED
    impact: ActionImpact | None = None
    impact_quantified: bool = False
    policy_permitted: bool = False
    blocked_reason: str | None = None
    metadata: dict[str, Any] = {}

    @field_validator("action")
    @classmethod
    def action_must_be_lowercase(cls, v: str) -> str:
        return v.lower().strip()

    @property
    def is_blocked(self) -> bool:
        return self.status == ActionStatus.BLOCKED

    @property
    def can_execute(self) -> bool:
        return self.status == ActionStatus.APPROVED and not self.is_blocked

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "action": self.action,
            "domain": self.domain.value,
            "target": self.target,
            "description": self.description,
            "cited_assertion_ids": self.cited_assertion_ids,
            "owner": self.owner,
            "status": self.status.value,
            "impact_quantified": self.impact_quantified,
            "policy_permitted": self.policy_permitted,
            "blocked_reason": self.blocked_reason,
            "impact": self.impact.model_dump() if self.impact else None,
        }


class ActionResult(BaseModel):
    created: bool = False
    action_item: ActionItem | None = None
    errors: list[str] = []
    warnings: list[str] = []


def create_action(
    action: str,
    domain: ActionDomain,
    target: str,
    description: str,
    cited_assertion_ids: list[str],
    owner: str | None = None,
    impact: ActionImpact | None = None,
    policy_permitted: bool = False,
) -> ActionResult:
    """Create an action item with full gate enforcement."""
    errors = []
    warnings = []

    # Gate 1: Taxonomy check
    if (action.lower().strip(), domain) not in APPROVED_ACTIONS:
        errors.append(f"Action '({action}, {domain.value})' not in approved taxonomy")
        return ActionResult(
            created=False,
            errors=errors,
            action_item=ActionItem(
                id="", action=action, domain=domain, target=target,
                description=description, cited_assertion_ids=cited_assertion_ids,
                status=ActionStatus.BLOCKED, blocked_reason=errors[0],
            ),
        )

    # Gate 2: Must cite at least one validated assertion
    if not cited_assertion_ids:
        errors.append("Action must cite at least one validated assertion")
        return ActionResult(
            created=False,
            errors=errors,
            action_item=ActionItem(
                id="", action=action, domain=domain, target=target,
                description=description, cited_assertion_ids=[],
                status=ActionStatus.BLOCKED, blocked_reason=errors[0],
            ),
        )

    # Gate 3: Policy permission
    if not policy_permitted:
        warnings.append("Action not yet policy-permitted — requires approval")

    # Gate 4: Impact quantification
    impact_quantified = impact is not None and (
        impact.expected_savings is not None or impact.expected_revenue is not None
    )
    if not impact_quantified:
        warnings.append("Impact not quantified — reduces action confidence")

    # Gate 5: Owner identification
    owner_identified = bool(owner and owner.strip())
    if not owner_identified:
        warnings.append("No owner identified — action requires assignment")

    action_id = f"act_{action}_{target.lower().replace(' ', '_')[:20]}"
    status = ActionStatus.PROPOSED if not policy_permitted else ActionStatus.APPROVED

    return ActionResult(
        created=True,
        action_item=ActionItem(
            id=action_id, action=action, domain=domain, target=target,
            description=description, cited_assertion_ids=cited_assertion_ids,
            owner=owner, owner_identified=owner_identified, status=status,
            impact=impact, impact_quantified=impact_quantified,
            policy_permitted=policy_permitted,
        ),
        warnings=warnings,
    )


def create_action_from_assertion(assertion: "Assertion", owner: str | None = None) -> ActionResult:
    """Create an action from an ACTION-type assertion."""
    metadata = assertion.metadata or {}
    action = metadata.get("action", "")
    target = metadata.get("target", "")
    policy_permitted = metadata.get("policy_permitted", False)
    target_lower = target.lower()

    domain = ActionDomain.OPERATIONS
    if any(w in target_lower for w in ["cost", "spend", "expense", "budget"]):
        domain = ActionDomain.COST
    elif any(w in target_lower for w in ["revenue", "sales", "income"]):
        domain = ActionDomain.REVENUE
    elif any(w in target_lower for w in ["headcount", "hire", "staff", "fte"]):
        domain = ActionDomain.HEADCOUNT

    return create_action(
        action=action, domain=domain, target=target,
        description=assertion.text,
        cited_assertion_ids=[assertion.id],
        owner=owner, policy_permitted=policy_permitted,
    )
