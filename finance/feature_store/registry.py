"""Feature registry — discovers and builds feature groups.

Maps each feature-group key to its builder module and provides a
:class:`FeatureRegistry` facade to build, look up, version, and validate
features. The registry mirrors the tenant-config override pattern used in
``finance/variance_engine/materiality.py`` (deterministic, no I/O, no
LLM).

Naming contract:
    Feature group keys and feature names are snake_case alphanumeric ids —
    the same rule the dataset contract (:class:`contracts.datasets
    .DatasetContractV1`) enforces for ``dataset_id``, and the metadata
    registry's ``feature:*`` entry kind convention
    (``business/metadata/registry.py``). :meth:`FeatureRegistry.naming_warnings`
    reports any violation.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping, Sequence
from types import ModuleType
from typing import cast

import polars as pl

from finance.feature_store.base import FeatureStoreError, validate_feature_frame

#: Feature group key → module implementing ``build_<group>_features``.
FEATURE_GROUPS: dict[str, str] = {
    "vendor": "finance.feature_store.vendor",
    "invoice": "finance.feature_store.invoice",
    "cashflow": "finance.feature_store.cashflow",
    "department": "finance.feature_store.department",
    "forecast": "finance.feature_store.forecast",
    "anomaly": "finance.feature_store.anomaly",
}

#: Version constant each group module must define.
_VERSION_ATTR = "FEATURE_VERSION"

#: Feature-name contract each group module must define.
_NAMES_ATTR = "FEATURE_NAMES"

#: Source-table contract each group module must define.
_SOURCE_ATTR = "SOURCE_TABLE"

#: Builder callable name per group (``build_<group>_features``).
def _builder_name(group: str) -> str:
    return f"build_{group}_features"


def _is_snake_case_id(value: str) -> bool:
    """Return whether ``value`` satisfies the contracts' snake_case id rule.

    Mirrors the id validation used by the formula contract
    (``contracts/formulas/__init__.py``): snake_case alphanumeric with
    optional underscores and no whitespace / path-hostile characters.
    """
    return value.replace("_", "").isalnum()


class FeatureLookupError(FeatureStoreError, KeyError):
    """Raised when a feature group is unknown or its module is broken."""


def _require_group_attr(
    module: ModuleType, attr: str, group: str
) -> str | tuple[str, ...]:
    """Return a required module constant, raising on a broken contract."""
    value = getattr(module, attr, None)
    if value is None:
        raise FeatureLookupError(
            f"feature group {group!r} module {module.__name__} must define "
            f"{attr!r}"
        )
    return cast("str | tuple[str, ...]", value)


class FeatureRegistry:
    """Build and inspect feature groups.

    The registry is deterministic and side-effect free at import time:
    group modules are imported lazily on first use, mirroring the
    tenant-config override pattern of the materiality engine.
    """

    def __init__(self, groups: Mapping[str, str] | None = None) -> None:
        """Build a registry over ``groups`` (defaults to ``FEATURE_GROUPS``)."""
        self._groups: dict[str, str] = dict(groups if groups is not None else FEATURE_GROUPS)

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def groups(self) -> list[str]:
        """Return the sorted feature-group keys."""
        return sorted(self._groups)

    def source_tables(self) -> dict[str, str]:
        """Return group → source table name (lineage metadata)."""
        return {group: self.source_table(group) for group in self.groups()}

    def version(self, group: str) -> str:
        """Return the semantic ``FEATURE_VERSION`` of ``group``.

        Raises:
            FeatureLookupError: When ``group`` is unknown or unversioned.
        """
        module = self._import_module(group)
        version = _require_group_attr(module, _VERSION_ATTR, group)
        if not isinstance(version, str):
            raise FeatureLookupError(
                f"feature group {group!r} FEATURE_VERSION must be a string"
            )
        return version

    def feature_names(self, group: str) -> tuple[str, ...]:
        """Return the stable output column contract of ``group``.

        Raises:
            FeatureLookupError: When ``group`` is unknown or the contract
                is missing.
        """
        module = self._import_module(group)
        names = _require_group_attr(module, _NAMES_ATTR, group)
        if not isinstance(names, tuple):
            raise FeatureLookupError(
                f"feature group {group!r} FEATURE_NAMES must be a tuple"
            )
        return names

    def source_table(self, group: str) -> str:
        """Return the physical source table of ``group``.

        Raises:
            FeatureLookupError: When ``group`` is unknown or lacks a
                ``SOURCE_TABLE`` constant.
        """
        module = self._import_module(group)
        table = _require_group_attr(module, _SOURCE_ATTR, group)
        if not isinstance(table, str):
            raise FeatureLookupError(
                f"feature group {group!r} SOURCE_TABLE must be a string"
            )
        return table

    def builder(self, group: str) -> Callable[[pl.DataFrame], pl.DataFrame]:
        """Return the ``build_<group>_features`` callable for ``group``.

        Raises:
            FeatureLookupError: When ``group`` is unknown or its builder is
                missing.
        """
        module = self._import_module(group)
        fn = getattr(module, _builder_name(group), None)
        if not callable(fn):
            raise FeatureLookupError(
                f"feature group {group!r} module {module.__name__} must "
                f"define callable {_builder_name(group)!r}"
            )
        return cast(Callable[[pl.DataFrame], pl.DataFrame], fn)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, group: str, df: pl.DataFrame) -> pl.DataFrame:
        """Build one feature group from a source frame.

        Args:
            group: Feature-group key registered in ``FEATURE_GROUPS``.
            df: The source polars frame expected by the group's builder
                (see each module's ``SOURCE_COLUMNS`` / docstring).

        Returns:
            The validated feature frame (``Decimal`` money, structural
            pandera checks applied).

        Raises:
            FeatureLookupError: When ``group`` is unknown.
            FeatureStoreError: When the builder's output violates the
                money-column or structural contract.
        """
        builder = self.builder(group)
        out = builder(df)
        if not isinstance(out, pl.DataFrame):
            raise FeatureStoreError(
                f"feature group {group!r} builder returned "
                f"{type(out).__name__}, expected polars.DataFrame"
            )
        validate_feature_frame(group, out)
        return out

    def build_all(
        self,
        frames: Mapping[str, pl.DataFrame],
        groups: Sequence[str] | None = None,
    ) -> dict[str, pl.DataFrame]:
        """Build every requested group from its source frame.

        ``frames`` is keyed by feature-group name. When ``groups`` is
        omitted, every group in the registry is built; a frame must be
        provided for each requested group.

        Args:
            frames: Mapping group → source polars frame.
            groups: Subset of groups to build (default: all).

        Returns:
            Mapping group → validated feature frame, in ``groups()`` order.

        Raises:
            FeatureLookupError: When a requested group is unknown.
            FeatureStoreError: When a frame is missing for a requested
                group.
        """
        keys = list(groups) if groups is not None else self.groups()
        missing = [group for group in keys if group not in frames]
        if missing:
            raise FeatureStoreError(
                f"no source frame provided for feature group(s): {', '.join(missing)}"
            )
        return {group: self.build(group, frames[group]) for group in keys}

    # ------------------------------------------------------------------
    # Naming validation (contracts/datasets alignment)
    # ------------------------------------------------------------------

    def naming_warnings(self) -> list[str]:
        """Return warnings for group keys / feature names violating the contract.

        Uses the same snake_case id rule that the formula contract
        (``contracts/formulas``) and the dataset contract
        (``contracts/datasets``) enforce — no whitespace, path-hostile
        characters, or non-alphanumeric symbols. Returns an empty list
        when the registry is clean.
        """
        warnings: list[str] = []
        for group in self.groups():
            if not _is_snake_case_id(group):
                warnings.append(f"feature group key {group!r} is not snake_case")
            for name in self.feature_names(group):
                if not _is_snake_case_id(name):
                    warnings.append(
                        f"feature name {name!r} in group {group!r} is not snake_case"
                    )
        return warnings

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _import_module(self, group: str) -> ModuleType:
        """Import (lazily) the module implementing ``group``.

        Raises:
            FeatureLookupError: When the group is unknown or its module
                cannot be imported.
        """
        if group not in self._groups:
            raise FeatureLookupError(f"unknown feature group {group!r}; known: {self.groups()}")
        module_name = self._groups[group]
        try:
            return importlib.import_module(module_name)
        except ImportError as exc:
            raise FeatureLookupError(
                f"failed to import feature group {group!r} module {module_name}: {exc}"
            ) from exc


#: Process-wide feature registry singleton (mirrors the materiality engine's
#: stateless facade pattern; construction is cheap and side-effect free).
FEATURE_REGISTRY = FeatureRegistry()


def build_features(
    frames: Mapping[str, pl.DataFrame],
    groups: Sequence[str] | None = None,
    registry: FeatureRegistry | None = None,
) -> dict[str, pl.DataFrame]:
    """Build feature groups — entry point for the deterministic feature store.

    Args:
        frames: Mapping group → source polars frame.
        groups: Subset of groups to build (default: all).
        registry: Override the registry (defaults to ``FEATURE_REGISTRY``).

    Returns:
        Mapping group → validated feature frame.

    Raises:
        FeatureLookupError: When a requested group is unknown.
        FeatureStoreError: When a source frame is missing or an output
            violates the money-column / structural contract.
    """
    reg = registry if registry is not None else FEATURE_REGISTRY
    return reg.build_all(frames, groups)


__all__ = [
    "FEATURE_GROUPS",
    "FEATURE_REGISTRY",
    "FeatureLookupError",
    "FeatureRegistry",
    "build_features",
]
