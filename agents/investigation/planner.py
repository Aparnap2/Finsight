"""Deterministic typed investigation planner (P4.2).

:class:`Planner` turns an :class:`InvestigationRequest` into an
:class:`InvestigationPlan` — semantic interpretation, hypothesis generation,
investigation planning, and capability selection — through exactly one
``LLMProvider.generate_structured`` call with a deterministic prompt renderer.
No money arithmetic is performed and no amounts appear in the prompt beyond
opaque evidence ids.

After the call the planner applies structural validation only: schema parse
(enforced at the provider boundary), allowlist membership against the
request snapshot, string-only bounded args, size bounds,
``evidence_required`` subset of ``request.evidence_ids``, and a
non-authoritative wording scan of the hypothesis (flagged, never fixed).
Failures raise :class:`PlannerError` (structural rejections as
:class:`PlanRejectedError`); the caller owns fallback to P3 templates.

The planner executes no capability, holds no state, builds no proposal, runs
no loop, and imports no LangChain/LiteLLM or ``apps``/``finance`` execution
paths. It is provider-agnostic: any ``LLMProvider`` (Groq, FakeLLM) behaves
identically through the injected seam.
"""

from __future__ import annotations

import logging
import re

from agents.investigation.errors import PlannerError, PlanRejectedError
from agents.investigation.plan import FROZEN_CAPABILITY_ALLOWLIST, InvestigationPlan
from agents.investigation.request import MAX_CONTEXT_CHARS, InvestigationRequest
from shared.llm.errors import ProviderError
from shared.llm.provider import LLMProvider
from shared.llm.types import InvestigationPrompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are the FinSight investigation planner. Return ONE candidate "
    "InvestigationPlan as JSON with exactly these fields: hypothesis_text, "
    "capability_calls, evidence_required, escalation. "
    "Allowed acts only: semantic interpretation, hypothesis generation, "
    "investigation planning, capability selection from the provided allowlist, "
    "evidence synthesis. "
    "Never: determine authoritative amounts, perform calculations, change "
    "state, execute providers, approve proposals, transition state, emit "
    "CLOSED, bypass policy, choose idempotency keys, declare VERIFIED, "
    "override authorization, or select execution mode. "
    "Word the hypothesis as an unproven candidate: never claim verified, "
    "confirmed, or exact amounts. Output is a proposal input to deterministic "
    "validation, never an authorization."
)

_AUTHORITATIVE_WORDS_RE = re.compile(r"\b(?:verified|confirmed)\b")
"""Flags authoritative wording (applied to separator-normalized text)."""

_AMOUNT_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d{1,2})?|\b\d[\d,]*\.\d{2}\b")
"""Flags exact-amount figures (currency signs or two-decimal numbers)."""


def _normalize_words(text: str) -> str:
    """Lowercase and split ``_``/``-`` so joined forms stay detectable."""
    return text.lower().replace("_", " ").replace("-", " ")


def render_investigation_prompt(request: InvestigationRequest) -> InvestigationPrompt:
    """Render a deterministic bounded prompt for one planning round.

    Args:
        request: Validated planner input (verified-only evidence, bounded
            context, allowlist snapshot, round budget).

    Returns:
        A frozen :class:`InvestigationPrompt` carrying opaque ids only —
        no amounts, no credentials, no unscoped history. Identical requests
        render byte-identical prompts.
    """
    evidence = ", ".join(request.evidence_ids)
    allowlist = ", ".join(request.capability_allowlist)
    lines = [
        f"exception_id: {request.exception_id}",
        f"exception_type: {request.exception_type}",
        f"evidence_ids (verified-only, opaque references): {evidence}",
        f"capability_allowlist: {allowlist}",
        f"round_budget: {request.round_budget}",
        f"context: {request.context_window or '(none)'}",
    ]
    if request.context_truncated:
        lines.append(f"(context truncated to {MAX_CONTEXT_CHARS} chars at construction)")
    lines.extend(
        [
            "Task: interpret the exception, propose ONE unproven hypothesis, then "
            "plan ordered investigation steps selecting ONLY from the allowlist.",
            "Rules: capability_calls need capability (allowlist only), string-only "
            "args, and order_index 0-based matching position; evidence_required "
            "must be a non-empty subset of evidence_ids; set escalation true to "
            "force human review.",
        ]
    )
    return InvestigationPrompt(
        user_prompt="\n".join(lines),
        system_prompt=_SYSTEM_PROMPT,
        evidence_ids=request.evidence_ids,
        allowlist_snapshot=request.capability_allowlist,
    )


class Planner:
    """One-shot typed planner over a constructor-injected LLMProvider."""

    def __init__(self, llm: LLMProvider) -> None:
        """Bind the provider seam (no capability execution here).

        Args:
            llm: Any ``LLMProvider`` (Groq, FakeLLM, ...); behavior is
                identical across implementations by construction.

        Raises:
            TypeError: If ``llm`` is None.
        """
        if llm is None:
            raise TypeError("llm must be an LLMProvider, got None.")
        self._llm: LLMProvider = llm

    @property
    def llm(self) -> LLMProvider:
        """Return the injected provider seam."""
        return self._llm

    def plan(self, request: InvestigationRequest) -> InvestigationPlan:
        """Produce a structurally valid candidate plan with one LLM call.

        Args:
            request: Validated planner input.

        Returns:
            The candidate :class:`InvestigationPlan` (unauthorized proposal).

        Raises:
            TypeError: If ``request`` is not an :class:`InvestigationRequest`.
            PlanRejectedError: If request invariants or plan structure fail.
            PlannerError: If the provider call fails or returns malformed
                output (caller degrades to P3 templates).
        """
        if not isinstance(request, InvestigationRequest):
            raise TypeError(
                f"request must be an InvestigationRequest, got {type(request).__name__}."
            )
        self._require_request_invariants(request)
        prompt = render_investigation_prompt(request)
        logger.debug(
            "planning exception=%s evidence=%d allowlist=%d",
            request.exception_id,
            len(request.evidence_ids),
            len(request.capability_allowlist),
        )
        try:
            candidate = self._llm.generate_structured(prompt, InvestigationPlan)
        except (PlanRejectedError, PlannerError):
            raise
        except ProviderError as exc:
            raise PlannerError(f"provider failed for exception {request.exception_id}") from exc
        except Exception as exc:
            raise PlannerError(f"planning failed for exception {request.exception_id}") from exc
        self._validate_structure(candidate, request)
        logger.info(
            "plan accepted exception=%s calls=%d escalation=%s",
            request.exception_id,
            len(candidate.capability_calls),
            candidate.escalation,
        )
        return candidate

    @staticmethod
    def _require_request_invariants(request: InvestigationRequest) -> None:
        """Defensively re-check construction-site gates before any LLM call.

        Raises:
            PlanRejectedError: On empty evidence, exhausted budget, or a snapshot
                outside the frozen allowlist.
        """
        if len(request.evidence_ids) == 0:
            raise PlanRejectedError("InvestigationRequest carries no verified evidence ids.")
        if request.round_budget < 1:
            raise PlanRejectedError("Round budget exhausted; halt LLM calls per spec.")
        frozen = set(FROZEN_CAPABILITY_ALLOWLIST)
        outside = [c for c in request.capability_allowlist if c not in frozen]
        if outside:
            raise PlanRejectedError(f"Allowlist snapshot outside frozen set: {outside}.")

    @staticmethod
    def _validate_structure(plan: InvestigationPlan, request: InvestigationRequest) -> None:
        """Apply request-relative structural checks (flag, never fix).

        Raises:
            PlanRejectedError: On a non-plan payload, authoritative hypothesis
                wording, exact amounts, off-allowlist capabilities,
                non-string/unbounded args, or evidence outside the request set.
        """
        if not isinstance(plan, InvestigationPlan):
            raise PlanRejectedError(f"Candidate is {type(plan).__name__}, not InvestigationPlan.")
        hypothesis = plan.hypothesis_text
        if not hypothesis.strip():
            raise PlanRejectedError("hypothesis_text is blank.")
        if _AUTHORITATIVE_WORDS_RE.search(_normalize_words(hypothesis)):
            raise PlanRejectedError(
                "hypothesis_text uses authoritative wording (verified/confirmed); "
                "hypotheses must stay unproven."
            )
        if _AMOUNT_RE.search(hypothesis):
            raise PlanRejectedError(
                "hypothesis_text states an exact amount; amounts are deterministic-only."
            )
        allowed = set(request.capability_allowlist)
        for position, call in enumerate(plan.capability_calls):
            if call.capability not in allowed:
                raise PlanRejectedError(
                    f"capability_calls[{position}] names {call.capability!r} "
                    "outside the request allowlist snapshot."
                )
            for key, item in call.args.items():
                if not isinstance(key, str) or not isinstance(item, str):
                    raise PlanRejectedError(
                        f"capability_calls[{position}] args must be string-only."
                    )
        known = set(request.evidence_ids)
        unknown = [e for e in plan.evidence_required if e not in known]
        if unknown:
            raise PlanRejectedError(
                f"evidence_required cites ids outside the request set: {unknown}."
            )
