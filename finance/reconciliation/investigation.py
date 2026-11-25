"""Bounded AI investigation of reconciliation exceptions.

The investigation builds a context from the exception, its run, and the
persisted evidence (matches, allocations). It calls the LLM through the
``LLMProvider`` protocol and requires structured output with evidence
references. The LLM may explain; it may not mutate financial state.

Abstention is explicit: when evidence is insufficient, the investigation
returns ``status='ABSTAINED'`` rather than fabricating an explanation.

Only the shared LLM framework and the Python standard library are used.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from finance.reconciliation.context import ExceptionDiagnostic
from shared.llm.provider import LLMProvider


class InvestigationFinding(BaseModel):
    """One structured finding from an AI investigation."""

    claim: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: str = Field(pattern="^(high|medium|low)$")
    abstained: bool = False
    abstention_reason: str | None = None


class InvestigationContext(BaseModel):
    """The evidence available to the LLM for one exception."""

    exception_id: str
    exception_code: str
    title: str
    description: str
    evidence_refs: list[str] = Field(default_factory=list)
    match_summary: str = ""
    allocation_summary: str = ""


class BoundedInvestigation:
    """Runs one evidence-grounded investigation via an LLM provider."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def investigate(
        self,
        context: InvestigationContext,
        diagnostic: ExceptionDiagnostic | None = None,
    ) -> InvestigationFinding:
        """Return a structured finding. Abstains on missing evidence.

        When a CP3 diagnostic is supplied, its calculations, rule results and
        eligibility are folded into the prompt as supplied evidence. The LLM
        explains; it does not recompute or mutate financial state.
        """
        if not context.evidence_refs:
            return InvestigationFinding(
                claim="Insufficient evidence to investigate this exception.",
                evidence_refs=[],
                confidence="low",
                abstained=True,
                abstention_reason="No evidence references provided.",
            )

        diagnostic_block = ""
        if diagnostic is not None:
            diagnostic_block = (
                "\nDiagnostic envelope (CP1-CP3, supplied - do not recompute):\n"
                f"  snapshot_id: {diagnostic.snapshot_id}\n"
                f"  engine_version: {diagnostic.engine_version}\n"
                f"  eligibility: "
                f"{diagnostic.eligibility.status.value if diagnostic.eligibility else 'unknown'}\n"
                f"  calculations: {diagnostic.context.calculations}\n"
                "  rule_results: "
                + ", ".join(r.rule_id + "=" + r.status.value for r in diagnostic.rule_results)
                + "\n"
            )

        prompt = (
            "You are a financial reconciliation analyst. Given the following "
            "exception, provide a concise explanation citing only the evidence "
            "references provided. Do not invent financial values. If evidence is "
            "insufficient, set abstained=true. You must not modify reconciliation "
            "results, eligibility, allocations, or exception status.\n\n"
            f"Exception: {context.exception_code} — {context.title}\n"
            f"Description: {context.description}\n"
            f"Evidence refs: {context.evidence_refs}\n"
            f"Match summary: {context.match_summary}\n"
            f"Allocation summary: {context.allocation_summary}\n"
            f"{diagnostic_block}"
        )

        try:
            result = self._provider.generate_structured(prompt, InvestigationFinding)
            # Enforce: if LLM claims non-abstained but no evidence refs, abstain
            if not result.abstained and not result.evidence_refs:
                return InvestigationFinding(
                    claim="Investigation produced no verifiable evidence references.",
                    evidence_refs=[],
                    confidence="low",
                    abstained=True,
                    abstention_reason="LLM output lacked evidence references.",
                )
            return result
        except Exception as exc:
            return InvestigationFinding(
                claim=f"Investigation failed: {exc}",
                evidence_refs=[],
                confidence="low",
                abstained=True,
                abstention_reason=f"Provider error: {exc}",
            )
