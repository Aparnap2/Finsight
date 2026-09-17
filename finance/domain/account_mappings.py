"""Static Razorpay to QuickBooks to COBOL account mappings for Meridian.

Frozen code-level configuration (``docs/domain/company.md``): the table
binds each Razorpay settlement event to its QuickBooks account and its
COBOL general-ledger code. Code ``4812`` is the valid correction-leg
account used by the FS-231 reprocess proposal; records referencing codes
outside this table are rejected with ``INVALID_ACCOUNT_CODE``.
"""

from pydantic import BaseModel, ConfigDict


class AccountMapping(BaseModel):
    """One static row binding the three legs of a settlement event."""

    model_config = ConfigDict(frozen=True, strict=True)

    name: str
    """Short row name, e.g. ``provider-fee``."""

    razorpay_event: str
    """Razorpay settlement event, e.g. ``fee``."""

    quickbooks_account: str
    """QuickBooks account name receiving the entry."""

    cobol_gl_code: str
    """Four-digit COBOL general-ledger code."""


ACCOUNT_MAPPINGS: tuple[AccountMapping, ...] = (
    AccountMapping(
        name="settlement",
        razorpay_event="capture",
        quickbooks_account="Merchant Settlement Clearing",
        cobol_gl_code="4000",
    ),
    AccountMapping(
        name="pending",
        razorpay_event="pending",
        quickbooks_account="Unsettled Provider Balance",
        cobol_gl_code="4090",
    ),
    AccountMapping(
        name="refund",
        razorpay_event="refund",
        quickbooks_account="Merchant Refunds Payable",
        cobol_gl_code="4300",
    ),
    AccountMapping(
        name="adjustment",
        razorpay_event="adjustment",
        quickbooks_account="Settlement Adjustments",
        cobol_gl_code="4350",
    ),
    AccountMapping(
        name="correction",
        razorpay_event="correction",
        quickbooks_account="Legacy Correction Suspense",
        cobol_gl_code="4812",
    ),
    AccountMapping(
        name="provider-fee",
        razorpay_event="fee",
        quickbooks_account="Razorpay Fees Expense",
        cobol_gl_code="5200",
    ),
)
"""The frozen six-row mapping table (no runtime mutation)."""

VALID_COBOL_CODES: frozenset[str] = frozenset(
    mapping.cobol_gl_code for mapping in ACCOUNT_MAPPINGS
)
"""Codes a legacy record may reference; anything else is rejected."""


def is_valid_cobol_code(code: str) -> bool:
    """Return True when ``code`` is a known COBOL GL code.

    Args:
        code: The account code from a legacy record.

    Returns:
        True for mapped codes such as ``4812``; False otherwise (the
        record is then rejected with ``INVALID_ACCOUNT_CODE``).
    """
    return isinstance(code, str) and code in VALID_COBOL_CODES


def lookup_by_cobol(code: str) -> AccountMapping | None:
    """Return the mapping row for ``code``, or None when unmapped.

    Args:
        code: The COBOL general-ledger code to look up.

    Returns:
        The matching :class:`AccountMapping`, or None when the code is
        outside the static table.
    """
    for mapping in ACCOUNT_MAPPINGS:
        if mapping.cobol_gl_code == code:
            return mapping
    return None
