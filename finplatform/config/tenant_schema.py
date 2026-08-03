"""Tenant configuration schema and loader (Layer 0).

Defines the ``tenant.yaml`` schema (``TenantConfig`` and nested models) plus
the YAML loading entry points used across the platform. This module imports
only the standard library, PyYAML, and pydantic — it must never import
shared/finance/agents/apps.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class TenantConfigError(Exception):
    """Raised when a tenant config cannot be located, parsed, or validated."""


class CompanyInfo(BaseModel):
    """Legal entity information for a tenant's company."""

    name: str
    legal_name: str


class Materiality(BaseModel):
    """Materiality thresholds: ``amount`` in tenant currency, ``pct`` in percent."""

    amount: Decimal
    pct: Decimal


class ApprovalLimits(BaseModel):
    """Approval authority limits per role (in tenant currency)."""

    manager: Decimal
    director: Decimal
    cfo: Decimal


class FeatureFlags(BaseModel):
    """Boolean feature toggles for a tenant (all default off)."""

    forecasting: bool = False
    recommendations: bool = False
    rag: bool = False
    ml: bool = False


class TenantConfig(BaseModel):
    """Immutable per-tenant configuration loaded from ``tenants/<id>/tenant.yaml``."""

    tenant_id: str
    company: CompanyInfo
    currency: str = Field(pattern=r"^[A-Z]{3}$", description="ISO 4217 currency code")
    fiscal_year_start_month: int = Field(ge=1, le=12, description="1 = January .. 12 = December")
    materiality: Materiality
    approval_limits: ApprovalLimits
    tax_regime: str | None = None
    sox_enabled: bool
    connectors: list[str]
    features: FeatureFlags

    model_config = ConfigDict(frozen=True)

    @classmethod
    def load(cls, tenant_id: str, root: Path | None = None) -> TenantConfig:
        """Load and validate a single tenant's configuration.

        Reads ``<root>/tenants/<tenant_id>/tenant.yaml`` where ``root``
        defaults to the repository root (located via the module path).
        Raises :class:`TenantConfigError` for a missing file, unparseable
        YAML, or schema validation failure.
        """
        repo_root = root if root is not None else cls._locate_root()
        path = repo_root / "tenants" / tenant_id / "tenant.yaml"
        if not path.is_file():
            # Demo tenants live under tenants/demo/<id>/; fall back so that
            # both `load("acme-corp")` and `load_all()` resolve them.
            demo_path = repo_root / "tenants" / "demo" / tenant_id / "tenant.yaml"
            if demo_path.is_file():
                path = demo_path
            else:
                raise TenantConfigError(f"tenant config not found: {path}")
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise TenantConfigError(f"invalid YAML in {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise TenantConfigError(f"tenant config must be a mapping: {path}")
        try:
            return cls(tenant_id=tenant_id, **raw)
        except ValidationError as exc:
            raise TenantConfigError(f"invalid tenant config {path}: {exc}") from exc

    @classmethod
    def load_all(cls) -> dict[str, TenantConfig]:
        """Load every demo tenant under ``tenants/demo/*/tenant.yaml``.

        Returns a mapping of ``tenant_id`` → validated config, with the
        scan order sorted for deterministic results.
        """
        repo_root = cls._locate_root()
        demo_dir = repo_root / "tenants" / "demo"
        if not demo_dir.is_dir():
            raise TenantConfigError(f"demo tenants directory not found: {demo_dir}")
        configs: dict[str, TenantConfig] = {}
        for tenant_dir in sorted(demo_dir.iterdir()):
            if (tenant_dir / "tenant.yaml").is_file():
                config = cls.load(tenant_dir.name, root=repo_root)
                configs[config.tenant_id] = config
        return configs

    @staticmethod
    def _locate_root() -> Path:
        """Return the repository root (first ancestor holding a ``tenants/`` dir)."""
        current = Path(__file__).resolve().parent
        for candidate in (current, *current.parents):
            if (candidate / "tenants").is_dir():
                return candidate
        raise TenantConfigError("unable to locate repository root (no tenants/ directory found)")
