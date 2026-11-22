"""Canonical input schemas for the three reconciliation data sources.

One schema per source type declares the canonical field names, the header
aliases a real export may use, and which fields are mandatory. Header
resolution is deterministic: fold case, spaces, hyphens, dots and slashes to
underscores, then match exactly. There is no fuzzy matching and no AI
inference — an unrecognised header is reported, never guessed at.

Adapters are source-independent. A CSV export, a Google Sheets range, or a
pasted table all resolve through the same schema, so equivalent data yields
equivalent canonical records regardless of transport.

Only the Python standard library is used.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from finance.source_ingestion.issues import ApiErrorCode, IngestionError

_HEADER_FOLDERS = (" ", "-", ".", "/", "\\")


class SourceType(StrEnum):
    """The three evidence sources the reconciliation engine consumes."""

    INVOICE = "INVOICE"
    STRIPE = "STRIPE"
    BANK = "BANK"


def normalize_header(value: str) -> str:
    """Fold one source header to its deterministic comparison key.

    Args:
        value: Raw header cell as it appears in the source.

    Returns:
        Lowercased, underscore-joined form used for exact matching.
    """
    folded = value.strip().lower()
    for character in _HEADER_FOLDERS:
        folded = folded.replace(character, "_")
    while "__" in folded:
        folded = folded.replace("__", "_")
    return folded.strip("_")


@dataclass(frozen=True)
class ColumnSpec:
    """One canonical field and the headers that may carry it.

    Attributes:
        field_name: Canonical name used by the normalizer.
        required: Whether the field must be present in the header row.
        aliases: Alternative export header spellings for the same field.
        description: Human-readable purpose, surfaced in preview errors.
    """

    field_name: str
    required: bool = False
    aliases: tuple[str, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        """Reject empty canonical names and alias collisions."""
        if not isinstance(self.field_name, str) or not self.field_name.strip():
            raise ValueError("field_name must be a non-empty string.")
        for alias in self.aliases:
            if not isinstance(alias, str) or not alias.strip():
                raise ValueError("aliases must be non-empty strings.")

    def accepted_keys(self) -> frozenset[str]:
        """Return the folded header keys this column accepts."""
        return frozenset(normalize_header(name) for name in (self.field_name, *self.aliases))


@dataclass(frozen=True)
class ResolvedColumns:
    """Outcome of mapping a source header row onto canonical fields.

    Attributes:
        columns: Canonical field name -> the header that carried it.
        unknown_headers: Headers with no canonical meaning (reported, not fatal).
    """

    columns: Mapping[str, str]
    unknown_headers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Freeze the column mapping."""
        columns_value: object = self.columns
        if not isinstance(columns_value, Mapping):
            raise TypeError("columns must be a mapping of canonical field -> header.")
        object.__setattr__(self, "columns", MappingProxyType(dict(columns_value)))

    def header_for(self, field_name: str) -> str | None:
        """Return the source header carrying ``field_name``, if present."""
        return self.columns.get(field_name)

    def __contains__(self, field_name: object) -> bool:
        """Return whether the source carries the canonical field."""
        return field_name in self.columns


@dataclass(frozen=True)
class SourceSchema:
    """The canonical field set for one source type."""

    source_type: SourceType
    columns: tuple[ColumnSpec, ...]

    def __post_init__(self) -> None:
        """Reject duplicate canonical field names."""
        names = [column.field_name for column in self.columns]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate canonical field names in {self.source_type} schema.")

    @property
    def required_fields(self) -> tuple[str, ...]:
        """Return the canonical fields that must be present."""
        return tuple(column.field_name for column in self.columns if column.required)

    @property
    def expected_headers(self) -> tuple[str, ...]:
        """Return every canonical field name, required first."""
        return tuple(column.field_name for column in self.columns)

    def resolve(self, headers: Sequence[str]) -> ResolvedColumns:
        """Map a source header row onto canonical fields.

        Args:
            headers: Raw header cells in source order.

        Returns:
            The resolved mapping plus any headers with no canonical meaning.

        Raises:
            IngestionError: If a header is blank, two headers claim the same
                canonical field, or a required field is absent.
        """
        resolved: dict[str, str] = {}
        unknown: list[str] = []
        for header in headers:
            key = normalize_header(header)
            if not key:
                raise IngestionError(
                    ApiErrorCode.INVALID_SCHEMA,
                    "The source contains a blank header cell.",
                    found_columns=tuple(headers),
                )
            spec = next(
                (column for column in self.columns if key in column.accepted_keys()),
                None,
            )
            if spec is None:
                unknown.append(header)
                continue
            existing = resolved.get(spec.field_name)
            if existing is not None:
                raise IngestionError(
                    ApiErrorCode.INVALID_SCHEMA,
                    f"Columns {existing!r} and {header!r} both map to {spec.field_name!r}.",
                    found_columns=tuple(headers),
                )
            resolved[spec.field_name] = header
        missing = tuple(field for field in self.required_fields if field not in resolved)
        if missing:
            raise IngestionError(
                ApiErrorCode.INVALID_SCHEMA,
                f"Expected columns: {list(self.required_fields)}. Found: {list(headers)}.",
                missing_columns=missing,
                found_columns=tuple(headers),
            )
        return ResolvedColumns(columns=resolved, unknown_headers=tuple(unknown))


INVOICE_SCHEMA = SourceSchema(
    source_type=SourceType.INVOICE,
    columns=(
        ColumnSpec(
            "invoice_id",
            required=True,
            aliases=("invoice_number", "invoice", "invoice_no"),
            description="Invoice register identifier.",
        ),
        ColumnSpec(
            "amount",
            required=True,
            aliases=("gross", "invoice_amount", "total", "amount_gross"),
            description="Gross invoice amount in major units.",
        ),
        ColumnSpec(
            "currency",
            required=True,
            aliases=("currency_code", "ccy"),
            description="ISO 4217 currency code.",
        ),
        ColumnSpec(
            "issued_at",
            required=True,
            aliases=("issue_date", "invoice_date", "date"),
            description="Invoice issue instant (ISO 8601).",
        ),
        ColumnSpec("fee", description="Fee withheld from the invoice; defaults to 0."),
        ColumnSpec("refund", description="Refund already applied; defaults to 0."),
        ColumnSpec("status", description="Payment status; defaults to CAPTURED."),
        ColumnSpec("reference", description="Free-form external reference."),
    ),
)

STRIPE_SCHEMA = SourceSchema(
    source_type=SourceType.STRIPE,
    columns=(
        ColumnSpec(
            "charge_id",
            required=True,
            aliases=("charge", "payment_id", "transaction_id", "id"),
            description="Processor charge identifier.",
        ),
        ColumnSpec(
            "amount",
            required=True,
            aliases=("gross", "amount_gross", "charge_amount", "total"),
            description="Gross charge amount in major units.",
        ),
        ColumnSpec(
            "currency",
            required=True,
            aliases=("currency_code", "ccy"),
            description="ISO 4217 currency code.",
        ),
        ColumnSpec(
            "created_at",
            required=True,
            aliases=("created", "charge_date", "date", "occurred_at"),
            description="Charge creation instant (ISO 8601).",
        ),
        ColumnSpec("fee", description="Processor fee; defaults to 0."),
        ColumnSpec("refund", description="Refund amount; defaults to 0."),
        ColumnSpec("status", description="Charge status; defaults to CAPTURED."),
        ColumnSpec(
            "event_id",
            description="Processor event identifier; defaults to the charge id.",
        ),
        ColumnSpec("reference", description="Free-form external reference."),
    ),
)

BANK_SCHEMA = SourceSchema(
    source_type=SourceType.BANK,
    columns=(
        ColumnSpec(
            "deposit_id",
            required=True,
            aliases=("deposit", "transaction_id", "bank_reference", "id"),
            description="Bank statement deposit identifier.",
        ),
        ColumnSpec(
            "amount",
            required=True,
            aliases=("credit", "credit_amount", "amount_gross"),
            description="Credited amount in major units.",
        ),
        ColumnSpec(
            "posted_at",
            required=True,
            aliases=("date", "posting_date", "posted_date", "value_date"),
            description="Statement posting date.",
        ),
        ColumnSpec(
            "currency",
            description="Optional currency column; must agree with the declared one.",
        ),
        ColumnSpec("fee", description="Bank fee withheld; defaults to 0."),
        ColumnSpec("account", description="Account reference."),
        ColumnSpec("reference", description="Bank reference text."),
        ColumnSpec("description", description="Statement narrative."),
    ),
)

_SCHEMAS: Mapping[SourceType, SourceSchema] = MappingProxyType(
    {
        SourceType.INVOICE: INVOICE_SCHEMA,
        SourceType.STRIPE: STRIPE_SCHEMA,
        SourceType.BANK: BANK_SCHEMA,
    }
)


def schema_for(source_type: SourceType) -> SourceSchema:
    """Return the canonical schema for one source type.

    Raises:
        IngestionError: If the source type is not one of the three known types.
    """
    schema = _SCHEMAS.get(source_type) if isinstance(source_type, SourceType) else None
    if schema is None:
        raise IngestionError(
            ApiErrorCode.INVALID_SCHEMA,
            f"Unsupported source type: {source_type!r}.",
        )
    return schema
