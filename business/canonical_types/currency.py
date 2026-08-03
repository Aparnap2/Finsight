"""ISO 4217 currency code value object.

Defines CurrencyCode — a validated, immutable three-letter currency
identifier used across all monetary value objects in the platform.
"""

# mypy: disable-error-code="misc,untyped-decorator"

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

# ── ISO 4217 Currency Codes ─────────────────────────────────────────────────

_ISO_CURRENCIES: set[str] = {
    "AED", "AFN", "ALL", "AMD", "ANG", "AOA", "ARS", "AUD", "AWG", "AZN",
    "BAM", "BBD", "BDT", "BGN", "BHD", "BIF", "BMD", "BND", "BOB", "BRL",
    "BSD", "BTN", "BWP", "BYN", "BZD", "CAD", "CDF", "CHF", "CLP", "CNY",
    "COP", "CRC", "CUP", "CVE", "CZK", "DJF", "DKK", "DOP", "DZD", "EGP",
    "ERN", "ETB", "EUR", "FJD", "FKP", "FOK", "GBP", "GEL", "GGP", "GHS",
    "GIP", "GMD", "GNF", "GTQ", "GYD", "HKD", "HNL", "HRK", "HTG", "HUF",
    "IDR", "ILS", "IMP", "INR", "IQD", "IRR", "ISK", "JEP", "JMD", "JOD",
    "JPY", "KES", "KGS", "KHR", "KID", "KMF", "KRW", "KWD", "KYD", "KZT",
    "LAK", "LBP", "LKR", "LRD", "LSL", "LYD", "MAD", "MDL", "MGA", "MKD",
    "MMK", "MNT", "MOP", "MRU", "MUR", "MVR", "MWK", "MXN", "MYR", "MZN",
    "NAD", "NGN", "NIO", "NOK", "NPR", "NZD", "OMR", "PAB", "PEN", "PGK",
    "PHP", "PKR", "PLN", "PYG", "QAR", "RON", "RSD", "RUB", "RWF", "SAR",
    "SBD", "SCR", "SDG", "SEK", "SGD", "SHP", "SLE", "SLL", "SOS", "SRD",
    "SSP", "STN", "SYP", "SZL", "THB", "TJS", "TMT", "TND", "TOP", "TRY",
    "TTD", "TVD", "TWD", "TZS", "UAH", "UGX", "USD", "UYU", "UZS", "VES",
    "VND", "VUV", "WST", "XAF", "XCD", "XDR", "XOF", "XPF", "YER", "ZAR",
    "ZMW", "ZWL",
}


class CurrencyCode(BaseModel):
    """ISO 4217 three-letter currency code.

    Represents a monetary unit used in financial transactions. The code is
    validated against the ISO 4217 standard at construction.

    Examples: USD, EUR, GBP, JPY, INR, BRL, CAD, AUD, CHF, SGD, MXN.

    Usage:
        usd = CurrencyCode("USD")
        eur = CurrencyCode("eur")   # Auto-uppercased to EUR
    """

    model_config = ConfigDict(frozen=True)

    code: str

    @field_validator("code")
    @classmethod
    def _validate_code(cls, v: str) -> str:
        """Normalize and validate the currency code against ISO 4217."""
        normalized = v.strip().upper()
        if len(normalized) != 3:
            raise ValueError(
                f"Currency code must be exactly 3 characters, got {len(normalized)}"
            )
        if not normalized.isalpha():
            raise ValueError(
                f"Currency code must contain only letters, got {normalized}"
            )
        if normalized not in _ISO_CURRENCIES:
            raise ValueError(f"Unknown currency code: {normalized}")
        return normalized

    def __str__(self) -> str:
        return self.code
