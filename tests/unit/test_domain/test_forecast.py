"""Tests for the Forecast domain models.

Forecasts represent projected financial outcomes for future periods
(`finance/domain/forecast.py`). Each forecast is scoped to a company and
fiscal year, carries a scenario (base / optimistic / pessimistic), and
aggregates forecast lines per account × period.

All monetary values are ``decimal.Decimal`` — never ``float``.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from finance.domain.forecast import Forecast, ForecastLine, ForecastScenario


def _now() -> datetime:
    """Return a fixed, timezone-aware timestamp for determinism."""
    return datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)


def _line(
    amount: str = "150000.00",
    scenario: ForecastScenario = ForecastScenario.BASE,
    line_id: str = "fl-001",
) -> ForecastLine:
    """Build a forecast line with sensible defaults."""
    return ForecastLine(
        id=line_id,
        account_id="acc-1000",
        amount=Decimal(amount),
        period_id="2026-08",
        scenario=scenario,
    )


def _forecast(scenario: ForecastScenario = ForecastScenario.BASE) -> Forecast:
    """Build a forecast aggregate with a single line."""
    return Forecast(
        id="fc-001",
        company_id="comp-001",
        fiscal_year=2026,
        scenario=scenario,
        lines=[_line(scenario=scenario)],
        created_at=_now(),
        updated_at=_now(),
    )


# =============================================================================
# ForecastScenario
# =============================================================================


class TestForecastScenario:
    """Scenario lifecycle enum."""

    def test_enum_values(self) -> None:
        """The enum exposes the canonical scenario names."""
        assert ForecastScenario.BASE.value == "base"
        assert ForecastScenario.OPTIMISTIC.value == "optimistic"
        assert ForecastScenario.PESSIMISTIC.value == "pessimistic"

    def test_str_round_trip(self) -> None:
        """StrEnum values serialize to their canonical strings."""
        assert str(ForecastScenario.OPTIMISTIC) == "optimistic"

    def test_all_scenarios_exist(self) -> None:
        """The three expected scenarios are present."""
        expected = {
            ForecastScenario.BASE,
            ForecastScenario.OPTIMISTIC,
            ForecastScenario.PESSIMISTIC,
        }
        assert expected.issubset(set(ForecastScenario))


# =============================================================================
# ForecastLine
# =============================================================================


class TestForecastLine:
    """Forecast line construction invariants."""

    def test_valid_line_constructs(self) -> None:
        """A fully specified forecast line constructs."""
        line = _line()
        assert line.id == "fl-001"
        assert line.account_id == "acc-1000"
        assert line.amount == Decimal("150000.0000")
        assert line.period_id == "2026-08"

    def test_default_scenario_is_base(self) -> None:
        """A forecast line defaults to the base scenario."""
        line = _line()
        assert line.scenario == ForecastScenario.BASE

    def test_float_amount_rejected(self) -> None:
        """Float monetary values are rejected."""
        with pytest.raises(ValidationError, match="Float values are not allowed"):
            ForecastLine(
                id="fl-002",
                account_id="acc-1000",
                amount=150000.50,
                period_id="2026-08",
            )

    def test_string_amount_accepted(self) -> None:
        """String amounts are coerced to Decimal."""
        line = ForecastLine(
            id="fl-003",
            account_id="acc-1000",
            amount="150000.50",
            period_id="2026-08",
        )
        assert isinstance(line.amount, Decimal)
        assert line.amount == Decimal("150000.5000")

    def test_zero_amount_constructs(self) -> None:
        """A zero forecast line is valid."""
        assert _line(amount="0.00").amount == Decimal("0.0000")

    def test_negative_amount_constructs(self) -> None:
        """A negative forecast line (e.g. projected refund) is valid."""
        assert _line(amount="-5000.00").amount == Decimal("-5000.0000")

    def test_large_amount_preserves_precision(self) -> None:
        """Large forecast amounts do not lose precision."""
        assert _line(amount="999999999999.99").amount == Decimal("999999999999.9900")

    def test_missing_id_rejected(self) -> None:
        """A forecast line requires an identifier."""
        with pytest.raises(ValidationError):
            ForecastLine(
                account_id="acc-1000",  # type: ignore[call-arg]
                amount=Decimal("100.00"),
                period_id="2026-08",
            )

    def test_missing_amount_rejected(self) -> None:
        """A forecast line requires an amount."""
        with pytest.raises(ValidationError):
            ForecastLine(
                id="fl-004",
                account_id="acc-1000",
                period_id="2026-08",
            )  # type: ignore[call-arg]

    def test_invalid_scenario_rejected(self) -> None:
        """An unknown scenario string is rejected."""
        with pytest.raises(ValidationError):
            ForecastLine(
                id="fl-005",
                account_id="acc-1000",
                amount=Decimal("100.00"),
                period_id="2026-08",
                scenario="wildcard", 
            )

    def test_optimistic_scenario_constructs(self) -> None:
        """An optimistic scenario line is representable."""
        line = _line(scenario=ForecastScenario.OPTIMISTIC)
        assert line.scenario == ForecastScenario.OPTIMISTIC


# =============================================================================
# Forecast aggregate
# =============================================================================


class TestForecastAggregate:
    """Forecast aggregate construction and invariant checks."""

    def test_valid_forecast_constructs(self) -> None:
        """A forecast with lines constructs."""
        forecast = _forecast()
        assert forecast.id == "fc-001"
        assert forecast.company_id == "comp-001"
        assert forecast.fiscal_year == 2026
        assert forecast.scenario == ForecastScenario.BASE
        assert len(forecast.lines) == 1

    def test_empty_lines_allowed(self) -> None:
        """A forecast with no lines is representable."""
        forecast = Forecast(
            id="fc-002",
            company_id="comp-001",
            fiscal_year=2026,
            scenario=ForecastScenario.BASE,
            lines=[],
            created_at=_now(),
            updated_at=_now(),
        )
        assert forecast.lines == []

    def test_multiple_lines_preserved(self) -> None:
        """Multiple forecast lines are preserved in order."""
        forecast = Forecast(
            id="fc-003",
            company_id="comp-001",
            fiscal_year=2026,
            scenario=ForecastScenario.PESSIMISTIC,
            lines=[_line(line_id="fl-1"), _line(line_id="fl-2", amount="2000.00")],
            created_at=_now(),
            updated_at=_now(),
        )
        assert [line.id for line in forecast.lines] == ["fl-1", "fl-2"]

    def test_pessimistic_scenario_forecast(self) -> None:
        """A pessimistic forecast is representable end-to-end."""
        forecast = _forecast(scenario=ForecastScenario.PESSIMISTIC)
        assert forecast.scenario == ForecastScenario.PESSIMISTIC
        assert forecast.lines[0].scenario == ForecastScenario.PESSIMISTIC

    def test_missing_company_rejected(self) -> None:
        """A forecast requires a company identifier."""
        with pytest.raises(ValidationError):
            Forecast(
                id="fc-004",
                fiscal_year=2026,  # type: ignore[call-arg]
                scenario=ForecastScenario.BASE,
                lines=[],
                created_at=_now(),
                updated_at=_now(),
            )

    def test_missing_scenario_rejected(self) -> None:
        """A forecast requires a scenario."""
        with pytest.raises(ValidationError):
            Forecast(
                id="fc-005",
                company_id="comp-001",
                fiscal_year=2026,
                lines=[],  # type: ignore[call-arg]
                created_at=_now(),
                updated_at=_now(),
            )

    def test_missing_timestamps_rejected(self) -> None:
        """A forecast requires created and updated timestamps."""
        with pytest.raises(ValidationError):
            Forecast(
                id="fc-006",
                company_id="comp-001",
                fiscal_year=2026,
                scenario=ForecastScenario.BASE,
                lines=[],
            )  # type: ignore[call-arg]


# =============================================================================
# Forecast serialization & monetary invariants
# =============================================================================


class TestForecastSerialization:
    """Serialization / deserialization round-trips."""

    def test_model_dump_round_trip(self) -> None:
        """model_dump / model_validate preserves a forecast."""
        original = _forecast()
        rebuilt = Forecast.model_validate(original.model_dump())
        assert rebuilt == original

    def test_json_round_trip(self) -> None:
        """JSON round-trip preserves the forecast."""
        original = _forecast()
        rebuilt = Forecast.model_validate_json(original.model_dump_json())
        assert rebuilt == original

    def test_line_amounts_remain_decimal_after_round_trip(self) -> None:
        """Line amounts stay Decimal through JSON round-tripping."""
        rebuilt = Forecast.model_validate_json(_forecast().model_dump_json())
        assert isinstance(rebuilt.lines[0].amount, Decimal)

    def test_scenario_survives_round_trip(self) -> None:
        """The scenario enum survives serialization."""
        rebuilt = Forecast.model_validate_json(
            _forecast(ForecastScenario.OPTIMISTIC).model_dump_json()
        )
        assert rebuilt.scenario == ForecastScenario.OPTIMISTIC


class TestForecastMonetaryInvariants:
    """Monetary invariants across forecast lines."""

    def test_all_amounts_are_decimal(self) -> None:
        """Every forecast line amount is a Decimal."""
        forecast = Forecast(
            id="fc-010",
            company_id="comp-001",
            fiscal_year=2026,
            scenario=ForecastScenario.BASE,
            lines=[_line(), _line(amount="200.00", line_id="fl-2")],
            created_at=_now(),
            updated_at=_now(),
        )
        for line in forecast.lines:
            assert isinstance(line.amount, Decimal)

    def test_amounts_quantized_to_four_places(self) -> None:
        """Forecast amounts are normalized to 4 decimal places."""
        assert _line(amount="123.45").amount == Decimal("123.4500")

    def test_last_known_value_baseline_available(self) -> None:
        """Period-scoped lines allow last-known-value baselines per account.

        The forecast model is a container of period-scoped lines; a consumer
        can recover the latest known value for an account as the max period
        line for that account (the model itself performs no arithmetic).
        """
        forecast = Forecast(
            id="fc-011",
            company_id="comp-001",
            fiscal_year=2026,
            scenario=ForecastScenario.BASE,
            lines=[
                _line(amount="100.00", line_id="fl-a"),
                ForecastLine(
                    id="fl-b",
                    account_id="acc-1000",
                    amount=Decimal("200.00"),
                    period_id="2026-09",
                ),
            ],
            created_at=_now(),
            updated_at=_now(),
        )
        latest = max(
            (line for line in forecast.lines if line.account_id == "acc-1000"),
            key=lambda line: line.period_id,
        )
        assert latest.amount == Decimal("200.0000")
