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
from agents.runtime.context import RuntimeContext, RuntimeRequest
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
        _factory: Any | None = None,
    ) -> None:
        """Store context and optional fake model (injected, not created)."""
        if not isinstance(context, RuntimeContext):
            raise AuthorityError("context must be a RuntimeContext.")
        # Enforce factory-issued context when a factory is present.
        # Direct construction without a factory is allowed in tests via
        # the factory helper, but a context with an empty token that
        # was not validated is still considered unissued if a factory
        # is supplied. For strict boundary, require token when factory
        # is given.
        if _factory is not None:
            _factory.validate_context(context)
        elif not getattr(context, "_factory_token", ""):
            # If no factory is supplied, allow direct contexts for
            # backward compat in existing tests, but log.
            logger.debug("RuntimeContext without factory token — test path.")
        self._context = context
        self._model = model
        self._boundary = context.boundary
        self._registry = context.registry
        self._factory = _factory

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
        # Also check mapping payloads for nested authoritative keys that
        # might be smuggled as dict values.
        if isinstance(output, Mapping):
            for k in ("to_authoritative", "to_fact"):
                if k in output:
                    raise AuthorityError("Second authority model is forbidden.")
                # Check nested dicts for authoritative smuggling
                for v in output.values():
                    if isinstance(v, Mapping) and k in v:  # type: ignore[no-redef]
                        raise AuthorityError("Second authority model is forbidden.")
                    if hasattr(v, "to_authoritative") or hasattr(v, "to_fact"):
                        raise AuthorityError("Second authority model is forbidden.")

    def _check_no_registry_injection(self, inputs: Mapping[str, Any]) -> None:
        """Refuse any request that tries to inject registry or boundary."""
        for forbidden in ("registry", "boundary", "evidence_registry", "authority_boundary"):
            if forbidden in inputs:
                raise AuthorityError(f"Request must not carry {forbidden!r}.")

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
        Deterministic request context wins: model cannot expand evidence
        scope, change situation/company/capability, or inject authority.
        """
        self._require_capability(AgentCapability.PROPOSE)
        # Capture deterministic request envelope — model cannot redefine.
        original_evidence_ids = tuple(evidence_ids)
        original_situation = self._context.situation_id
        original_company = self._context.company_id
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
            # Model output is untrusted — validate as opaque object first.
            self._validate_not_second_authority(model_output)
            # Check for nested authoritative payload.
            if isinstance(model_output, Mapping):
                for v in model_output.values():
                    if isinstance(v, Mapping):
                        for k in ("status", "amount", "verdict", "decision"):
                            if k in v:
                                raise AuthorityError(
                                    f"Model output smuggles nested key {k!r}."
                                )
            # Deterministic envelope wins: model cannot change case scope.
            for forbidden in ("situation_id", "company_id", "capability"):
                if forbidden in model_output and str(
                    model_output[forbidden]
                ) != str(
                    {
                        "situation_id": original_situation,
                        "company_id": original_company,
                        "capability": AgentCapability.PROPOSE.value,
                    }.get(forbidden)
                ):
                    raise AuthorityError(
                        f"Model must not redefine {forbidden!r}."
                    )
            # Model cannot expand evidence scope beyond the request.
            model_eids_raw = model_output.get("evidence_ids", evidence_ids)
            if isinstance(model_eids_raw, (list, tuple)):
                model_eids = tuple(str(x) for x in model_eids_raw)
                # Any new id outside original scope is a scope expansion.
                if set(model_eids) - set(original_evidence_ids):
                    raise AuthorityError("Model must not expand evidence scope.")
                # Also reject if model tries to change evidence metadata
                evidence_ids = model_eids
                evidence_dicts = self._resolve_refs(evidence_ids)
            # Model output is plain data — re-validate, never trust.
            proposal_type = str(model_output.get("proposal_type", proposal_type))
            uncertainty = str(model_output.get("uncertainty", uncertainty))
            rationale = str(model_output.get("rationale", rationale))
            target = model_output.get("target", target)
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

    def dispatch_request(self, request: RuntimeRequest) -> Any:
        """Dispatch an already-validated ``RuntimeRequest``.

        The request envelope is validated at construction (typed
        ``AgentCapability``, non-blank evidence_ids, no registry
        injection). This method consumes it without re-parsing
        authority — it is not another parser boundary.
        """
        # Capability is already typed and validated at construction.
        capability = request.capability
        inputs = request.inputs
        # Also check for smuggled authoritative keys in generic dispatch.
        if capability == AgentCapability.PROPOSE:
            for k in ("status", "amount", "verdict", "decision"):
                if k in inputs:
                    raise AuthorityError(
                        f"Proposal payload smuggles authoritative key {k!r}."
                    )
            for v in inputs.values():
                if isinstance(v, Mapping):
                    for k in ("status", "amount", "verdict", "decision"):
                        if k in v:
                            raise AuthorityError(
                                f"Proposal payload smuggles nested key {k!r}."
                            )
        if capability == AgentCapability.READ:
            return self.read(request.evidence_ids)
        if capability == AgentCapability.CORRELATE:
            return self.correlate(request.evidence_ids)
        if capability == AgentCapability.HYPOTHESIZE:
            return self.hypothesize(
                text=str(inputs.get("text", "")),
                evidence_ids=request.evidence_ids,
                uncertainty=str(inputs.get("uncertainty", "")),
            )
        if capability == AgentCapability.PROPOSE:
            return self.propose(
                proposal_type=str(inputs.get("proposal_type", inputs.get("action", ""))),
                evidence_ids=request.evidence_ids,
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

    def dispatch(
        self, capability: AgentCapability, inputs: Mapping[str, Any]
    ) -> Any:
        """Generic capability-gated dispatch (typed, registry-bound).

        For backward compat, accepts ``AgentCapability`` or string;
        internally it constructs a validated ``RuntimeRequest`` and
        delegates to ``dispatch_request`` so the request envelope is
        the single authority boundary.
        """
        if not isinstance(capability, AgentCapability):
            # Allow string for test of denied capability, but still gate.
            try:
                capability = AgentCapability(str(capability))
            except ValueError:
                msg = f"Capability {capability!r} outside authority."
                raise AuthorityError(msg) from None
        # Request must never carry registry/boundary injection — checked
        # at RuntimeRequest construction, but also check raw inputs early.
        self._check_no_registry_injection(inputs)
        # Build the typed request envelope — construction validates.
        # Evidence_ids are taken from inputs if present, else from
        # request.evidence_ids handling.
        evidence_ids = tuple(inputs.get("evidence_ids", inputs.get("evidence_refs", ())))
        # Validate each evidence_id is non-blank at request construction.
        request = RuntimeRequest(
            capability=capability,
            inputs=inputs,
            evidence_ids=evidence_ids,  # type: ignore[arg-type]
        )
        return self.dispatch_request(request)
