"""Tests for the deterministic feature store (``finance/feature_store/``).

Covers: feature groups discoverable / versioned, every builder running on
a small synthetic polars frame and returning a well-typed frame (pandera
structural schema + Decimal money-column checks), registry behaviour, and
naming-contract validation.
"""

# mypy: disable-error-code="untyped-decorator"

from __future__ import annotations

import re
from decimal import Decimal

import polars as pl
import pytest

from finance.feature_store import (
    FEATURE_GROUPS,
    FeatureLookupError,
    FeatureRegistry,
    build_features,
)
from finance.feature_store.base import (
    FEATURE_GROUP_SCHEMAS,
    FeatureStoreError,
    validate_feature_frame,
)

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

#: All registered feature-group keys (must mirror FEATURE_GROUPS).
ALL_GROUPS = ("vendor", "invoice", "cashflow", "department", "forecast", "anomaly")

#: Monetary feature columns per group (must stay polars Decimal).
MONEY_COLUMNS_BY_GROUP: dict[str, tuple[str, ...]] = {
    "vendor": (
        "vendor_total_amount",
        "vendor_avg_invoice_amount",
        "vendor_paid_amount",
        "vendor_open_amount",
        "vendor_concentration_ratio",
    ),
    "invoice": (
        "invoice_amount_total",
        "invoice_amount_avg",
        "invoice_amount_max",
        "invoice_amount_min",
        "invoice_paid_amount",
        "invoice_share_paid",
        "invoice_share_draft",
    ),
    "cashflow": (
        "cashflow_inflow_amount",
        "cashflow_outflow_amount",
        "cashflow_net_amount",
        "cashflow_coverage_ratio",
    ),
    "department": (
        "headcount_turnover_rate",
        "dept_total_compensation",
        "dept_comp_per_head",
    ),
    "forecast": (
        "forecast_amount_total",
        "forecast_amount_avg",
        "forecast_latest_amount_total",
        "forecast_share_of_entity",
    ),
    "anomaly": (
        "actual_amount",
        "budget_amount",
        "variance_amount",
        "variance_pct",
        "anomaly_abs_deviation",
        "anomaly_deviation_ratio",
    ),
}


# =============================================================================
# Synthetic source frames (small, hand-computed)
# =============================================================================


@pytest.fixture
def vendor_frame() -> pl.DataFrame:
    """Two vendors, four invoices: totals 300, paid 150, open 150.

    Vendor A total = 150, vendor B total = 150 → concentration = 0.50.
    """
    return pl.DataFrame(
        {
            "entity_id": ["e1", "e1", "e1", "e1"],
            "period": ["2026-01", "2026-01", "2026-01", "2026-01"],
            "vendor_name": ["A", "A", "B", "B"],
            "amount": [Decimal("100.00"), Decimal("50.00"), Decimal("50.00"), Decimal("100.00")],
            "status": ["paid", "draft", "paid", "open"],
        }
    )


@pytest.fixture
def invoice_frame() -> pl.DataFrame:
    """Three invoices: total 300, paid 150, draft 150, max 150, min 50."""
    return pl.DataFrame(
        {
            "entity_id": ["e1", "e1", "e1"],
            "period": ["2026-01", "2026-01", "2026-01"],
            "amount": [Decimal("100.00"), Decimal("50.00"), Decimal("150.00")],
            "category": ["cat_a", "cat_a", "cat_b"],
            "status": ["paid", "paid", "draft"],
        }
    )


@pytest.fixture
def cashflow_frame() -> pl.DataFrame:
    """Inflows (4*) 150, outflows (5*/6*) 50 → net 100, coverage 3.0."""
    return pl.DataFrame(
        {
            "entity_id": ["e1", "e1", "e1", "e1", "e1"],
            "period": ["2026-01", "2026-01", "2026-01", "2026-01", "2026-01"],
            "account_id": ["4010", "4011", "6010", "5010", "7010"],
            "amount": [
                Decimal("100.00"),
                Decimal("50.00"),
                Decimal("-30.00"),
                Decimal("-20.00"),
                Decimal("10.00"),
            ],
        }
    )


@pytest.fixture
def headcount_frame() -> pl.DataFrame:
    """Two departments; d1: hc 15, comp 150000; d2: hc 0 (degenerate)."""
    return pl.DataFrame(
        {
            "entity_id": ["e1", "e1", "e1"],
            "period": ["2026-01", "2026-01", "2026-01"],
            "department": ["d1", "d1", "d2"],
            "headcount": [10, 5, 0],
            "new_hires": [2, 1, 0],
            "departures": [1, 2, 1],
            "total_compensation": [Decimal("100000.00"), Decimal("50000.00"), Decimal("0.00")],
        }
    )


@pytest.fixture
def forecast_frame() -> pl.DataFrame:
    """d1: total 600 (latest 500), d2: total 400 (latest 300)."""
    return pl.DataFrame(
        {
            "entity_id": ["e1", "e1", "e1", "e1", "e1"],
            "period": ["2026-01", "2026-01", "2026-01", "2026-01", "2026-01"],
            "department": ["d1", "d1", "d1", "d2", "d2"],
            "amount": [
                Decimal("100.00"),
                Decimal("200.00"),
                Decimal("300.00"),
                Decimal("100.00"),
                Decimal("300.00"),
            ],
            "version": [1, 2, 2, 1, 3],
        }
    )


@pytest.fixture
def anomaly_frame() -> pl.DataFrame:
    """Three accounts: spike, deficit, and degenerate zero-budget."""
    return pl.DataFrame(
        {
            "entity_id": ["e1", "e1", "e1"],
            "period": ["2026-01", "2026-01", "2026-01"],
            "account_id": ["4010", "6010", "7010"],
            "department": ["Sales", "G&A", None],
            "actual_amount": [Decimal("600000.00"), Decimal("100000.00"), Decimal("50000.00")],
            "budget_amount": [Decimal("500000.00"), Decimal("250000.00"), Decimal("0.00")],
        }
    )


@pytest.fixture
def frames(
    vendor_frame: pl.DataFrame,
    invoice_frame: pl.DataFrame,
    cashflow_frame: pl.DataFrame,
    headcount_frame: pl.DataFrame,
    forecast_frame: pl.DataFrame,
    anomaly_frame: pl.DataFrame,
) -> dict[str, pl.DataFrame]:
    """Source frames for every feature group, keyed by group name."""
    return {
        "vendor": vendor_frame,
        "invoice": invoice_frame,
        "cashflow": cashflow_frame,
        "department": headcount_frame,
        "forecast": forecast_frame,
        "anomaly": anomaly_frame,
    }


# =============================================================================
# 1. Discovery & versioning
# =============================================================================


class TestFeatureGroups:
    """Feature groups are discoverable, versioned, and snake_case."""

    def test_feature_groups_are_registered(self) -> None:
        """All six expected groups are registered with a module path."""
        assert set(FEATURE_GROUPS) == set(ALL_GROUPS)
        for group, module in FEATURE_GROUPS.items():
            assert module == f"finance.feature_store.{group}"

    def test_registry_groups_sorted(self) -> None:
        """Registry returns the groups in deterministic sorted order."""
        registry = FeatureRegistry()
        assert registry.groups() == sorted(FEATURE_GROUPS)

    @pytest.mark.parametrize("group", ALL_GROUPS)
    def test_group_versioned(self, group: str) -> None:
        """Each group exposes a semantic MAJOR.MINOR.PATCH version."""
        registry = FeatureRegistry()
        version = registry.version(group)
        assert VERSION_RE.match(version) is not None, f"bad version {version!r} for {group}"

    @pytest.mark.parametrize("group", ALL_GROUPS)
    def test_group_has_stable_feature_names(self, group: str) -> None:
        """Each group declares a non-empty snake_case column contract."""
        registry = FeatureRegistry()
        names = registry.feature_names(group)
        assert names, f"group {group} declares no features"
        for name in names:
            assert name.replace("_", "").isalnum(), f"{name!r} is not snake_case"

    def test_naming_warnings_empty(self) -> None:
        """All registered group keys and feature names satisfy the contract."""
        registry = FeatureRegistry()
        assert registry.naming_warnings() == []

    def test_source_tables_mapped(self) -> None:
        """Every group maps to a documented physical source table."""
        registry = FeatureRegistry()
        tables = registry.source_tables()
        assert tables["vendor"] == "vendor_invoices"
        assert tables["invoice"] == "vendor_invoices"
        assert tables["cashflow"] == "actuals"
        assert tables["department"] == "headcount_data"
        assert tables["forecast"] == "forecast_lines"
        assert "budget_lines" in tables["anomaly"]


# =============================================================================
# 2. Builders produce well-typed frames
# =============================================================================


class TestBuilders:
    """Each builder runs on a synthetic frame and returns a well-typed frame."""

    @pytest.mark.parametrize("group", ALL_GROUPS)
    def test_builder_returns_validated_frame(
        self, frames: dict[str, pl.DataFrame], group: str
    ) -> None:
        """The registry builds a frame matching the FEATURE_NAMES contract."""
        registry = FeatureRegistry()
        out = registry.build(group, frames[group])
        assert isinstance(out, pl.DataFrame)
        assert out.columns == list(registry.feature_names(group))
        # Structural pandera schema passes (exercised inside build via
        # validate_feature_frame; assert here for clarity).
        validate_feature_frame(group, out)
        # Every group has at least one row for the fixture.
        assert out.height >= 1

    @pytest.mark.parametrize("group", ALL_GROUPS)
    def test_money_columns_are_decimal(
        self, frames: dict[str, pl.DataFrame], group: str
    ) -> None:
        """Every monetary feature column is a polars Decimal dtype."""
        out = FeatureRegistry().build(group, frames[group])
        for col in MONEY_COLUMNS_BY_GROUP[group]:
            assert isinstance(out.schema[col], pl.Decimal), (
                f"{group}.{col} dtype {out.schema[col]} is not Decimal"
            )

    def test_build_features_entry_point(self, frames: dict[str, pl.DataFrame]) -> None:
        """The package entry point builds every group."""
        built = build_features(frames)
        assert set(built) == set(FEATURE_GROUPS)
        assert all(isinstance(frame, pl.DataFrame) for frame in built.values())

    def test_build_features_subset(self, frames: dict[str, pl.DataFrame]) -> None:
        """The entry point honours the requested group subset."""
        built = build_features(frames, groups=["vendor", "cashflow"])
        assert set(built) == {"vendor", "cashflow"}


# =============================================================================
# 3. Hand-computed values
# =============================================================================


class TestVendorValues:
    """Vendor features on a tiny hand-computed frame."""

    def test_vendor_totals(self, vendor_frame: pl.DataFrame) -> None:
        """Counts, totals, paid/open splits and concentration are exact."""
        out = FeatureRegistry().build("vendor", vendor_frame)
        row = out.row(0, named=True)
        assert row["vendor_count"] == 2
        assert row["vendor_invoice_count"] == 4
        assert row["vendor_total_amount"] == Decimal("300.00")
        assert row["vendor_avg_invoice_amount"] == Decimal("75.00")
        assert row["vendor_paid_amount"] == Decimal("150.00")
        assert row["vendor_open_amount"] == Decimal("150.00")
        assert row["vendor_concentration_ratio"] == Decimal("0.50")


class TestInvoiceValues:
    """Invoice-book features on a tiny hand-computed frame."""

    def test_invoice_totals(self, invoice_frame: pl.DataFrame) -> None:
        """Counts, monetary totals, and payment shares are exact."""
        out = FeatureRegistry().build("invoice", invoice_frame)
        row = out.row(0, named=True)
        assert row["invoice_count_total"] == 3
        assert row["invoice_amount_total"] == Decimal("300.00")
        assert row["invoice_amount_avg"] == Decimal("100.00")
        assert row["invoice_amount_max"] == Decimal("150.00")
        assert row["invoice_amount_min"] == Decimal("50.00")
        assert row["invoice_category_count"] == 2
        assert row["invoice_status_count"] == 2
        assert row["invoice_paid_amount"] == Decimal("150.00")
        assert row["invoice_share_paid"] == Decimal("0.50")
        assert row["invoice_share_draft"] == Decimal("0.50")


class TestCashflowValues:
    """Cash-flow proxy features on a tiny hand-computed frame."""

    def test_cashflow_totals(self, cashflow_frame: pl.DataFrame) -> None:
        """Inflow/outflow classification by account prefix is exact."""
        out = FeatureRegistry().build("cashflow", cashflow_frame)
        row = out.row(0, named=True)
        assert row["cashflow_inflow_amount"] == Decimal("150.00")
        assert row["cashflow_outflow_amount"] == Decimal("50.00")
        assert row["cashflow_net_amount"] == Decimal("100.00")
        assert row["cashflow_coverage_ratio"] == Decimal("3.00")

    def test_cashflow_zero_outflow_guard(self) -> None:
        """Coverage is 0 when outflow is 0 (degenerate, documented)."""
        frame = pl.DataFrame(
            {
                "entity_id": ["e2"],
                "period": ["2026-02"],
                "account_id": ["6010"],
                "amount": [Decimal("-40.00")],
            }
        )
        out = FeatureRegistry().build("cashflow", frame)
        row = out.row(0, named=True)
        assert row["cashflow_inflow_amount"] == Decimal("0.00")
        assert row["cashflow_coverage_ratio"] == Decimal("0.00")


class TestDepartmentValues:
    """Department features on a tiny hand-computed frame."""

    def test_department_totals(self, headcount_frame: pl.DataFrame) -> None:
        """Headcount, turnover, and per-head compensation are exact."""
        out = FeatureRegistry().build("department", headcount_frame)
        d1 = out.filter(pl.col("department") == "d1").row(0, named=True)
        d2 = out.filter(pl.col("department") == "d2").row(0, named=True)
        assert d1["headcount_total"] == 15
        assert d1["headcount_new_hires"] == 3
        assert d1["headcount_departures"] == 3
        assert d1["headcount_net_change"] == 0
        assert d1["headcount_turnover_rate"] == Decimal("0.20")
        assert d1["dept_total_compensation"] == Decimal("150000.00")
        assert d1["dept_comp_per_head"] == Decimal("10000.00")
        # d2 has zero headcount: net change -1, guarded ratios are 0.
        assert d2["headcount_total"] == 0
        assert d2["headcount_net_change"] == -1
        assert d2["headcount_turnover_rate"] == Decimal("0.00")
        assert d2["dept_comp_per_head"] == Decimal("0.00")


class TestForecastValues:
    """Forecast features on a tiny hand-computed frame."""

    def test_forecast_totals(self, forecast_frame: pl.DataFrame) -> None:
        """Totals, latest-version totals, and entity shares are exact."""
        out = FeatureRegistry().build("forecast", forecast_frame)
        d1 = out.filter(pl.col("department") == "d1").row(0, named=True)
        d2 = out.filter(pl.col("department") == "d2").row(0, named=True)
        assert d1["forecast_line_count"] == 3
        assert d1["forecast_version_max"] == 2
        assert d1["forecast_amount_total"] == Decimal("600.00")
        assert d1["forecast_amount_avg"] == Decimal("200.00")
        assert d1["forecast_latest_amount_total"] == Decimal("500.00")
        assert d1["forecast_share_of_entity"] == Decimal("0.60")
        assert d2["forecast_version_max"] == 3
        assert d2["forecast_amount_total"] == Decimal("400.00")
        assert d2["forecast_latest_amount_total"] == Decimal("300.00")
        assert d2["forecast_share_of_entity"] == Decimal("0.40")


class TestAnomalyValues:
    """Anomaly features on a tiny hand-computed frame."""

    def test_anomaly_flags(self, anomaly_frame: pl.DataFrame) -> None:
        """Variance, deviation, and deterministic anomaly flags are exact."""
        out = FeatureRegistry().build("anomaly", anomaly_frame)
        rows = {r["account_id"]: r for r in out.rows(named=True)}
        spike = rows["4010"]
        assert spike["variance_amount"] == Decimal("100000.00")
        assert spike["variance_pct"] == Decimal("20.00")
        assert spike["anomaly_abs_deviation"] == Decimal("100000.00")
        assert spike["anomaly_deviation_ratio"] == Decimal("0.20")
        assert spike["anomaly_flag_spike"] is False
        assert spike["anomaly_flag_deficit"] is False
        assert spike["anomaly_flag_material"] is True

        deficit = rows["6010"]
        assert deficit["variance_amount"] == Decimal("-150000.00")
        assert deficit["variance_pct"] == Decimal("-60.00")
        assert deficit["anomaly_flag_spike"] is False
        assert deficit["anomaly_flag_deficit"] is True
        assert deficit["anomaly_flag_material"] is True

        degenerate = rows["7010"]
        assert degenerate["budget_amount"] == Decimal("0.00")
        assert degenerate["variance_pct"] == Decimal("0.00")  # guarded
        assert degenerate["anomaly_deviation_ratio"] == Decimal("0.00")
        assert degenerate["anomaly_flag_material"] is False


# =============================================================================
# 4. Registry behaviour & failure modes
# =============================================================================


class TestRegistryBehaviour:
    """Lookup, missing frames, and money-dtype enforcement."""

    def test_unknown_group_raises(self) -> None:
        """Unknown groups fail with FeatureLookupError."""
        registry = FeatureRegistry()
        with pytest.raises(FeatureLookupError):
            registry.build("nope", pl.DataFrame())
        with pytest.raises(FeatureLookupError):
            registry.version("nope")

    def test_missing_frame_raises(self, vendor_frame: pl.DataFrame) -> None:
        """build_all fails when a requested group has no source frame."""
        registry = FeatureRegistry()
        with pytest.raises(FeatureStoreError):
            registry.build_all({"vendor": vendor_frame})

    def test_float_money_rejected(self) -> None:
        """A float monetary column is rejected with FeatureStoreError."""
        frame = pl.DataFrame(
            {
                "entity_id": ["e1"],
                "period": ["2026-01"],
                "vendor_name": ["A"],
                "amount": [100.5],  # float, not Decimal
                "status": ["paid"],
            }
        )
        with pytest.raises(FeatureStoreError):
            FeatureRegistry().build("vendor", frame)

    def test_missing_source_column_rejected(self) -> None:
        """A builder missing a required source column fails."""
        frame = pl.DataFrame(
            {
                "entity_id": ["e1"],
                "period": ["2026-01"],
                "amount": [Decimal("10.00")],  # missing vendor_name/status
            }
        )
        with pytest.raises(FeatureStoreError):
            FeatureRegistry().build("vendor", frame)

    def test_builder_returns_non_frame_rejected(self) -> None:
        """A builder returning a non-frame object is rejected."""
        registry = FeatureRegistry()
        # Monkeypatch the builder to return something non-polars.
        original = registry.builder
        setattr(registry, "builder", lambda group: lambda _df: "not a frame")  # noqa: B010
        try:
            with pytest.raises(FeatureStoreError):
                registry.build("vendor", pl.DataFrame())
        finally:
            setattr(registry, "builder", original)  # noqa: B010

    def test_schema_registry_covers_all_groups(self) -> None:
        """Every registered group has a structural pandera schema."""
        assert set(FEATURE_GROUP_SCHEMAS) == set(FEATURE_GROUPS)
