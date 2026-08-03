"""Tests for forecast error metrics — MAE, RMSE, MAPE, Precision@K."""
from __future__ import annotations

from decimal import Decimal

import pytest

from finance.evaluation.metrics import (
    MeanAbsoluteError,
    MeanAbsolutePercentageError,
    PrecisionAtK,
    RootMeanSquaredError,
    _as_decimal,
)


class TestAsDecimal:
    def test_accepts_decimal_int_str(self) -> None:
        assert _as_decimal(Decimal("1.5")) == Decimal("1.5")
        assert _as_decimal(5) == Decimal("5")
        assert _as_decimal("2.25") == Decimal("2.25")

    def test_rejects_float(self) -> None:
        with pytest.raises(TypeError):
            _as_decimal(1.5)


class TestMeanAbsoluteError:
    def test_hand_computed_value(self) -> None:
        # actual=[10,20,30], predicted=[10,25,25] → errors 0,5,5 → MAE 3.333...
        mae = MeanAbsoluteError.compute([10, 20, 30], [10, 25, 25])
        assert mae == Decimal("3.333333333333333333333333333")

    def test_perfect_forecast_is_zero(self) -> None:
        assert MeanAbsoluteError.compute([1, 2, 3], [1, 2, 3]) == Decimal("0")

    def test_string_values_coerced(self) -> None:
        assert MeanAbsoluteError.compute(["10", "20"], [10, 30]) == Decimal("5")

    def test_empty_returns_none(self) -> None:
        assert MeanAbsoluteError.compute([], []) is None

    def test_length_mismatch_returns_none(self) -> None:
        assert MeanAbsoluteError.compute([1, 2], [1]) is None


class TestRootMeanSquaredError:
    def test_hand_computed_value(self) -> None:
        # errors 0,5,5 → mean_sq = 50/3 = 16.666..., rmse = sqrt = 4.08248...
        rmse = RootMeanSquaredError.compute([10, 20, 30], [10, 25, 25])
        assert rmse is not None
        assert abs(rmse - Decimal("4.082482904638630164")) < Decimal("0.0001")

    def test_perfect_forecast_is_zero(self) -> None:
        assert RootMeanSquaredError.compute([1, 2, 3], [1, 2, 3]) == Decimal("0")

    def test_empty_returns_none(self) -> None:
        assert RootMeanSquaredError.compute([], []) is None

    def test_length_mismatch_returns_none(self) -> None:
        assert RootMeanSquaredError.compute([1, 2], [1]) is None


class TestMeanAbsolutePercentageError:
    def test_hand_computed_fraction(self) -> None:
        # actual=[10,20,30], predicted=[10,25,25]
        # pct: 0, 5/20=0.25, 5/30≈0.1667 → MAPE = (0.4167)/3 ≈ 0.13889
        mape = MeanAbsolutePercentageError.compute([10, 20, 30], [10, 25, 25])
        assert mape is not None
        assert abs(mape - Decimal("0.138888888888888888")) < Decimal("0.0001")

    def test_zero_actuals_are_excluded(self) -> None:
        # Only the non-zero actual contributes: error 0 → MAPE 0
        mape = MeanAbsolutePercentageError.compute([0, 20], [10, 20])
        assert mape == Decimal("0")

    def test_all_zero_actuals_returns_none(self) -> None:
        assert MeanAbsolutePercentageError.compute([0, 0], [1, 1]) is None

    def test_empty_returns_none(self) -> None:
        assert MeanAbsolutePercentageError.compute([], []) is None

    def test_length_mismatch_returns_none(self) -> None:
        assert MeanAbsolutePercentageError.compute([1, 2], [1]) is None


class TestPrecisionAtK:
    def test_all_detected_are_expected(self) -> None:
        assert PrecisionAtK.compute(["a", "b"], ["a", "b"]) == 1.0

    def test_partial_precision(self) -> None:
        # top-2 = [a, c]; only a is relevant → 0.5
        assert PrecisionAtK.compute(["a", "b"], ["a", "c", "b"], k=2) == 0.5

    def test_k_none_uses_full_detected_length(self) -> None:
        # all 3 considered: hits a,b → 2/3
        assert PrecisionAtK.compute(["a", "b"], ["a", "c", "b"]) == pytest.approx(2 / 3)

    def test_k_larger_than_detected_clamps(self) -> None:
        assert PrecisionAtK.compute(["a"], ["a"], k=10) == 1.0

    def test_k_zero_returns_zero(self) -> None:
        assert PrecisionAtK.compute(["a"], ["a"], k=0) == 0.0

    def test_empty_detected_returns_zero(self) -> None:
        assert PrecisionAtK.compute(["a"], []) == 0.0

    def test_duplicates_in_detected_count_once_each_position(self) -> None:
        # top-2 = [a, a] → 2 hits / 2 = 1.0
        assert PrecisionAtK.compute(["a"], ["a", "a"]) == 1.0
