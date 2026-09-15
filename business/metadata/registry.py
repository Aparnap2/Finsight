"""Metadata Registry implementation — singleton plus discovery.

This module exposes the process-wide :data:`METADATA_REGISTRY` singleton
and the :func:`discover` entry point that populates it from the
authoritative sources in the codebase:

* the formula registry (``business/formula_registry/formulas.yaml``)
  → ``formula:*`` entries;
* the capability registry (``business/capabilities/registry.py``)
  → ``capability:*`` entries;
* the policy registry (``business/policies/registry.py``)
  → ``policy:*`` entries;
* the semantic data dictionary (``business/data_dictionary/registry.py``)
  → ``dataset:*`` entries.

Discovery is *best-effort*: a missing or malformed source is logged and
skipped rather than aborting the whole scan, so the registry degrades
gracefully when a subsystem is not installed.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from business.capabilities.models import Capability
from business.data_dictionary.models import TableMetadata
from business.formula_registry.models import FormulaDefinition
from business.metadata.models import (
    EntryKind,
    MetadataRegistry,
    RegistryEntry,
)
from business.policies.models import BusinessPolicy

logger = logging.getLogger(__name__)

#: Tags that identify an external standard worth recording as a reference.
_STANDARD_TAGS: frozenset[str] = frozenset({"gaap", "ifrs", "ias", "iso", "sox", "us_gaap"})

#: Registry id prefixes per entry kind.
_ID_PREFIX: dict[str, str] = {
    "formula": "formula:",
    "policy": "policy:",
    "connector": "connector:",
    "dataset": "dataset:",
    "schema": "schema:",
    "feature": "feature:",
    "capability": "capability:",
}

#: Maturity → lifecycle status mapping for capabilities.
_CAPABILITY_STATUS: dict[str, str] = {
    "planned": "discovery",
    "partial": "implemented",
    "full": "implemented",
    "production": "production",
}

METADATA_REGISTRY = MetadataRegistry()
"""Process-wide metadata registry singleton.

Populated by :func:`discover`. Starts empty so importing this module
stays cheap and side-effect free.
"""


# ---------------------------------------------------------------------------
# Entry builders
# ---------------------------------------------------------------------------


def _normalize_version(version: str) -> str:
    """Normalise a version string to ``MAJOR.MINOR.PATCH``.

    Handles the compact ``"1.0"`` form used by policies by appending the
    missing patch component.

    Args:
        version: The raw version string.

    Returns:
        A three-part semantic version.
    """
    parts = version.split(".")
    while len(parts) < 3:
        parts.append("0")
    return ".".join(parts)


def _formula_entry(formula: FormulaDefinition) -> RegistryEntry:
    """Build a registry entry from a :class:`FormulaDefinition`.

    Args:
        formula: The formula definition to record.

    Returns:
        A ``formula:*`` registry entry.
    """
    status = "production" if formula.valid_until is None else "deprecated"
    references = [tag for tag in formula.tags if tag in _STANDARD_TAGS]
    return RegistryEntry(
        id=f"formula:{formula.formula_id}",
        kind="formula",
        version=formula.version,
        owner=formula.owner,
        status=status,
        dependencies=[f"formula:{dep}" for dep in formula.depends_on],
        references=references,
        description=formula.description,
    )


def _capability_entry(capability: Capability) -> RegistryEntry:
    """Build a registry entry from a :class:`Capability`.

    Args:
        capability: The capability to record.

    Returns:
        A ``capability:*`` registry entry.
    """
    dependencies = (
        [f"capability:{capability.parent_id}"] if capability.parent_id is not None else []
    )
    return RegistryEntry(
        id=f"capability:{capability.capability_id}",
        kind="capability",
        version="1.0.0",
        owner=capability.owner,
        status=_CAPABILITY_STATUS.get(capability.maturity, "discovery"),
        dependencies=dependencies,
        references=[tag for tag in capability.tags if tag in _STANDARD_TAGS],
        description=capability.description,
    )


def _policy_entry(policy: BusinessPolicy) -> RegistryEntry:
    """Build a registry entry from a :class:`BusinessPolicy`.

    Args:
        policy: The policy to record.

    Returns:
        A ``policy:*`` registry entry.
    """
    active_until = policy.effective_until
    status = "production" if active_until is None else "deprecated"
    return RegistryEntry(
        id=f"policy:{policy.policy_id}",
        kind="policy",
        version=_normalize_version(policy.version),
        owner=policy.owner,
        status=status,
        references=[tag for tag in policy.tags if tag in _STANDARD_TAGS],
        description=policy.description,
    )


def _dataset_entry(table: TableMetadata) -> RegistryEntry:
    """Build a registry entry from a :class:`TableMetadata`.

    Args:
        table: The table metadata to record.

    Returns:
        A ``dataset:*`` registry entry.
    """
    return RegistryEntry(
        id=f"dataset:{table.table_name}",
        kind="dataset",
        version="1.0.0",
        owner=table.owner,
        status="production",
        references=[tag for tag in (table.business_name.lower().split()) if tag in _STANDARD_TAGS],
        description=table.definition,
    )


# ---------------------------------------------------------------------------
# Source collectors
# ---------------------------------------------------------------------------


def _collect_formulas() -> list[RegistryEntry]:
    """Collect ``formula:*`` entries from ``formulas.yaml``.

    Reads the YAML file directly (rather than importing the registry) so
    that discovery tolerates a temporarily broken formula package.

    Returns:
        List of formula registry entries.
    """
    path = Path(__file__).resolve().parent.parent / "formula_registry" / "formulas.yaml"
    if not path.is_file():
        logger.warning("metadata discovery: formulas.yaml not found at %s", path)
        return []

    try:
        payload: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        logger.warning("metadata discovery: failed to parse %s: %s", path, exc)
        return []

    records = payload.get("formulas", []) if isinstance(payload, dict) else []
    entries: list[RegistryEntry] = []
    for record in records:
        try:
            formula = FormulaDefinition.model_validate(record)
            entries.append(_formula_entry(formula))
        except Exception as exc:  # noqa: BLE001 - tolerate malformed records
            logger.warning("metadata discovery: skipping malformed formula record: %s", exc)
    return entries


def _collect_capabilities() -> list[RegistryEntry]:
    """Collect ``capability:*`` entries from the capability registry.

    Returns:
        List of capability registry entries.
    """
    try:
        from business.capabilities.registry import CAPABILITIES
    except ImportError as exc:
        logger.warning("metadata discovery: capabilities unavailable: %s", exc)
        return []
    return [_capability_entry(cap) for cap in CAPABILITIES]


def _collect_policies() -> list[RegistryEntry]:
    """Collect ``policy:*`` entries from the policy registry.

    Returns:
        List of policy registry entries.
    """
    try:
        from business.policies.registry import POLICY_REGISTRY
    except ImportError as exc:
        logger.warning("metadata discovery: policies unavailable: %s", exc)
        return []
    return [_policy_entry(policy) for policy in POLICY_REGISTRY.policies.values()]


def _collect_datasets() -> list[RegistryEntry]:
    """Collect ``dataset:*`` entries from the semantic data dictionary.

    Returns:
        List of dataset registry entries.
    """
    try:
        from business.data_dictionary.registry import DATA_DICTIONARY
    except ImportError as exc:
        logger.warning("metadata discovery: data dictionary unavailable: %s", exc)
        return []
    return [_dataset_entry(table) for table in DATA_DICTIONARY]


def _collect_connectors() -> list[RegistryEntry]:
    """Collect ``connector:*`` entries from the connector registry.

    The connector registry is optional at this layer; the empty result
    is returned when it is not yet available.

    Returns:
        List of connector registry entries (currently empty).
    """
    try:
        module = importlib.import_module("business.connectors.registry")
    except ImportError:
        return []

    connector_registry = getattr(module, "CONNECTOR_REGISTRY", None)
    if connector_registry is None:
        return []
    connectors: list[Any] = getattr(connector_registry, "all", lambda: [])()
    return [
        RegistryEntry(
            id=f"connector:{connector.connector_id}",
            kind="connector",
            version=_normalize_version(getattr(connector, "version", "1.0.0")),
            owner=getattr(connector, "owner", "Platform"),
            status="production",
            description=getattr(connector, "description", ""),
        )
        for connector in connectors
    ]


#: Ordered list of (kind, collector) pairs used by :func:`discover`.
_SOURCES: list[tuple[EntryKind, Callable[[], list[RegistryEntry]]]] = [
    ("formula", _collect_formulas),
    ("capability", _collect_capabilities),
    ("policy", _collect_policies),
    ("dataset", _collect_datasets),
    ("connector", _collect_connectors),
]


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def build_entries() -> list[RegistryEntry]:
    """Collect registry entries from every available source.

    Returns:
        All discovered registry entries, sorted by id.
    """
    entries: list[RegistryEntry] = []
    for _kind, collector in _SOURCES:
        entries.extend(collector())
    return sorted(entries, key=lambda e: e.id)


def discover() -> MetadataRegistry:
    """Populate :data:`METADATA_REGISTRY` from the authoritative sources.

    The scan replaces the previous contents (idempotent, safe to call
    repeatedly) and never raises — broken sources are skipped with a
    warning.

    Returns:
        The populated singleton :data:`METADATA_REGISTRY`.
    """
    entries = build_entries()
    for entry in entries:
        METADATA_REGISTRY._set(entry)  # noqa: SLF001 - force-replace by design
    logger.info("metadata discovery: registered %d entries", len(entries))
    return METADATA_REGISTRY
