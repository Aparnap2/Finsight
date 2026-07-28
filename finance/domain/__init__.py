"""FinSight Finance Domain Models.

Domain models represent the core business entities of the FinSight platform.
They are Pydantic v2 models with strict typing, ``Decimal`` for all monetary
values, and comprehensive docstrings explaining business purpose.

Usage::

    from finance.domain import (
        Company,
        Account,
        ChartOfAccounts,
        Budget,
        Actual,
        Variance,
        Recommendation,
        BoardReport,
    )
"""

from finance.domain._types import MoneyDecimal
from finance.domain.actual import Actual, ActualLine
from finance.domain.board_report import BoardReport, ReportSection
from finance.domain.budget import Budget, BudgetLine, BudgetVersion
from finance.domain.chart_of_accounts import Account, AccountType, ChartOfAccounts
from finance.domain.company import Company
from finance.domain.cost_center import CostCenter
from finance.domain.department import Department
from finance.domain.driver import Driver, DriverTree, DriverType
from finance.domain.evidence import EvidenceConfidence, EvidenceItem, EvidenceSource
from finance.domain.fiscal_calendar import FiscalCalendar, FiscalPeriod, FiscalPeriodType
from finance.domain.forecast import Forecast, ForecastLine, ForecastScenario
from finance.domain.kpi import KPI, KPIDefinition, KPIValue
from finance.domain.recommendation import (
    Recommendation,
    RecommendationStatus,
    RecommendationType,
)
from finance.domain.transaction import Transaction
from finance.domain.variance import Variance, VarianceDirection

__all__ = [
    # Types
    "MoneyDecimal",
    # Company
    "Company",
    # Fiscal Calendar
    "FiscalCalendar",
    "FiscalPeriod",
    "FiscalPeriodType",
    # Chart of Accounts
    "Account",
    "AccountType",
    "ChartOfAccounts",
    # Department & Cost Center
    "Department",
    "CostCenter",
    # Budget
    "Budget",
    "BudgetLine",
    "BudgetVersion",
    # Actual
    "Actual",
    "ActualLine",
    # Forecast
    "Forecast",
    "ForecastLine",
    "ForecastScenario",
    # Transaction
    "Transaction",
    # KPI
    "KPI",
    "KPIDefinition",
    "KPIValue",
    # Variance
    "Variance",
    "VarianceDirection",
    # Driver
    "Driver",
    "DriverTree",
    "DriverType",
    # Evidence
    "EvidenceConfidence",
    "EvidenceItem",
    "EvidenceSource",
    # Recommendation
    "Recommendation",
    "RecommendationStatus",
    "RecommendationType",
    # Board Report
    "BoardReport",
    "ReportSection",
]
