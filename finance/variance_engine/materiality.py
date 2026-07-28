"""
Materiality Engine for FinSight FP&A Intelligence Platform.

Determines which variances are "material" (significant enough to investigate)
using a tiered sensitivity model. 100% deterministic — no external dependencies.

Account Sensitivity Tiers:
    CRITICAL — Revenue, Cash (lowest thresholds)
    HIGH     — COGS, Gross Margin
    MEDIUM   — Operating Expenses
    LOW      — Non-material accounts
"""

import fnmatch
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel

from shared.models.state import Variance


# =============================================================================
# Sensitivity Tiers
# =============================================================================


class SensitivityTier(str, Enum):
    """Sensitivity classification for variance materiality thresholds."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# =============================================================================
# Materiality Rule & Configuration
# =============================================================================


class MaterialityRule(BaseModel):
    """A single materiality rule defining thresholds for account matching.

    A rule can match accounts by:
    - ``account_code``: exact account code match
    - ``account_pattern``: glob pattern (e.g. ``"4*"`` for all revenue accounts)
    - Neither: acts as a default rule for the tier
    """

    account_code: Optional[str] = None
    account_pattern: Optional[str] = None
    tier: SensitivityTier
    pct_threshold: Decimal
    abs_threshold: Decimal
    combined_rule: Optional[str] = "any"  # "any" | "both"

    def matches(self, account_code: str) -> bool:
        """Check whether this rule applies to the given account code."""
        if self.account_code is not None:
            return self.account_code == account_code
        if self.account_pattern is not None:
            return fnmatch.fnmatch(account_code, self.account_pattern)
        return False  # default rules match via tier lookup, not this method


# ---------------------------------------------------------------------------
# Default threshold values (as Decimals — no float rounding)
# ---------------------------------------------------------------------------

DEFAULT_CRITICAL_PCT = Decimal("0.03")
DEFAULT_CRITICAL_ABS = Decimal("50000")

DEFAULT_HIGH_PCT = Decimal("0.05")
DEFAULT_HIGH_ABS = Decimal("100000")

DEFAULT_MEDIUM_PCT = Decimal("0.10")
DEFAULT_MEDIUM_ABS = Decimal("250000")

DEFAULT_LOW_PCT = Decimal("0.15")
DEFAULT_LOW_ABS = Decimal("500000")


# ---------------------------------------------------------------------------
# Default account-to-tier mappings (glob patterns)
# ---------------------------------------------------------------------------

DEFAULT_TIER_MAP: dict[SensitivityTier, list[str]] = {
    SensitivityTier.CRITICAL: ["4*"],  # Revenue accounts typically start with 4
    SensitivityTier.HIGH: ["5*"],      # COGS accounts typically start with 5
    SensitivityTier.MEDIUM: ["6*"],    # OpEx accounts typically start with 6
    SensitivityTier.LOW: ["7*", "8*", "9*"],  # Non-material
}


class MaterialityConfig(BaseModel):
    """Complete materiality configuration with tier-based rules."""

    tiers: dict[SensitivityTier, list[MaterialityRule]]

    @classmethod
    def default(cls) -> "MaterialityConfig":
        """Build the default materiality configuration.

        Each tier gets a default rule (no account_code / account_pattern) and
        a set of pattern-based rules for account classification.
        """
        tiers: dict[SensitivityTier, list[MaterialityRule]] = {
            SensitivityTier.CRITICAL: [
                MaterialityRule(
                    account_code=None,
                    account_pattern=None,
                    tier=SensitivityTier.CRITICAL,
                    pct_threshold=DEFAULT_CRITICAL_PCT,
                    abs_threshold=DEFAULT_CRITICAL_ABS,
                    combined_rule="any",
                ),
            ],
            SensitivityTier.HIGH: [
                MaterialityRule(
                    account_code=None,
                    account_pattern=None,
                    tier=SensitivityTier.HIGH,
                    pct_threshold=DEFAULT_HIGH_PCT,
                    abs_threshold=DEFAULT_HIGH_ABS,
                    combined_rule="any",
                ),
            ],
            SensitivityTier.MEDIUM: [
                MaterialityRule(
                    account_code=None,
                    account_pattern=None,
                    tier=SensitivityTier.MEDIUM,
                    pct_threshold=DEFAULT_MEDIUM_PCT,
                    abs_threshold=DEFAULT_MEDIUM_ABS,
                    combined_rule="any",
                ),
            ],
            SensitivityTier.LOW: [
                MaterialityRule(
                    account_code=None,
                    account_pattern=None,
                    tier=SensitivityTier.LOW,
                    pct_threshold=DEFAULT_LOW_PCT,
                    abs_threshold=DEFAULT_LOW_ABS,
                    combined_rule="any",
                ),
            ],
        }
        # Add pattern-based classification rules for each tier
        for tier, patterns in DEFAULT_TIER_MAP.items():
            for pattern in patterns:
                tiers[tier].append(
                    MaterialityRule(
                        account_code=None,
                        account_pattern=pattern,
                        tier=tier,
                        pct_threshold=_default_pct(tier),
                        abs_threshold=_default_abs(tier),
                        combined_rule="any",
                    )
                )
        return cls(tiers=tiers)


def _default_pct(tier: SensitivityTier) -> Decimal:
    mapping = {
        SensitivityTier.CRITICAL: DEFAULT_CRITICAL_PCT,
        SensitivityTier.HIGH: DEFAULT_HIGH_PCT,
        SensitivityTier.MEDIUM: DEFAULT_MEDIUM_PCT,
        SensitivityTier.LOW: DEFAULT_LOW_PCT,
    }
    return mapping[tier]


def _default_abs(tier: SensitivityTier) -> Decimal:
    mapping = {
        SensitivityTier.CRITICAL: DEFAULT_CRITICAL_ABS,
        SensitivityTier.HIGH: DEFAULT_HIGH_ABS,
        SensitivityTier.MEDIUM: DEFAULT_MEDIUM_ABS,
        SensitivityTier.LOW: DEFAULT_LOW_ABS,
    }
    return mapping[tier]


# =============================================================================
# Tenant-specific Configuration
# =============================================================================


class TenantMaterialityConfig(BaseModel):
    """Per-tenant materiality overrides.

    Tenant-specific rules are merged on top of a base (global) configuration.
    """

    tenant_id: str
    rules: list[MaterialityRule]
    base_config: MaterialityConfig

    def merged_config(self) -> MaterialityConfig:
        """Merge tenant rules into the base config.

        Tenant rules take precedence over base rules for the same account.
        Tenant rules with an account_code or account_pattern are added to
        their respective tier; if a base rule exists with the same
        account_code, it is replaced.
        """
        merged_tiers: dict[SensitivityTier, list[MaterialityRule]] = {}
        for tier in SensitivityTier:
            base_rules = list(self.base_config.tiers.get(tier, []))
            tenant_rules = [r for r in self.rules if r.tier == tier]

            # Remove any base rules that have the same account_code as a tenant rule
            tenant_codes = {r.account_code for r in tenant_rules if r.account_code is not None}
            base_rules = [
                r
                for r in base_rules
                if r.account_code is None or r.account_code not in tenant_codes
            ]

            merged_tiers[tier] = base_rules + tenant_rules

        return MaterialityConfig(tiers=merged_tiers)


# =============================================================================
# Assessment Output
# =============================================================================


class MaterialityAssessment(BaseModel):
    """Result of assessing a single variance against materiality rules."""

    variance_id: str
    account_id: str
    account_name: str
    tier: SensitivityTier
    variance_pct: Decimal
    variance_abs: Decimal
    pct_exceeds: bool
    abs_exceeds: bool
    is_material: bool
    rule_matched: Optional[MaterialityRule] = None


# =============================================================================
# Materiality Engine
# =============================================================================


class MaterialityEngine:
    """Determines which variances are material for investigation.

    The engine is 100% deterministic and uses a tier-based threshold system.
    Accounts are classified into sensitivity tiers via glob pattern matching.
    """

    def __init__(self, config: Optional[MaterialityConfig] = None):
        self.config = config if config is not None else MaterialityConfig.default()

    # ------------------------------------------------------------------
    # Single assessment
    # ------------------------------------------------------------------

    def assess(self, variance: Variance) -> MaterialityAssessment:
        """Assess a single variance against materiality rules.

        Steps:
        1. Determine the account's sensitivity tier.
        2. Find the best matching rule (exact account_code > pattern > default).
        3. Compare variance against thresholds.
        4. Apply the combined_rule (``any`` | ``both``).
        """
        tier = self.classify_account(variance.account_id)
        rule = self._find_rule(variance.account_id, tier)

        # Use absolute values for threshold comparison
        abs_variance = abs(variance.variance_amount)
        abs_pct = abs(variance.variance_pct)

        pct_exceeds = abs_pct > rule.pct_threshold * Decimal("100")
        abs_exceeds = abs_variance > rule.abs_threshold

        if rule.combined_rule == "both":
            is_material = pct_exceeds and abs_exceeds
        else:
            is_material = pct_exceeds or abs_exceeds

        # Overwrite is_material on the variance itself
        variance.is_material = is_material

        return MaterialityAssessment(
            variance_id=variance.account_id,
            account_id=variance.account_id,
            account_name=variance.account_name,
            tier=tier,
            variance_pct=variance.variance_pct,
            variance_abs=variance.variance_amount,
            pct_exceeds=pct_exceeds,
            abs_exceeds=abs_exceeds,
            is_material=is_material,
            rule_matched=rule,
        )

    # ------------------------------------------------------------------
    # Batch assessment
    # ------------------------------------------------------------------

    def assess_batch(self, variances: list[Variance]) -> list[MaterialityAssessment]:
        """Assess all variances and return assessments sorted by severity.

        Severity is determined by:
        1. Material variances come before non-material.
        2. Within each group, larger absolute variances come first.
        """
        assessments = [self.assess(v) for v in variances]
        assessments.sort(
            key=lambda a: (
                not a.is_material,         # material first
                -abs(a.variance_abs),       # larger abs variance first
            ),
        )
        return assessments

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def get_material_variances(self, variances: list[Variance]) -> list[Variance]:
        """Filter to only material variances (mutates is_material in-place)."""
        for v in variances:
            if not v.is_material:
                self.assess(v)  # ensures is_material is set
        return [v for v in variances if v.is_material]

    # ------------------------------------------------------------------
    # Account classification
    # ------------------------------------------------------------------

    def classify_account(self, account_code: str) -> SensitivityTier:
        """Determine the sensitivity tier for an account code.

        Checks exact account_code matches first (for tenant overrides),
        then glob patterns, then falls back to MEDIUM.
        """
        priority = [
            SensitivityTier.CRITICAL,
            SensitivityTier.HIGH,
            SensitivityTier.MEDIUM,
            SensitivityTier.LOW,
        ]

        # 1. Exact account_code match (tenant overrides, etc.)
        for tier in priority:
            for rule in self.config.tiers.get(tier, []):
                if rule.account_code == account_code:
                    return tier

        # 2. Glob pattern match
        for tier in priority:
            for rule in self.config.tiers.get(tier, []):
                if rule.account_pattern is not None:
                    if fnmatch.fnmatch(account_code, rule.account_pattern):
                        return tier

        # 3. Fall back to MEDIUM
        return SensitivityTier.MEDIUM

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_rule(self, account_code: str, tier: SensitivityTier) -> MaterialityRule:
        """Find the best-matching rule for an account within its tier.

        Priority:
        1. Exact ``account_code`` match within the tier.
        2. ``account_pattern`` match within the tier.
        3. Default rule (no code, no pattern) within the tier.
        """
        rules = self.config.tiers.get(tier, [])

        # 1. Exact code match
        for rule in rules:
            if rule.account_code == account_code:
                return rule

        # 2. Pattern match
        for rule in rules:
            if rule.account_pattern is not None and fnmatch.fnmatch(account_code, rule.account_pattern):
                return rule

        # 3. Default rule (no account_code and no account_pattern)
        for rule in rules:
            if rule.account_code is None and rule.account_pattern is None:
                return rule

        # Fallback: should never happen since every tier has a default rule
        return MaterialityRule(
            account_code=None,
            account_pattern=None,
            tier=tier,
            pct_threshold=_default_pct(tier),
            abs_threshold=_default_abs(tier),
            combined_rule="any",
        )
