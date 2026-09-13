"""LLMProvider protocol: the single seam for all LLM calls.

Domain call sites MUST depend on this protocol only — no direct SDK imports.
Strict Pydantic validation of structured output happens at this boundary:
unknown fields are rejected regardless of the schema's ``extra`` setting,
and type errors surface as :class:`SchemaMismatchError`.
"""

from __future__ import annotations

import json
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ValidationError

from shared.llm.errors import SchemaMismatchError
from shared.llm.types import InvestigationPrompt, ModelMetadata, ProviderHealth


@runtime_checkable
class LLMProvider(Protocol):
    """Swappable LLM backend. All methods are credential-safe."""

    def generate_structured[T: BaseModel](
        self, prompt: InvestigationPrompt | str, response_schema: type[T]
    ) -> T:
        """Return schema-valid structured output or raise a ProviderError."""
        ...

    def health_check(self) -> ProviderHealth:
        """Report liveness; unhealthy providers trigger P3 fallback."""
        ...

    def model_metadata(self) -> ModelMetadata:
        """Return model/cost identity for audit logging (no secrets)."""
        ...


def validate_structured_output[T: BaseModel](data: object, response_schema: type[T]) -> T:
    """Strictly validate raw provider output against ``response_schema``.

    Args:
        data: Raw decoded JSON (dict), JSON string, or BaseModel instance.
        response_schema: Target Pydantic model. Unknown fields are always
            rejected, even if the schema permits extra fields.

    Raises:
        SchemaMismatchError: On unknown fields, wrong types, bad JSON, or any
            Pydantic validation failure. Messages never include secrets
            (payloads carry no credentials by construction).
    """
    schema_name = getattr(response_schema, "__name__", str(response_schema))
    if not (isinstance(response_schema, type) and issubclass(response_schema, BaseModel)):
        raise SchemaMismatchError(
            f"response_schema must be a BaseModel subclass, got {schema_name}"
        )

    payload: object = data
    if isinstance(payload, BaseModel):
        payload = payload.model_dump()
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (json.JSONDecodeError, ValueError) as exc:
            raise SchemaMismatchError(f"output is not valid JSON for {schema_name}") from exc
    if not isinstance(payload, dict):
        raise SchemaMismatchError(f"output for {schema_name} must be a JSON object")

    allowed = set(response_schema.model_fields.keys())
    unknown = sorted(set(payload.keys()) - allowed)
    if unknown:
        raise SchemaMismatchError(f"unknown fields for {schema_name}: {unknown}")

    try:
        return response_schema.model_validate(payload, strict=True)
    except ValidationError as exc:
        raise SchemaMismatchError(
            f"schema validation failed for {schema_name}: "
            f"{exc.errors(include_url=False, include_context=False)}"
        ) from exc
