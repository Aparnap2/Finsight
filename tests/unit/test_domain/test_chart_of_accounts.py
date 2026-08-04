"""Tests for the Chart of Accounts domain models.

Covers ``finance/domain/chart_of_accounts.py``: the ``AccountType`` enum,
the ``Account`` record, and the ``ChartOfAccounts`` aggregate. Key
invariants: account codes are unique within a chart (documented contract),
accounts default to active, and the hierarchy references parent codes.
"""

import pytest
from pydantic import ValidationError

from finance.domain.chart_of_accounts import Account, AccountType, ChartOfAccounts


def _account(**overrides: object) -> Account:
    """Build a default account."""
    defaults: dict[str, object] = {
        "id": "ACC-4010",
        "code": "4010",
        "name": "Consulting Revenue",
        "type": AccountType.REVENUE,
    }
    defaults.update(overrides)
    return Account(**defaults)


def _coa(**overrides: object) -> ChartOfAccounts:
    """Build a default chart of accounts."""
    defaults: dict[str, object] = {
        "id": "COA-001",
        "company_id": "CF001",
        "accounts": [_account()],
    }
    defaults.update(overrides)
    return ChartOfAccounts(**defaults)


# =============================================================================
# AccountType enum
# =============================================================================


class TestAccountType:
    """AccountType enum values."""

    def test_revenue_value(self) -> None:
        """REVENUE serializes to 'revenue'."""
        assert AccountType.REVENUE.value == "revenue"

    def test_cogs_value(self) -> None:
        """COGS serializes to 'cogs'."""
        assert AccountType.COGS.value == "cogs"

    def test_opex_value(self) -> None:
        """OPEX serializes to 'opex'."""
        assert AccountType.OPEX.value == "opex"

    def test_other_income_value(self) -> None:
        """OTHER_INCOME serializes to 'other_income'."""
        assert AccountType.OTHER_INCOME.value == "other_income"

    def test_asset_value(self) -> None:
        """ASSET serializes to 'asset'."""
        assert AccountType.ASSET.value == "asset"

    def test_liability_value(self) -> None:
        """LIABILITY serializes to 'liability'."""
        assert AccountType.LIABILITY.value == "liability"

    def test_equity_value(self) -> None:
        """EQUITY serializes to 'equity'."""
        assert AccountType.EQUITY.value == "equity"


# =============================================================================
# Account
# =============================================================================


class TestAccount:
    """Account construction."""

    def test_constructs_with_required_fields(self) -> None:
        """An account builds with required fields."""
        account = _account()
        assert account.id == "ACC-4010"
        assert account.code == "4010"
        assert account.name == "Consulting Revenue"
        assert account.type == AccountType.REVENUE

    def test_is_active_defaults_to_true(self) -> None:
        """Accounts default to active."""
        assert _account().is_active is True

    def test_parent_code_defaults_to_none(self) -> None:
        """parent_code defaults to None."""
        assert _account().parent_code is None

    def test_currency_defaults_to_none(self) -> None:
        """currency defaults to None (use company base currency)."""
        assert _account().currency is None

    def test_deactivated_account_representable(self) -> None:
        """An inactive account is representable."""
        assert _account(is_active=False).is_active is False

    def test_parent_code_settable(self) -> None:
        """The parent account code is settable."""
        assert _account(parent_code="4000").parent_code == "4000"

    def test_currency_override_settable(self) -> None:
        """A currency override is settable."""
        assert _account(currency="EUR").currency == "EUR"

    def test_all_account_types_representable(self) -> None:
        """Every account type constructs an account."""
        for account_type in AccountType:
            account = _account(type=account_type)
            assert account.type == account_type

    def test_id_required(self) -> None:
        """An account requires an id."""
        with pytest.raises(ValidationError):
            _account(id=None)

    def test_code_required(self) -> None:
        """An account requires a code."""
        with pytest.raises(ValidationError):
            _account(code=None)

    def test_name_required(self) -> None:
        """An account requires a name."""
        with pytest.raises(ValidationError):
            _account(name=None)

    def test_type_required(self) -> None:
        """An account requires a type."""
        with pytest.raises(ValidationError):
            _account(type=None)


# =============================================================================
# ChartOfAccounts
# =============================================================================


class TestChartOfAccounts:
    """Chart of accounts aggregate construction."""

    def test_constructs_with_required_fields(self) -> None:
        """A chart builds with required fields."""
        coa = _coa()
        assert coa.id == "COA-001"
        assert coa.company_id == "CF001"
        assert len(coa.accounts) == 1

    def test_version_defaults_to_one(self) -> None:
        """version defaults to 1."""
        assert _coa().version == 1

    def test_multiple_accounts_stored(self) -> None:
        """A chart carries multiple accounts."""
        coa = _coa(accounts=[_account(), _account(id="ACC-4011", code="4011")])
        assert len(coa.accounts) == 2

    def test_accounts_are_account_instances(self) -> None:
        """Accounts are validated as Account instances."""
        assert isinstance(_coa().accounts[0], Account)

    def test_invalid_account_rejected(self) -> None:
        """A malformed account is rejected at the chart boundary."""
        with pytest.raises(ValidationError):
            _coa(accounts=[{"code": "4010"}])

    def test_empty_accounts_representable(self) -> None:
        """An empty chart is representable."""
        assert _coa(accounts=[]).accounts == []

    def test_version_settable(self) -> None:
        """The version is settable."""
        assert _coa(version=2).version == 2

    def test_company_id_required(self) -> None:
        """A chart requires a company id."""
        with pytest.raises(ValidationError):
            _coa(company_id=None)

    def test_round_trip_serialization(self) -> None:
        """A chart round-trips through model_dump."""
        coa = _coa()
        dumped = coa.model_dump()
        rebuilt = ChartOfAccounts(**dumped)
        assert rebuilt == coa