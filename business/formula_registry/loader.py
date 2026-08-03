"""Loader for the elevated formula registry (``registry.yaml``).

Reads the registry YAML document produced by the platform build and
returns the canonical list of formula records. The YAML schema is
``finsight/formula-registry/registry-v1`` — the versioned contract in
:mod:`contracts.formulas` — and carries the elevated fields
(``inputs``, ``output``, ``references``, ``status``) alongside the
legacy ``FormulaDefinition`` fields.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from contracts.formulas import SCHEMA

#: Canonical location of the registry file, relative to this module.
_DEFAULT_PATH = Path(__file__).resolve().parent / "registry.yaml"


class RegistryFileError(ValueError):
    """Raised when the registry YAML is missing, malformed, or unversioned."""


def load_records(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Load the list of formula records from the registry YAML.

    Args:
        path: Explicit path to the registry file. Defaults to
            ``business/formula_registry/registry.yaml``.

    Returns:
        List of formula record dicts, each matching the registry-v1
        schema.

    Raises:
        RegistryFileError: If the file is missing, is not parseable, or
            does not declare the ``finsight/formula-registry/registry-v1``
            schema.
    """
    registry_path = Path(path) if path is not None else _DEFAULT_PATH
    if not registry_path.is_file():
        msg = f"Registry file not found: {registry_path}"
        raise RegistryFileError(msg)

    try:
        payload: Any = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        msg = f"Failed to parse registry YAML {registry_path}: {exc}"
        raise RegistryFileError(msg) from exc

    if not isinstance(payload, dict):
        msg = f"Registry YAML {registry_path} must contain a mapping"
        raise RegistryFileError(msg)

    schema = payload.get("schema")
    if schema != SCHEMA:
        msg = (
            f"Registry YAML {registry_path} declares unsupported schema "
            f"'{schema}' (expected '{SCHEMA}')"
        )
        raise RegistryFileError(msg)

    records = payload.get("formulas")
    if not isinstance(records, list):
        msg = f"Registry YAML {registry_path} must contain a 'formulas' list"
        raise RegistryFileError(msg)
    return list(records)


def record_by_id(
    records: list[dict[str, Any]],
    formula_id: str,
) -> dict[str, Any]:
    """Look up a formula record by its ``id``.

    Args:
        records: The list of formula records.
        formula_id: The formula identifier to find.

    Returns:
        The matching record.

    Raises:
        KeyError: If no record carries the given id.
    """
    for record in records:
        if record.get("id") == formula_id:
            return record
    msg = f"Formula '{formula_id}' not found in registry records"
    raise KeyError(msg)
