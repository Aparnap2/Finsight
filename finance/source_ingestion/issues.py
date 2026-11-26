"""Deterministic issue taxonomy for source ingestion.

Ingestion never drops a financial record silently. Every row that cannot
become a canonical record produces a :class:`RowIssue` carrying its 1-based
source line, the offending column, the original cells, and a stable reason
code. Envelope failures (unreadable file, wrong headers) raise
:class:`IngestionError` instead, because no record can be produced at all.

Both shapes map onto the API codes in ``docs/specs/ERROR_CATALOG.md`` so the
P2 HTTP layer can translate them without re-deriving semantics.

Only the Python standard library is used.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from shared.errors import ErrorCode

#: The API error codes are owned by the shared registry
#: (:mod:`shared.errors.catalog`); this alias keeps the ingestion vocabulary
#: without creating a second source of truth.
ApiErrorCode = ErrorCode


class IssueCode(StrEnum):
    """Why one source row was refused.

    ``ROW_SHAPE`` means the row's cell count disagreed with the header, so
    it was never interpreted. The remaining codes are field-level: the row
    had the right width but a value could not become a canonical record.
    """

    ROW_SHAPE = "ROW_SHAPE"
    MISSING_FIELD = "MISSING_FIELD"
    INVALID_AMOUNT = "INVALID_AMOUNT"
    NEGATIVE_AMOUNT = "NEGATIVE_AMOUNT"
    OVER_PRECISION = "OVER_PRECISION"
    INVALID_DATE = "INVALID_DATE"
    INVALID_CURRENCY = "INVALID_CURRENCY"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    INVALID_STATUS = "INVALID_STATUS"
    INVALID_RECORD = "INVALID_RECORD"
    DUPLICATE_ROW = "DUPLICATE_ROW"
    CONFLICTING_ROW = "CONFLICTING_ROW"


_API_CODE_BY_ISSUE: Mapping[IssueCode, ApiErrorCode] = MappingProxyType(
    {
        IssueCode.ROW_SHAPE: ApiErrorCode.VALIDATION_FAILED,
        IssueCode.MISSING_FIELD: ApiErrorCode.VALIDATION_FAILED,
        IssueCode.INVALID_AMOUNT: ApiErrorCode.VALIDATION_FAILED,
        IssueCode.NEGATIVE_AMOUNT: ApiErrorCode.VALIDATION_FAILED,
        IssueCode.OVER_PRECISION: ApiErrorCode.VALIDATION_FAILED,
        IssueCode.INVALID_DATE: ApiErrorCode.VALIDATION_FAILED,
        IssueCode.INVALID_CURRENCY: ApiErrorCode.VALIDATION_FAILED,
        IssueCode.CURRENCY_MISMATCH: ApiErrorCode.VALIDATION_FAILED,
        IssueCode.INVALID_STATUS: ApiErrorCode.VALIDATION_FAILED,
        IssueCode.INVALID_RECORD: ApiErrorCode.VALIDATION_FAILED,
        IssueCode.DUPLICATE_ROW: ApiErrorCode.DUPLICATE_IMPORT,
        IssueCode.CONFLICTING_ROW: ApiErrorCode.VALIDATION_FAILED,
    }
)


def api_error_code_for(code: IssueCode) -> ApiErrorCode:
    """Return the API error code a row-level issue rolls up to."""
    return _API_CODE_BY_ISSUE[code]


class IngestionError(Exception):
    """Envelope failure: the source could not be read or understood.

    Raised for an empty file, an unsupported encoding or format, or headers
    that do not satisfy the canonical schema. Row-level problems never raise;
    they are reported as :class:`RowIssue` values.

    Attributes:
        code: API error code from the frozen error catalog.
        detail: User-safe explanation (no stack traces, paths, or secrets).
        missing_columns: Required canonical fields absent from the source.
        found_columns: Headers actually present, for the operator message.
    """

    def __init__(
        self,
        code: ApiErrorCode,
        detail: str,
        *,
        missing_columns: Sequence[str] = (),
        found_columns: Sequence[str] = (),
    ) -> None:
        """Store the API code, message, and header context."""
        super().__init__(detail)
        if not isinstance(code, ApiErrorCode):
            raise TypeError(f"code must be an ApiErrorCode, got {type(code).__name__}.")
        if not isinstance(detail, str) or not detail.strip():
            raise ValueError("detail must be a non-empty string.")
        self.code = code
        self.detail = detail
        self.missing_columns = tuple(missing_columns)
        self.found_columns = tuple(found_columns)


@dataclass(frozen=True)
class RowIssue:
    """One source row that could not become a canonical record.

    Attributes:
        code: Stable reason code.
        line_number: 1-based physical line in the source (header is line 1).
        detail: Actionable, user-safe explanation naming the offending value.
        field_name: Canonical field involved, when the failure is field-level.
        raw: The original row cells, preserved for audit.
        related_line: Line of the earlier row this one duplicates, if any.
    """

    code: IssueCode
    line_number: int
    detail: str
    field_name: str | None = None
    raw: Mapping[str, str] = field(default_factory=dict)
    related_line: int | None = None

    def __post_init__(self) -> None:
        """Validate the code, line, message, and freeze the raw cells."""
        if not isinstance(self.code, IssueCode):
            raise TypeError(f"code must be an IssueCode, got {type(self.code).__name__}.")
        if not isinstance(self.line_number, int) or isinstance(self.line_number, bool):
            raise TypeError("line_number must be an int.")
        if self.line_number < 1:
            raise ValueError("line_number must be >= 1.")
        if not isinstance(self.detail, str) or not self.detail.strip():
            raise ValueError("detail must be a non-empty string.")
        if self.field_name is not None and (
            not isinstance(self.field_name, str) or not self.field_name.strip()
        ):
            raise ValueError("field_name must be a non-empty string or None.")
        if self.related_line is not None:
            if not isinstance(self.related_line, int) or isinstance(self.related_line, bool):
                raise TypeError("related_line must be an int.")
            if self.related_line < 1:
                raise ValueError("related_line must be >= 1.")
        raw_value: object = self.raw
        if not isinstance(raw_value, Mapping):
            raise TypeError("raw must be a mapping of header -> cell.")
        object.__setattr__(self, "raw", MappingProxyType(dict(raw_value)))

    @property
    def api_error_code(self) -> ApiErrorCode:
        """Return the API error code this issue rolls up to."""
        return api_error_code_for(self.code)
