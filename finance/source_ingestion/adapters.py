"""Source adapters: raw source data to a uniform parsed table.

An adapter answers one mechanical question — "what rows does this source
contain?" — and nothing else. It does not validate field values, decide
financial meaning, or persist anything; that belongs to the normalizer and
the ingestion service.

Two adapters ship in P1:

* :class:`CsvAdapter` — the initial, always-available transport.
* :class:`TableAdapter` — an already-tabular source (a Google Sheets range,
  a pasted block, a test fixture). It proves the interface is genuinely
  source-independent: equivalent cells produce equivalent canonical records.

Line numbers are 1-based physical source lines. The header is line 1, the
first data row line 2. Rows whose cell count disagrees with the header are
reported as shape issues with their real line, never coerced.

Only the Python standard library is used.
"""

from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from finance.source_ingestion.issues import ApiErrorCode, IngestionError
from finance.source_ingestion.schemas import SourceType, normalize_header

_TABLE_SEPARATOR = "\x1f"
_ROW_SEPARATOR = "\x1e"


@dataclass(frozen=True)
class RowShapeIssue:
    """One row whose cell count disagreed with the header row."""

    line_number: int
    expected_cells: int
    found_cells: int
    cells: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate the line, the cell counts, and the captured cells."""
        if not isinstance(self.line_number, int) or isinstance(self.line_number, bool):
            raise TypeError("line_number must be an int.")
        if self.line_number < 2:
            raise ValueError("line_number must be >= 2 (the header is line 1).")
        for name in ("expected_cells", "found_cells"):
            value: object = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{name} must be an int.")
            if value < 0:
                raise ValueError(f"{name} must be non-negative.")
        if len(self.cells) != self.found_cells:
            raise ValueError("cells must match found_cells.")
        object.__setattr__(self, "cells", tuple(self.cells))


@dataclass(frozen=True)
class ParsedTable:
    """Uniform tabular view of a source, independent of transport.

    Attributes:
        headers: Raw header cells in source order.
        rows: Well-shaped rows as header -> cell mappings, in source order.
        line_numbers: Physical source line of each row in ``rows``.
        shape_issues: Rows refused because their width disagreed with the header.
        source_format: Transport name (``"csv"``, ``"table"``, ...).
    """

    headers: tuple[str, ...]
    rows: tuple[Mapping[str, str], ...]
    line_numbers: tuple[int, ...]
    shape_issues: tuple[RowShapeIssue, ...] = ()
    source_format: str = "csv"

    def __post_init__(self) -> None:
        """Validate the table envelope and freeze each row."""
        if not self.headers:
            raise ValueError("headers must not be empty.")
        if len(self.rows) != len(self.line_numbers):
            raise ValueError("rows and line_numbers must have the same length.")
        if len(set(self.line_numbers)) != len(self.line_numbers):
            raise ValueError("line_numbers must be unique.")
        for line in self.line_numbers:
            if not isinstance(line, int) or isinstance(line, bool):
                raise TypeError("line_numbers must contain ints.")
            if line < 2:
                raise ValueError("line_numbers must be >= 2 (the header is line 1).")
        frozen_rows: list[Mapping[str, str]] = []
        for row in self.rows:
            row_value: object = row
            if not isinstance(row_value, Mapping):
                raise TypeError("rows must be mappings of header -> cell.")
            frozen_rows.append(MappingProxyType(dict(row_value)))
        object.__setattr__(self, "rows", tuple(frozen_rows))
        if not isinstance(self.source_format, str) or not self.source_format.strip():
            raise ValueError("source_format must be a non-empty string.")

    def pairs(self) -> tuple[tuple[int, Mapping[str, str]], ...]:
        """Return ``(line_number, row)`` pairs in source order."""
        return tuple(zip(self.line_numbers, self.rows, strict=True))

    def digest(self) -> str:
        """Return a deterministic sha256 of the parsed table.

        The rendering covers headers and cells only, so an identical table
        arriving over a different transport (CSV file vs. Sheets range)
        produces the same digest.
        """
        parts: list[str] = [_TABLE_SEPARATOR.join(self.headers)]
        for _, row in self.pairs():
            parts.append(_TABLE_SEPARATOR.join(row.get(header, "") for header in self.headers))
        return hashlib.sha256(_ROW_SEPARATOR.join(parts).encode("utf-8")).hexdigest()


@runtime_checkable
class SourceAdapter(Protocol):
    """Common interface for every source adapter.

    Adapters parse raw source data into canonical rows. They do not validate
    financial values or persist anything — that is the ingestion service's
    responsibility.
    """

    def parse(self, raw: bytes | str, *, encoding: str = "utf-8") -> list[dict[str, Any]]:
        """Parse raw source data into a list of row dicts."""
        ...

    def headers(self, raw: bytes | str, *, encoding: str = "utf-8") -> list[str]:
        """Return the header row of the source."""
        ...

    def parse_table(self, raw: bytes | str, *, encoding: str = "utf-8") -> ParsedTable:
        """Parse raw source data into the uniform table view, with line numbers."""
        ...

    def source_type(self) -> SourceType:
        """Return the source type this adapter handles."""
        ...

    def supported_formats(self) -> list[str]:
        """Return supported format names (e.g. ``["csv"]``)."""
        ...


def _validate_headers(headers: Sequence[str]) -> tuple[str, ...]:
    """Normalize and validate a header row.

    Raises:
        IngestionError: If a header is blank or two headers fold to the same key.
    """
    cleaned = tuple(header.strip() for header in headers)
    if not cleaned:
        raise IngestionError(ApiErrorCode.INVALID_SCHEMA, "The source has no header row.")
    if any(not header for header in cleaned):
        raise IngestionError(
            ApiErrorCode.INVALID_SCHEMA,
            "The source contains a blank header cell.",
            found_columns=cleaned,
        )
    folded = [normalize_header(header) for header in cleaned]
    if len(set(folded)) != len(folded):
        raise IngestionError(
            ApiErrorCode.INVALID_SCHEMA,
            "The source header row contains duplicate columns.",
            found_columns=cleaned,
        )
    return cleaned


def _decode(raw: bytes | str, encoding: str) -> str:
    """Decode raw source bytes, refusing unsupported encodings."""
    if isinstance(raw, str):
        return raw
    if not isinstance(raw, bytes):
        raise IngestionError(
            ApiErrorCode.INVALID_FILE,
            f"Source must be bytes or text, got {type(raw).__name__}.",
        )
    try:
        return raw.decode(encoding)
    except (UnicodeDecodeError, LookupError) as exc:
        raise IngestionError(
            ApiErrorCode.INVALID_FILE,
            f"Source could not be decoded as {encoding}: {exc}.",
        ) from exc


def content_digest(raw: bytes | str) -> str:
    """Return the sha256 of the raw source bytes.

    Text sources are digested as UTF-8. This is file identity (used for
    duplicate-upload detection), not canonical content identity; see
    :meth:`ParsedTable.digest` for the latter.
    """
    payload = raw if isinstance(raw, bytes) else _decode(raw, "utf-8").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class CsvAdapter:
    """CSV transport adapter.

    Delimited-text parsing only: no value validation, no currency or date
    interpretation, no persistence.
    """

    def __init__(self, source_type: SourceType, *, delimiter: str = ",") -> None:
        """Bind the adapter to one source type and delimiter."""
        if not isinstance(source_type, SourceType):
            raise TypeError(f"source_type must be a SourceType, got {type(source_type).__name__}.")
        if not isinstance(delimiter, str) or len(delimiter) != 1:
            raise ValueError("delimiter must be a single character.")
        self._source_type = source_type
        self._delimiter = delimiter

    def source_type(self) -> SourceType:
        """Return the source type this adapter handles."""
        return self._source_type

    def supported_formats(self) -> list[str]:
        """Return the formats this adapter accepts."""
        return ["csv"]

    def parse_table(self, raw: bytes | str, *, encoding: str = "utf-8") -> ParsedTable:
        """Parse delimited text into headers, rows, and physical line numbers.

        Raises:
            IngestionError: If the source is empty, undecodable, malformed as
                CSV, or carries a blank or duplicate header.
        """
        text = _decode(raw, encoding)
        if not text.strip():
            raise IngestionError(ApiErrorCode.INVALID_FILE, "The source is empty.")
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=self._delimiter)
        try:
            header_row = next(reader)
        except StopIteration as exc:
            raise IngestionError(ApiErrorCode.INVALID_FILE, "The source is empty.") from exc
        except csv.Error as exc:
            raise IngestionError(
                ApiErrorCode.INVALID_FILE,
                f"The source is not readable CSV: {exc}.",
            ) from exc
        headers = _validate_headers(header_row)

        rows: list[Mapping[str, str]] = []
        lines: list[int] = []
        shape_issues: list[RowShapeIssue] = []
        while True:
            try:
                cells = next(reader)
            except StopIteration:
                break
            except csv.Error as exc:
                raise IngestionError(
                    ApiErrorCode.INVALID_FILE,
                    f"The source is not readable CSV: {exc}.",
                ) from exc
            line = reader.line_num
            if not cells or all(not cell.strip() for cell in cells):
                continue
            if len(cells) != len(headers):
                shape_issues.append(
                    RowShapeIssue(
                        line_number=line,
                        expected_cells=len(headers),
                        found_cells=len(cells),
                        cells=tuple(cells),
                    )
                )
                continue
            rows.append(MappingProxyType(dict(zip(headers, cells, strict=True))))
            lines.append(line)
        if not rows and not shape_issues:
            raise IngestionError(
                ApiErrorCode.INVALID_FILE,
                "The source has a header row but no data rows.",
            )
        return ParsedTable(
            headers=headers,
            rows=tuple(rows),
            line_numbers=tuple(lines),
            shape_issues=tuple(shape_issues),
            source_format="csv",
        )

    def parse(self, raw: bytes | str, *, encoding: str = "utf-8") -> list[dict[str, Any]]:
        """Return the parsed rows as plain dicts, in source order."""
        table = self.parse_table(raw, encoding=encoding)
        return [dict(row) for row in table.rows]

    def headers(self, raw: bytes | str, *, encoding: str = "utf-8") -> list[str]:
        """Return the source header row."""
        return list(self.parse_table(raw, encoding=encoding).headers)


class TableAdapter:
    """In-memory tabular adapter for already-structured sources.

    A Google Sheets range reader, a pasted block, or a test fixture binds its
    cells here and then flows through exactly the same schema resolution and
    normalization as a CSV file. ``raw`` is ignored because the table is
    bound at construction; ``content_digest`` for such a source falls back to
    the parsed-table digest.
    """

    def __init__(
        self,
        source_type: SourceType,
        headers: Sequence[str],
        rows: Iterable[Sequence[str]],
        *,
        first_line: int = 2,
        source_format: str = "table",
    ) -> None:
        """Bind the adapter to one source type and its tabular cells."""
        if not isinstance(source_type, SourceType):
            raise TypeError(f"source_type must be a SourceType, got {type(source_type).__name__}.")
        self._source_type = source_type
        self._headers = _validate_headers(headers)
        self._cells = tuple(tuple(row) for row in rows)
        self._first_line = first_line
        self._source_format = source_format

    def source_type(self) -> SourceType:
        """Return the source type this adapter handles."""
        return self._source_type

    def supported_formats(self) -> list[str]:
        """Return the formats this adapter accepts."""
        return [self._source_format]

    def parse_table(self, raw: bytes | str = b"", *, encoding: str = "utf-8") -> ParsedTable:
        """Return the bound table with physical line numbers.

        Raises:
            IngestionError: If no rows were bound.
        """
        del raw, encoding
        rows: list[Mapping[str, str]] = []
        lines: list[int] = []
        shape_issues: list[RowShapeIssue] = []
        for offset, cells in enumerate(self._cells):
            line = self._first_line + offset
            if all(not cell.strip() for cell in cells):
                continue
            if len(cells) != len(self._headers):
                shape_issues.append(
                    RowShapeIssue(
                        line_number=line,
                        expected_cells=len(self._headers),
                        found_cells=len(cells),
                        cells=tuple(cells),
                    )
                )
                continue
            rows.append(MappingProxyType(dict(zip(self._headers, cells, strict=True))))
            lines.append(line)
        if not rows and not shape_issues:
            raise IngestionError(
                ApiErrorCode.INVALID_FILE,
                "The source has a header row but no data rows.",
            )
        return ParsedTable(
            headers=self._headers,
            rows=tuple(rows),
            line_numbers=tuple(lines),
            shape_issues=tuple(shape_issues),
            source_format=self._source_format,
        )

    def parse(self, raw: bytes | str = b"", *, encoding: str = "utf-8") -> list[dict[str, Any]]:
        """Return the parsed rows as plain dicts, in source order."""
        table = self.parse_table(raw, encoding=encoding)
        return [dict(row) for row in table.rows]

    def headers(self, raw: bytes | str = b"", *, encoding: str = "utf-8") -> list[str]:
        """Return the bound header row."""
        return list(self.parse_table(raw, encoding=encoding).headers)


def adapter_for(source_type: SourceType, source_format: str = "csv") -> SourceAdapter:
    """Return the adapter for one source type and transport.

    Raises:
        IngestionError: If the transport is not supported in P1.
    """
    if not isinstance(source_type, SourceType):
        raise IngestionError(
            ApiErrorCode.INVALID_FILE,
            f"Unsupported source type: {source_type!r}.",
        )
    normalized = source_format.strip().lower()
    if normalized == "csv":
        return CsvAdapter(source_type)
    raise IngestionError(
        ApiErrorCode.INVALID_FILE,
        f"Unsupported source format: {source_format!r}. Supported: ['csv'].",
    )
