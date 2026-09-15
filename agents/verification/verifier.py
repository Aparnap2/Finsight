"""Deterministic verifier gate for P4.2 investigation plans (P4.4).

:class:`Verifier` enforces the frozen LLM-boundary contract on a candidate
:class:`~agents.investigation.plan.InvestigationPlan` in a fixed stage order,
before any capability executes and before any P3 proposal advances:

1. schema — typed shape, unknown fields, ordering, non-empty minima;
2. allowlist — every call names one of the frozen five capabilities;
3. grounding — every ``evidence_required`` id is in the available set
   (these entries are the plan's factual claims; per-claim
   ``FACTUAL``/``HYPOTHESIS`` records do not exist on the frozen plan
   contract, so there are no further claim objects to ground);
4. claim classification — no ``VERIFIED``-family markers anywhere in plan
   text/fields; causal verbs (``caused by``, ``root cause``, ``proves``)
   stay hypothesis-side and reject when framed as factual/verified;
5. confidence caps — any confidence above the cap rejects, never
   clamps-and-passes (the frozen plan carries no confidence field, so
   this stage probes an explicit attribute when present and scans for
   deterministic ``confidence <n>`` declarations in plan text);
6. bounds — frozen quantitative ceilings from
   :mod:`agents.investigation.plan`; the round/attempt bound itself is
   enforced by the budget gate in :meth:`Verifier.verify` (escalate,
   never widen), not by a violation code.

``verify`` is pure and total: no capability execution, no mutable state,
no proposals, no authorization grants, no policy or mode changes, no LLM
calls, and no model judgment anywhere — regular expressions and bound
comparisons only. Re-plan never relaxes: the verifier carries identical
bounds for every attempt (constructor-fixed; ``verify`` takes no bound
overrides). Exact-amount and ``confirmed`` wording stays planner-owned
(P4.2); the verifier enforces exactly the six stages above.

This module imports only the frozen plan vocabulary from
:mod:`agents.investigation.plan` (plus stdlib): nothing from ``apps/``,
``finance`` execution paths, sibling ``agents`` packages, ``shared/``,
or any LLM framework.
"""

from __future__ import annotations

import math
import re
from collections.abc import Collection
from typing import Final

from agents.investigation.plan import (
    FROZEN_CAPABILITY_ALLOWLIST,
    MAX_ARG_KEY_CHARS,
    MAX_ARG_VALUE_CHARS,
    MAX_ARGS_PER_CALL,
    MAX_CAPABILITY_CALLS,
    MAX_EVIDENCE_ID_CHARS,
    MAX_EVIDENCE_REQUIRED,
    MAX_HYPOTHESIS_CHARS,
    InvestigationPlan,
)
from agents.verification.verdict import Verdict

DEFAULT_MAX_REPLANS: Final[int] = 2
"""Conservative bounded re-plan budget (spec: N defaults conservatively)."""

DEFAULT_CONFIDENCE_CAP: Final[float] = 0.85
"""Inclusive upper bound for any stated confidence; above it rejects."""

_FROZEN_ALLOWLIST = frozenset(FROZEN_CAPABILITY_ALLOWLIST)
"""Set view of the frozen closed capability vocabulary."""

_EXECUTION_VERIFIED_RE = re.compile(r"\bexecution verified\b")
"""Normalized marker for never-item 12 (declare execution VERIFIED)."""

_EVIDENCE_VERIFIED_RE = re.compile(r"\bevidence verified\b")
"""Normalized marker for never-item 11 (declare evidence VERIFIED)."""

_BARE_VERIFIED_RE = re.compile(r"\bverified\b")
"""Residual authoritativeness marker after specific spans are redacted."""

_CAUSAL_VERB_RE = re.compile(r"caused\s+by|root\s+cause|\bproves\b")
"""Causal verbs that force the HYPOTHESIS side (task stage 4)."""

_AUTHORITATIVE_ADJ_RE = re.compile(r"\b(?:verified|confirmed|proven|factual)\b")
"""Factual framing adjectives; co-occurrence with a causal verb rejects."""

_CONFIDENCE_RE = re.compile(
    r"confiden(?:ce|t)\s*(?:is|of|at|=|:)?\s*(\d+(?:\.\d+)?)\s*(%)?", re.IGNORECASE
)
"""Deterministic ``confidence <n>`` declarations (optional percent sign)."""

_PERCENT_CONFIDENCE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*confiden\w*", re.IGNORECASE)
"""Leading-percent form (``95% confidence``) missed by :data:`_CONFIDENCE_RE`."""

_SENTENCE_SPLIT_RE = re.compile(r"[.!?;\n]+")
"""Sentence splitter bounding causal/framing co-occurrence to one sentence."""

_APPROVAL_RE = re.compile(r"\bapprov\w*\b|\bauthori[sz]\w*\b")
"""Approval verbs (never-item 5); any occurrence rejects as proposal-directed."""

_EMIT_CLOSED_RE = re.compile(
    r"\bis\s+closed\b"
    r"|\bmark\w*\s+(?:as\s+)?closed\b"
    r"|\bclos(?:e|es|ed|ing)\s+as\s+closed\b"
    r"|\bclos(?:e|es|ed|ing)\s+(?:the\s+)?(?:case|exception)\b"
    r"|\b(?:case|exception)\s+(?:is\s+)?closed\b"
)
"""Authoritative CLOSED emission (never-item 7); word-boundary tight."""


def _normalize(text: str) -> str:
    """Lowercase and split ``_``/``-`` so joined forms stay detectable."""
    return text.lower().replace("_", " ").replace("-", " ")


class Verifier:
    """Pure deterministic gate over candidate investigation plans."""

    def __init__(
        self,
        *,
        max_replans: int = DEFAULT_MAX_REPLANS,
        confidence_cap: float = DEFAULT_CONFIDENCE_CAP,
    ) -> None:
        """Fix identical bounds for every attempt (no per-call widening).

        Args:
            max_replans: Bounded re-plan budget; failures at attempts at or
                above this escalate to HITL instead of replanning.
            confidence_cap: Inclusive upper bound for any stated confidence;
                anything above rejects (never clamped).

        Raises:
            TypeError: If either bound has the wrong type.
            ValueError: If either bound is out of range.
        """
        if type(max_replans) is not int:
            raise TypeError(f"max_replans must be an int, got {type(max_replans).__name__}.")
        if max_replans < 0:
            raise ValueError(f"max_replans must be >= 0, got {max_replans}.")
        if isinstance(confidence_cap, bool) or not isinstance(confidence_cap, (int, float)):
            raise TypeError(
                f"confidence_cap must be a number, got {type(confidence_cap).__name__}."
            )
        cap = float(confidence_cap)
        if math.isnan(cap) or not 0.0 < cap <= 1.0:
            raise ValueError(f"confidence_cap must satisfy 0 < cap <= 1, got {cap!r}.")
        self._max_replans = max_replans
        self._confidence_cap = cap

    @property
    def max_replans(self) -> int:
        """Return the fixed bounded re-plan budget."""
        return self._max_replans

    @property
    def confidence_cap(self) -> float:
        """Return the fixed inclusive confidence upper bound."""
        return self._confidence_cap

    def verify(
        self,
        plan: InvestigationPlan,
        available_evidence_ids: Collection[str],
        attempt: int = 0,
    ) -> Verdict:
        """Gate one candidate plan through the six ordered stages (pure).

        Stages short-circuit in order: the first failing stage supplies the
        machine-readable reasons. A clean plan returns ``ACCEPTED``; a
        failing plan returns ``REJECTED_REPLAN`` unless ``attempt`` has
        reached the fixed budget, in which case the case freezes with
        ``ESCALATE_HITL`` (original reasons preserved plus a
        ``budget_exhausted`` code). Malformed ``attempt`` or available-set
        inputs fail closed as ``REJECTED_REPLAN`` without escalation.

        Args:
            plan: Candidate :class:`InvestigationPlan` (authorizes nothing).
            available_evidence_ids: Verified-only evidence ids the plan may
                cite (deterministic-code-owned; exact-match membership).
            attempt: Zero-based re-plan attempt index for the budget gate.

        Returns:
            A frozen :class:`Verdict` carrying status, reason codes, and
            the attempt index. Never raises for plan content.
        """
        if type(attempt) is not int or attempt < 0:
            return Verdict(
                status="REJECTED_REPLAN",
                reasons=("bounds_violation:attempt_must_be_non_negative_int",),
                attempt_index=0,
            )
        available = self._normalize_available(available_evidence_ids)
        if available is None:
            return Verdict(
                status="REJECTED_REPLAN",
                reasons=("bounds_violation:available_evidence_ids_malformed",),
                attempt_index=attempt,
            )
        reasons = self._check_schema(plan)
        if not reasons:
            reasons = self._check_allowlist(plan)
        if not reasons:
            reasons = self._check_grounding(plan, available)
        if not reasons:
            reasons = self._check_claim_classification(plan)
        if not reasons:
            reasons = self._check_confidence(plan)
        if not reasons:
            reasons = self._check_bounds(plan)
        if not reasons:
            return Verdict(status="ACCEPTED", reasons=(), attempt_index=attempt)
        if attempt >= self._max_replans:
            exhausted = f"budget_exhausted:attempt_{attempt}_gte_max_{self._max_replans}"
            return Verdict(
                status="ESCALATE_HITL",
                reasons=(*reasons, exhausted),
                attempt_index=attempt,
            )
        return Verdict(status="REJECTED_REPLAN", reasons=reasons, attempt_index=attempt)

    @staticmethod
    def _normalize_available(available_evidence_ids: Collection[str]) -> set[str] | None:
        """Copy the available set; return None when malformed (fail closed)."""
        if isinstance(available_evidence_ids, str):
            return None
        if not isinstance(available_evidence_ids, Collection):
            return None
        available: set[str] = set()
        for evidence_id in available_evidence_ids:
            if not isinstance(evidence_id, str):
                return None
            if not evidence_id.strip():
                return None
            if len(evidence_id) > MAX_EVIDENCE_ID_CHARS:
                return None
            available.add(evidence_id)
        return available

    @staticmethod
    def _plan_texts(plan: InvestigationPlan) -> tuple[str, ...]:
        """Collect every free-text field: hypothesis, args, evidence ids."""
        texts: list[str] = []
        if isinstance(plan.hypothesis_text, str):
            texts.append(plan.hypothesis_text)
        for call in plan.capability_calls:
            if isinstance(call.args, dict):
                for key, value in call.args.items():
                    if isinstance(key, str):
                        texts.append(key)
                    if isinstance(value, str):
                        texts.append(value)
        for evidence_id in plan.evidence_required:
            if isinstance(evidence_id, str):
                texts.append(evidence_id)
        return tuple(texts)

    @staticmethod
    def _check_schema(plan: InvestigationPlan) -> tuple[str, ...]:
        """Re-validate typed shape: unknown fields, ordering, minima, types."""
        if not isinstance(plan, InvestigationPlan):
            return (f"schema_violation:not_investigation_plan:{type(plan).__name__}",)
        if plan.__pydantic_extra__:
            names = ",".join(sorted(str(key) for key in plan.__pydantic_extra__))
            return (f"schema_violation:unknown_fields:{names}",)
        if not isinstance(plan.hypothesis_text, str) or not plan.hypothesis_text.strip():
            return ("schema_violation:hypothesis_text_blank",)
        calls = plan.capability_calls
        if not isinstance(calls, tuple):
            return ("schema_violation:capability_calls_not_tuple",)
        if len(calls) == 0:
            return ("schema_violation:capability_calls_empty",)
        if len(calls) > MAX_CAPABILITY_CALLS:
            return (
                f"schema_violation:capability_calls_{len(calls)}_gt_max_{MAX_CAPABILITY_CALLS}",
            )
        for position, call in enumerate(calls):
            if not isinstance(call.capability, str) or not call.capability.strip():
                return (f"schema_violation:calls[{position}].capability_blank",)
            if not isinstance(call.args, dict):
                return (f"schema_violation:calls[{position}].args_not_mapping",)
            if len(call.args) > MAX_ARGS_PER_CALL:
                return (
                    f"schema_violation:calls[{position}].args_"
                    f"{len(call.args)}_gt_max_{MAX_ARGS_PER_CALL}",
                )
            for key, value in call.args.items():
                if not isinstance(key, str) or not isinstance(value, str):
                    return (f"schema_violation:calls[{position}].args_not_string_only",)
                if not key.strip():
                    return (f"schema_violation:calls[{position}].args_blank_key",)
            if type(call.order_index) is not int or call.order_index != position:
                return (f"schema_violation:calls[{position}].order_index_mismatch",)
        required = plan.evidence_required
        if not isinstance(required, tuple):
            return ("schema_violation:evidence_required_not_tuple",)
        if len(required) == 0:
            return ("schema_violation:evidence_required_empty",)
        seen: set[str] = set()
        for evidence_id in required:
            if not isinstance(evidence_id, str) or not evidence_id.strip():
                return ("schema_violation:evidence_required_blank_entry",)
            if evidence_id in seen:
                return (f"schema_violation:evidence_required_duplicate:{evidence_id}",)
            seen.add(evidence_id)
        if type(plan.escalation) is not bool:
            return ("schema_violation:escalation_not_bool",)
        return ()

    @staticmethod
    def _check_allowlist(plan: InvestigationPlan) -> tuple[str, ...]:
        """Reject any call naming a capability outside the frozen five."""
        reasons: list[str] = []
        for call in plan.capability_calls:
            if call.capability not in _FROZEN_ALLOWLIST:
                reasons.append(f"allowlist_violation:{call.capability}")
        return tuple(reasons)

    @staticmethod
    def _check_grounding(plan: InvestigationPlan, available: set[str]) -> tuple[str, ...]:
        """Require every evidence_required id to be in the available set."""
        return tuple(
            f"grounding_violation:unknown_evidence_id:{evidence_id}"
            for evidence_id in plan.evidence_required
            if evidence_id not in available
        )

    @classmethod
    def _check_claim_classification(cls, plan: InvestigationPlan) -> tuple[str, ...]:
        """Reject VERIFIED-family markers; keep causal verbs hypothesis-side."""
        found: list[str] = []
        for text in cls._plan_texts(plan):
            normalized = _normalize(text)
            if _EXECUTION_VERIFIED_RE.search(normalized):
                found.append("never_violation:declare_execution_verified")
            if _EVIDENCE_VERIFIED_RE.search(normalized):
                found.append("never_violation:declare_evidence_verified")
            redacted = _EXECUTION_VERIFIED_RE.sub(" ", normalized)
            redacted = _EVIDENCE_VERIFIED_RE.sub(" ", redacted)
            if _BARE_VERIFIED_RE.search(redacted):
                found.append("never_violation:declare_verified")
            if _APPROVAL_RE.search(normalized):
                found.append("never_violation:declare_approval")
            if _EMIT_CLOSED_RE.search(normalized):
                found.append("never_violation:emit_closed")
            for sentence in _SENTENCE_SPLIT_RE.split(normalized):
                if _CAUSAL_VERB_RE.search(sentence) and _AUTHORITATIVE_ADJ_RE.search(sentence):
                    found.append("never_violation:causal_claim_as_verified")
                    break
        ordered: list[str] = []
        for reason in found:
            if reason not in ordered:
                ordered.append(reason)
        return tuple(ordered)

    def _check_confidence(self, plan: InvestigationPlan) -> tuple[str, ...]:
        """Reject any confidence above the cap; never clamp-and-pass."""
        reasons: list[str] = []
        raw: object = getattr(plan, "confidence", None)
        if raw is not None:
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                reasons.append("confidence_violation:field_confidence_not_numeric")
            else:
                value = float(raw)
                if math.isnan(value) or not 0.0 <= value <= 1.0:
                    reasons.append("confidence_violation:field_confidence_out_of_range")
                elif value > self._confidence_cap:
                    reasons.append(
                        f"confidence_violation:field_confidence_{value!r}_"
                        f"gt_cap_{self._confidence_cap!r}",
                    )
        for text in self._plan_texts(plan):
            for match in _CONFIDENCE_RE.finditer(text):
                declared = float(match.group(1))
                if match.group(2) == "%":
                    declared /= 100.0
                if declared > self._confidence_cap:
                    reason = (
                        f"confidence_violation:declared_confidence_{declared!r}_"
                        f"gt_cap_{self._confidence_cap!r}"
                    )
                    if reason not in reasons:
                        reasons.append(reason)
                    break
            for match in _PERCENT_CONFIDENCE_RE.finditer(text):
                declared = float(match.group(1)) / 100.0
                if declared > self._confidence_cap:
                    reason = (
                        f"confidence_violation:declared_confidence_{declared!r}_"
                        f"gt_cap_{self._confidence_cap!r}"
                    )
                    if reason not in reasons:
                        reasons.append(reason)
                    break
        return tuple(reasons)

    @staticmethod
    def _check_bounds(plan: InvestigationPlan) -> tuple[str, ...]:
        """Enforce frozen quantitative ceilings (hypothesis, args, evidence).

        The round/attempt bound is enforced by the budget gate in
        :meth:`Verifier.verify` (escalate at budget, identical bounds every
        attempt, no widening parameters), not by a violation code here.
        """
        if len(plan.hypothesis_text) > MAX_HYPOTHESIS_CHARS:
            return (
                f"bounds_violation:hypothesis_text_len_{len(plan.hypothesis_text)}"
                f"_gt_max_{MAX_HYPOTHESIS_CHARS}",
            )
        if len(plan.evidence_required) > MAX_EVIDENCE_REQUIRED:
            return (
                f"bounds_violation:evidence_required_{len(plan.evidence_required)}"
                f"_gt_max_{MAX_EVIDENCE_REQUIRED}",
            )
        for evidence_id in plan.evidence_required:
            if len(evidence_id) > MAX_EVIDENCE_ID_CHARS:
                return (
                    f"bounds_violation:evidence_id_len_{len(evidence_id)}"
                    f"_gt_max_{MAX_EVIDENCE_ID_CHARS}",
                )
        for position, call in enumerate(plan.capability_calls):
            for key, value in call.args.items():
                if len(key) > MAX_ARG_KEY_CHARS:
                    return (
                        f"bounds_violation:calls[{position}].arg_key_len_{len(key)}"
                        f"_gt_max_{MAX_ARG_KEY_CHARS}",
                    )
                if len(value) > MAX_ARG_VALUE_CHARS:
                    return (
                        f"bounds_violation:calls[{position}].arg_value_len_{len(value)}"
                        f"_gt_max_{MAX_ARG_VALUE_CHARS}",
                    )
        return ()
