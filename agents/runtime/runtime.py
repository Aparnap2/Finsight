"""Minimal agent runtime — capability-gated, registry-bound, P7-01-validated.

LangGraph, when used, sits inside this runtime as an internal
implementation detail. It never defines authority; every advisory
output is validated through the frozen P7-01 boundary before a
``RuntimeHandoff`` is produced.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

from agents.authority.claims import (
    AgentCapability,
    AgentHypothesis,
    correlate_evidence,
    explain_proposal,
    validate_proposal_dict,
)
from agents.authority.evidence import AuthorityError
from agents.runtime.context import RuntimeContext
from agents.runtime.handoff import RuntimeHandoff

logger = logging.getLogger(__name__)

FakeModel = Callable[[AgentCapability, Mapping[str, Any]], Mapping[str, Any]]
"""Injectable model interface: (capability, inputs) -> plain dict payload."""


class AgentRuntime:
    """Capability-gated runtime that carries context through P7-01.

    No financial writes, no direct DB/S3, no tool implementations,
    no vector DB, no Temporal, no second authority model.
    """

    def __init__(
        self,
        context: RuntimeContext,
        *,
        model: FakeModel | None = None,
    ) -> None:
        """Store context and optional fake model (injected, not created)."""
        if not isinstance(context, RuntimeContext):
            raise AuthorityError("context must be a RuntimeContext.")
        self._context = context
        self._model = model
        self._boundary = context.boundary
        self._registry = context.registry

    @property
    def context(self) -> RuntimeContext:
        """Return the runtime context (read-only)."""
        return self._context

    def _require_capability(self, capability: AgentCapability) -> None:
        """Gate dispatch through the P7-01 boundary."""
        self._boundary.attempt(capability.value)
        logger.debug("Runtime capability granted: %s", capability.value)

    def _resolve_refs(self, evidence_ids: tuple[str, ...]) -> list[dict[str, Any]]:
        """Resolve evidence_ids via registry into plain dicts for validation.

        The registry is the sole authority; caller-supplied metadata
        never bypasses it.
        """
        dicts: list[dict[str, Any]] = []
        for eid in evidence_ids:
            rec = self._registry.get_record(eid)
            if not self._registry.is_accessible(eid):
                raise AuthorityError(f"Inaccessible evidence {eid!r}.")
            dicts.append(
                {
                    "evidence_id": rec.evidence_id,
                    "source_id": rec.source_id,
                    "captured_at": rec.captured_at.isoformat(),
                    "digest": rec.digest,
                    "provenance": rec.provenance,
                    "ttl_seconds": rec.ttl_seconds,
                }
            )
        return dicts

    def _validate_not_second_authority(self, output: Any) -> None:
        """Refuse any output that tries to smuggle a second authority model."""
        if hasattr(output, "to_authoritative") or hasattr(output, "to_fact"):
            raise AuthorityError("Second authority model is forbidden.")

    # --- Capability methods ---

    def read(self, evidence_ids: tuple[str, ...]) -> tuple[Any, ...]:
        """READ — resolve evidence_ids via registry, gated."""
        self._require_capability(AgentCapability.READ)
        refs = []
        for eid in evidence_ids:
            ref = self._registry.create_reference(eid)
            self._registry.validate_reference(ref, self._context.now)
            refs.append(ref)
        return tuple(refs)

    def correlate(self, evidence_ids: tuple[str, ...]) -> str:
        """CORRELATE — advisory correlation over registry-issued refs."""
        self._require_capability(AgentCapability.CORRELATE)
        refs = [self._registry.create_reference(eid) for eid in evidence_ids]
        for ref in refs:
            self._registry.validate_reference(ref, self._context.now)
        return correlate_evidence(refs, now=self._context.now)

    def hypothesize(
        self,
        *,
        text: str,
        evidence_ids: tuple[str, ...],
        uncertainty: str,
    ) -> AgentHypothesis:
        """HYPOTHESIZE — create advisory hypothesis, gated and validated."""
        self._require_capability(AgentCapability.HYPOTHESIZE)
        refs = tuple(self._registry.create_reference(eid) for eid in evidence_ids)
        for ref in refs:
            self._registry.validate_reference(ref, self._context.now)
        hyp = AgentHypothesis(
            text=text,
            evidence_refs=refs,
            uncertainty=uncertainty,
            created_at=self._context.now,
        )
        self._validate_not_second_authority(hyp)
        return hyp

    def propose(
        self,
        *,
        proposal_type: str,
        evidence_ids: tuple[str, ...],
        uncertainty: str,
        rationale: str,
        target: str | None = None,
    ) -> RuntimeHandoff:
        """PROPOSE — validated advisory proposal wrapped as explicit handoff.

        If a fake model is injected, its output is treated as plain data
        and re-validated through P7-01 — never trusted as authority.
        """
        self._require_capability(AgentCapability.PROPOSE)
        # Resolve via registry — never trust caller metadata.
        evidence_dicts = self._resolve_refs(evidence_ids)

        # If model is injected, call it and treat output as plain data.
        smuggled_from_model: dict[str, Any] = {}
        if self._model is not None:
            try:
                model_output = self._model(
                    AgentCapability.PROPOSE,
                    {
                        "proposal_type": proposal_type,
                        "evidence_ids": evidence_ids,
                        "uncertainty": uncertainty,
                        "rationale": rationale,
                        "target": target,
                    },
                )
            except Exception as exc:
                raise AuthorityError(f"Model failed: {exc}") from exc
            if model_output is None:
                raise AuthorityError("Model output unavailable; will not fabricate.")
            # Model output is plain data — re-validate, never trust.
            # Use model_output's proposal_type if it tries to smuggle, it will be rejected.
            proposal_type = str(model_output.get("proposal_type", proposal_type))
            uncertainty = str(model_output.get("uncertainty", uncertainty))
            rationale = str(model_output.get("rationale", rationale))
            target = model_output.get("target", target)
            # Evidence_ids from model are also re-resolved via registry.
            model_eids = model_output.get("evidence_ids", evidence_ids)
            if isinstance(model_eids, (list, tuple)):
                evidence_ids = tuple(str(x) for x in model_eids)
                evidence_dicts = self._resolve_refs(evidence_ids)
            # Preserve any smuggled keys so the P7-01 validator can refuse them.
            for k in ("status", "amount", "verdict", "decision"):
                if k in model_output:
                    smuggled_from_model[k] = model_output[k]

        payload: dict[str, Any] = {
            "proposal_type": proposal_type,
            "evidence_refs": evidence_dicts,
            "uncertainty": uncertainty,
            "rationale": rationale,
            "created_at": self._context.now.isoformat(),
        }
        if target is not None:
            payload["target"] = target
        payload.update(smuggled_from_model)

        proposal = validate_proposal_dict(
            payload,
            now=self._context.now,
            registry=self._registry,
            boundary=self._boundary,
        )
        self._validate_not_second_authority(proposal)
        handoff = RuntimeHandoff(
            proposal=proposal,
            situation_id=self._context.situation_id,
            company_id=self._context.company_id,
            created_at=self._context.now,
        )
        return handoff

    def explain(self, handoff: RuntimeHandoff) -> str:
        """EXPLAIN — human-facing explanation of a handoff's proposal."""
        self._require_capability(AgentCapability.EXPLAIN)
        if not isinstance(handoff, RuntimeHandoff):
            raise AuthorityError("explain requires a RuntimeHandoff.")
        return explain_proposal(handoff.proposal)

    def dispatch(
        self, capability: AgentCapability, inputs: Mapping[str, Any]
    ) -> Any:
        """Generic capability-gated dispatch (typed, registry-bound)."""
        if not isinstance(capability, AgentCapability):
            # Allow string for test of denied capability, but still gate.
            try:
                capability = AgentCapability(str(capability))
            except ValueError:
                msg = f"Capability {capability!r} outside authority."
                raise AuthorityError(msg) from None
        if capability == AgentCapability.READ:
            return self.read(tuple(inputs.get("evidence_ids", ())))
        if capability == AgentCapability.CORRELATE:
            return self.correlate(tuple(inputs.get("evidence_ids", ())))
        if capability == AgentCapability.HYPOTHESIZE:
            return self.hypothesize(
                text=str(inputs.get("text", "")),
                evidence_ids=tuple(inputs.get("evidence_ids", ())),
                uncertainty=str(inputs.get("uncertainty", "")),
            )
        if capability == AgentCapability.PROPOSE:
            # Smuggled keys must be refused even when passed via generic dispatch.
            for k in ("status", "amount", "verdict", "decision"):
                if k in inputs:
                    raise AuthorityError(
                        f"Proposal payload smuggles authoritative key {k!r}."
                    )
            return self.propose(
                proposal_type=str(inputs.get("proposal_type", inputs.get("action", ""))),
                evidence_ids=tuple(inputs.get("evidence_ids", inputs.get("evidence_refs", ()))),
                uncertainty=str(inputs.get("uncertainty", "")),
                rationale=str(inputs.get("rationale", "")),
                target=inputs.get("target"),
            )
        if capability == AgentCapability.EXPLAIN:
            handoff = inputs.get("handoff")
            if not isinstance(handoff, RuntimeHandoff):
                raise AuthorityError("EXPLAIN requires handoff.")
            return self.explain(handoff)
        raise AuthorityError(f"Capability {capability!r} is not dispatchable.")
