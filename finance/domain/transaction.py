"""Transaction domain model.

Transactions represent individual financial events recorded in the general
ledger.  They are the atomic building blocks that aggregate into actuals
and drive variance analysis.
"""

from datetime import date, datetime

from pydantic import BaseModel

from finance.domain._types import MoneyDecimal


class Transaction(BaseModel):
    """An individual financial transaction recorded in the general ledger.

    Transactions are the finest-grain financial data in the system.  They
    are aggregated into ``ActualLine`` records for variance analysis.
    """

    id: str
    """Unique transaction identifier."""

    account_id: str
    """The account this transaction is posted to."""

    department_id: str | None = None
    """Optional department attribution."""

    cost_center_id: str | None = None
    """Optional cost centre attribution."""

    amount: MoneyDecimal
    """The monetary amount of the transaction."""

    currency: str = "USD"
    """Transaction currency (ISO 4217)."""

    description: str
    """Narrative description of the transaction."""

    transaction_date: date
    """The calendar date on which the transaction occurred."""

    period_id: str
    """The fiscal period this transaction is posted to."""

    source: str = "gl"
    """Originating system (e.g. ``\"gl\"``, ``\"journal\"``, ``\"manual\"``)."""

    reference: str | None = None
    """External reference or document number (e.g. invoice number)."""

    created_at: datetime
    """Timestamp when the transaction was recorded in the system."""
