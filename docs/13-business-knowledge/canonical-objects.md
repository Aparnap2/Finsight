# Canonical Value Objects — Design Document

> **Part of:** Business Knowledge Layer  
> **Status:** Design proposal  
> **Audience:** Domain engineers, platform architects, backend developers  
> **Design Principle:** Every financial primitive is a typed value object with explicit invariants, validation, and serialization. Never raw strings, never bare `Decimal`, never guessed semantics.

---

## Design Principles

1. **Immutability** — All canonical objects are frozen (`@dataclass(frozen=True)` or Pydantic ` frozen=True`). Once constructed, they cannot change.
2. **Validation at construction** — Invalid objects cannot be represented. All invariants are checked in `__post_init__()` or Pydantic validators.
3. **Type safety** — Every financial primitive is a distinct type. A `CostCenter` is not a `str` — it is a `CostCenter` that wraps a `str`.
4. **Arithmetic safety** — Operations between incompatible types are structurally impossible (e.g., `Money("USD") + Money("EUR")` fails).
5. **Refuse float** — No canonical object accepts `float` for numeric values. `Decimal` is the only allowed numeric type.
6. **Serialization** — Every object has `.to_dict()` and `.to_json()` methods for API output and `.from_dict()` / classmethod constructors for ingestion.
7. **Business meaning** — Object names, field names, and validation error messages use business vocabulary, not technical jargon.

---

## 1. `Money`

### Canonical Definition

```python
@dataclass(frozen=True)
class Money:
    """A monetary value with currency.
    
    Represents a financial amount in a specific currency. All arithmetic
    operations enforce currency consistency — mixing currencies is a
    TypeError unless an exchange rate is provided.
    
    The amount is stored as Decimal with precision enforced at construction.
    Float input is structurally rejected.
    """
    amount: Decimal
    currency: CurrencyCode
```

### Invariants

| Invariant | Enforcement | Error Message |
|-----------|-------------|---------------|
| `amount` must be `Decimal` | Type check in `__post_init__` | `"Money.amount must be Decimal, got <type>"` |
| `amount` precision ≤ 4 decimal places | Decimal quantize | `"Money amount precision exceeds 4 decimal places"` |
| `currency` must be valid ISO 4217 | Delegated to `CurrencyCode` | Per `CurrencyCode` validation |
| `amount` may be negative | Allowed (represents liability, loss) | — |

### Arithmetic Operations

```python
def __add__(self, other: Money) -> Money:
    """Add two Money values. Currency must match."""
    if self.currency != other.currency:
        raise CurrencyMismatchError(self.currency, other.currency, "add")
    return Money(self.amount + other.amount, self.currency)

def __sub__(self, other: Money) -> Money:
    """Subtract two Money values. Currency must match."""
    if self.currency != other.currency:
        raise CurrencyMismatchError(self.currency, other.currency, "subtract")
    return Money(self.amount - other.amount, self.currency)

def __mul__(self, factor: Decimal | int) -> Money:
    """Multiply by a scalar (Decimal or int)."""
    if not isinstance(factor, (Decimal, int)):
        raise TypeError(f"Cannot multiply Money by {type(factor).__name__}")
    return Money(self.amount * Decimal(str(factor)), self.currency)

def __neg__(self) -> Money:
    return Money(-self.amount, self.currency)

def convert(self, target_currency: CurrencyCode, rate: Decimal) -> Money:
    """Convert to another currency at the given rate."""
    return Money((self.amount * rate).quantize(Decimal("0.0001")), target_currency)

def abs(self) -> Money:
    return Money(abs(self.amount), self.currency)
```

### Comparison Operations

```python
def __eq__(self, other: object) -> bool:
    if not isinstance(other, Money):
        return NotImplemented
    return self.amount == other.amount and self.currency == other.currency

def __lt__(self, other: Money) -> bool:
    if self.currency != other.currency:
        raise CurrencyMismatchError(self.currency, other.currency, "compare")
    return self.amount < other.amount

# __le__, __gt__, __ge__ follow the same pattern
```

### Serialization

```python
def to_dict(self) -> dict:
    return {"amount": str(self.amount), "currency": str(self.currency)}

def to_json(self) -> str:
    return json.dumps({"amount": str(self.amount), "currency": str(self.currency)})

@classmethod
def from_dict(cls, data: dict) -> Money:
    return cls(
        amount=Decimal(str(data["amount"])),
        currency=CurrencyCode(data["currency"]),
    )
```

### Examples

```python
# Construction
revenue = Money(Decimal("1250000.00"), CurrencyCode("USD"))
tax = Money(Decimal("125000.00"), CurrencyCode("USD"))

# Arithmetic
net_revenue = revenue - tax  # Money(1125000.00, USD)

# Scalar multiplication
annualized = monthly_revenue * Decimal("12")  # Money(14400000.00, USD)

# Currency conversion (EUR → USD at 1.08)
eur_amount = Money(Decimal("1000000.00"), CurrencyCode("EUR"))
usd_amount = eur_amount.convert(CurrencyCode("USD"), Decimal("1.08"))
# Money(1080000.00, USD)

# Errors
# Money(Decimal("100"), CurrencyCode("USD")) + Money(Decimal("100"), CurrencyCode("EUR"))
# → CurrencyMismatchError: Cannot add USD and EUR
```

---

## 2. `Percentage`

### Canonical Definition

```python
@dataclass(frozen=True)
class Percentage:
    """A percentage value with a representation mode.
    
    Two modes:
    - `DECIMAL` (default): value is in [0, 1], e.g. 0.12 = 12%
    - `PERCENT`: value is in [0, 100], e.g. 12.0 = 12%
    
    Internal storage is always in DECIMAL mode. Formatting converts
    to the display mode as needed.
    """
    value: Decimal
    _mode: ClassVar[Literal["decimal", "percent"]] = "decimal"
```

### Invariants

| Invariant | Enforcement | Error Message |
|-----------|-------------|---------------|
| `value` must be `Decimal` | `__post_init__` | `"Percentage.value must be Decimal"` |
| `value` in `[0, 1]` when mode=`decimal` | Range check | `"Percentage must be in [0, 1], got <value>"` |
| `value` in `[0, 100]` when mode=`percent` | Range check | `"Percentage must be in [0, 100], got <value>"` |
| `value` precision ≤ 6 decimal places | Decimal quantize | `"Percentage precision exceeds 6 decimal places"` |

### Factory Methods

```python
@classmethod
def from_decimal(cls, decimal_value: Decimal) -> Percentage:
    """Create from a 0-1 decimal (e.g., 0.15 for 15%)."""
    return cls(decimal_value)

@classmethod
def from_percent(cls, percent_value: Decimal) -> Percentage:
    """Create from a 0-100 percent (e.g., 15.0 for 15%)."""
    return cls(percent_value / Decimal("100"))

@classmethod
def from_fraction(cls, numerator: Decimal, denominator: Decimal) -> Percentage:
    """Create from a fraction, computing numerator/denominator."""
    if denominator == 0:
        raise DivisionByZeroError("Cannot compute percentage with zero denominator")
    return cls(numerator / denominator)
```

### Formatting

```python
def format(self, decimals: int = 2) -> str:
    """Format as human-readable percentage string.
    
    Args:
        decimals: Number of decimal places (default 2).
    
    Returns:
        e.g., "12.34%"
    """
    percent_value = self.value * Decimal("100")
    formatted = percent_value.quantize(Decimal(f"0.{'0' * decimals}"))
    return f"{formatted}%"

def __str__(self) -> str:
    return self.format(2)

def __repr__(self) -> str:
    return f"Percentage({self.value})"
```

### Examples

```python
# Construction
margin = Percentage.from_decimal(Decimal("0.35"))     # 35% gross margin
growth = Percentage.from_percent(Decimal("12.5"))      # 12.5% growth
tax_rate = Percentage.from_fraction(
    Decimal("125000"), Decimal("1000000")
)  # 12.5% effective tax rate

# Formatting
print(margin)  # "35.00%"
print(growth)  # "12.50%"

# Comparison
Percentage.from_decimal(Decimal("0.10")) < Percentage.from_decimal(Decimal("0.20"))
# → True
```

---

## 3. `CurrencyCode`

### Canonical Definition

```python
@dataclass(frozen=True)
class CurrencyCode:
    """ISO 4217 three-letter currency code.
    
    Examples: USD, EUR, GBP, JPY, INR, BRL, AUD, CAD, CHF, CNY, SGD, MXN.
    """
    code: str
```

### Invariants

| Invariant | Enforcement | Error Message |
|-----------|-------------|---------------|
| Length must be exactly 3 | Check in `__post_init__` | `"CurrencyCode must be exactly 3 characters, got <n>"` |
| Must be uppercase letters | Check `code.isupper()` and `code.isalpha()` | `"CurrencyCode must be uppercase letters, got <code>"` |
| Must be in known ISO 4217 set | Check against `_ISO_CURRENCIES` | `"Unknown currency code: <code>"` |

### Known Currency Set

```python
_ISO_CURRENCIES: set[str] = {
    "USD", "EUR", "GBP", "JPY", "CNY", "INR", "BRL", "CAD", "AUD",
    "CHF", "SGD", "MXN", "KRW", "SEK", "NOK", "DKK", "NZD", "TRY",
    "ZAR", "HKD", "TWD", "THB", "MYR", "PHP", "IDR", "VND", "PLN",
    "CZK", "HUF", "ILS", "CLP", "COP", "PEN", "AED", "SAR", "NGN",
    # Add additional ISO 4217 currencies as needed
}
```

### Construction Normalization

```python
def __post_init__(self) -> None:
    # Auto-uppercase
    object.__setattr__(self, "code", self.code.upper().strip())
    # Validation in __post_init__ or Pydantic validator
```

### Examples

```python
usd = CurrencyCode("usd")    # Normalized to "USD"
eur = CurrencyCode("EUR")    # Passes through
# rup = CurrencyCode("RUPY")  # ValueError: Unknown currency code: RUPY
# xy = CurrencyCode("XY")     # ValueError: CurrencyCode must be exactly 3 characters
```

---

## 4. `FiscalPeriod`

### Canonical Definition

```python
@dataclass(frozen=True)
class FiscalPeriod:
    """A fiscal period identifier.
    
    Canonical format is YYYY-MM for monthly periods.
    Supports ordering, subtraction (period difference), and
    generation of adjacent periods.
    
    Examples: 2026-01 (January 2026), 2026-Q2 (Q2 2026), FY2026
    """
    year: int
    period: int
    type: Literal["month", "quarter", "year"] = "month"
```

### Invariants

| Invariant | Enforcement | Error Message |
|-----------|-------------|---------------|
| `year` must be ≥ 1900 and ≤ 2100 | Range check | `"FiscalPeriod year out of range: <year>"` |
| `period` must be 1-12 for month | Range check | `"Month period must be 1-12, got <period>"` |
| `period` must be 1-4 for quarter | Range check | `"Quarter period must be 1-4, got <period>"` |
| `period` must be 1 for year | Range check | `"Year period must be 1, got <period>"` |

### String Representations

```python
@property
def period_str(self) -> str:
    """Canonical string: YYYY-MM, YYYY-QN, or FYYYYY."""
    match self.type:
        case "month":
            return f"{self.year}-{self.period:02d}"
        case "quarter":
            return f"{self.year}-Q{self.period}"
        case "year":
            return f"FY{self.year}"

def __str__(self) -> str:
    return self.period_str

@classmethod
def from_string(cls, s: str) -> FiscalPeriod:
    """Parse from canonical string format."""
    # YYYY-MM
    m = re.match(r"^(\d{4})-(\d{2})$", s)
    if m:
        return cls(year=int(m.group(1)), period=int(m.group(2)), type="month")
    # YYYY-QN
    m = re.match(r"^(\d{4})-Q([1-4])$", s)
    if m:
        return cls(year=int(m.group(1)), period=int(m.group(2)), type="quarter")
    # FYYYYY
    m = re.match(r"^FY(\d{4})$", s)
    if m:
        return cls(year=int(m.group(1)), period=1, type="year")
    raise ValueError(f"Cannot parse FiscalPeriod from: {s}")
```

### Ordering

```python
def _sort_key(self) -> int:
    """Sort key: year * 100 + period (normalized to 1-12 or 1-4)."""
    return self.year * 100 + self.period

def __lt__(self, other: FiscalPeriod) -> bool:
    if not isinstance(other, FiscalPeriod):
        return NotImplemented
    return self._sort_key() < other._sort_key()

def __eq__(self, other: object) -> bool:
    if not isinstance(other, FiscalPeriod):
        return NotImplemented
    return (self.year, self.period, self.type) == (other.year, other.period, other.type)
```

### Period Arithmetic

```python
def __add__(self, months: int) -> FiscalPeriod:
    """Add (or subtract) months to get a new FiscalPeriod.
    
    Works across year boundaries. Quarters are converted to months,
    added, then converted back.
    """
    if self.type == "year":
        return FiscalPeriod(self.year + months, 1, "year")
    
    total_months = (self.year * 12 + self.period) + months
    new_year = (total_months - 1) // 12
    new_month = ((total_months - 1) % 12) + 1
    
    if self.type == "quarter":
        new_quarter = (new_month - 1) // 3 + 1
        return FiscalPeriod(new_year, new_quarter, "quarter")
    
    return FiscalPeriod(new_year, new_month, "month")

def __sub__(self, other: FiscalPeriod) -> int:
    """Month difference between two FiscalPeriods of the same type."""
    if self.type != other.type:
        raise TypeError(f"Cannot subtract {self.type} from {other.type}")
    return (self.year * 12 + self.period) - (other.year * 12 + other.period)
```

### Adjacent Periods

```python
@property
def prior_period(self) -> FiscalPeriod:
    """Previous month/quarter/year."""
    return self.__add__(-1)

@property
def next_period(self) -> FiscalPeriod:
    """Next month/quarter/year."""
    return self.__add__(1)

@property
def prior_year_period(self) -> FiscalPeriod:
    """Same period in the prior year."""
    return FiscalPeriod(self.year - 1, self.period, self.type)
```

### Examples

```python
jan_2026 = FiscalPeriod(2026, 1, "month")
feb_2026 = jan_2026.next_period        # FiscalPeriod(2026, 2, "month")
dec_2026 = jan_2026.__add__(11)        # FiscalPeriod(2026, 12, "month")
jan_2027 = jan_2026.__add__(12)        # FiscalPeriod(2027, 1, "month")

q1_2026 = FiscalPeriod(2026, 1, "quarter")
q2_2026 = q1_2026.next_period          # FiscalPeriod(2026, 2, "quarter")

# String
str(jan_2026)   # "2026-01"
str(q1_2026)    # "2026-Q1"
str(FiscalPeriod(2026, 1, "year"))  # "FY2026"

# Comparison
jan_2026 < feb_2026  # True

# Difference
feb_2026 - jan_2026  # 1 (month)

# Parsing
FiscalPeriod.from_string("2026-01")  # FiscalPeriod(2026, 1, "month")
FiscalPeriod.from_string("2026-Q1")  # FiscalPeriod(2026, 1, "quarter")
FiscalPeriod.from_string("FY2026")   # FiscalPeriod(2026, 1, "year")
```

---

## 5. `ExchangeRate`

### Canonical Definition

```python
@dataclass(frozen=True)
class ExchangeRate:
    """An exchange rate between two currencies on a given date.
    
    The rate is expressed as: 1 unit of from_currency = rate units of to_currency.
    For example, ExchangeRate(USD, EUR, 0.92, date(2026, 7, 15))
    means 1 USD = 0.92 EUR.
    
    The inverse rate is automatically computed and cached.
    """
    from_currency: CurrencyCode
    to_currency: CurrencyCode
    rate: Decimal
    date: date
```

### Invariants

| Invariant | Enforcement | Error Message |
|-----------|-------------|---------------|
| `rate` must be positive (> 0) | Check in `__post_init__` | `"Exchange rate must be positive, got <rate>"` |
| `rate` precision ≤ 8 decimal places | Decimal quantize | `"Exchange rate precision exceeds 8 decimal places"` |
| `from_currency` ≠ `to_currency` | Check | `"Cannot have exchange rate from <code> to itself"` |

### Inverse Rate

```python
@cached_property
def inverse(self) -> ExchangeRate:
    """The inverse exchange rate (to → from).
    
    Computed as 1 / rate and cached for subsequent access.
    """
    return ExchangeRate(
        from_currency=self.to_currency,
        to_currency=self.from_currency,
        rate=(Decimal("1") / self.rate).quantize(Decimal("0.00000001")),
        date=self.date,
    )
```

### Application

```python
def convert(self, amount: Money) -> Money:
    """Convert a Money amount using this rate.
    
    Args:
        amount: Money in from_currency.
    
    Returns:
        Money in to_currency.
    
    Raises:
        CurrencyMismatchError: If amount.currency != self.from_currency.
    """
    if amount.currency != self.from_currency:
        raise CurrencyMismatchError(
            amount.currency, self.from_currency,
            "Exchange rate conversion"
        )
    return amount.convert(self.to_currency, self.rate)
```

### Examples

```python
eur_to_usd = ExchangeRate(
    from_currency=CurrencyCode("EUR"),
    to_currency=CurrencyCode("USD"),
    rate=Decimal("1.08"),
    date=date(2026, 7, 15),
)

# Conversion
revenue_eur = Money(Decimal("1000000.00"), CurrencyCode("EUR"))
revenue_usd = eur_to_usd.convert(revenue_eur)
# Money(1080000.00, USD)

# Inverse
usd_to_eur = eur_to_usd.inverse
# ExchangeRate(USD, EUR, 0.9259..., date(2026, 7, 15))
```

---

## 6. Typed Identifier Wrappers

### Design Pattern

Each of these is a lightweight frozen dataclass wrapping a `str` with format validation. They exist to prevent primitive obsession — exchanging a `CostCenter` where a `GLAccountNumber` is expected should be a type error, not a runtime bug.

### `GLAccountNumber`

```python
@dataclass(frozen=True)
class GLAccountNumber:
    """A General Ledger account number.
    
    Format varies by entity but is typically a dot-separated or
    fixed-width number. Validation is entity-specific.
    """
    number: str
    
    def __post_init__(self) -> None:
        # Strip whitespace, uppercase
        object.__setattr__(self, "number", self.number.strip())
        if not self.number:
            raise ValueError("GL account number cannot be empty")
    
    def __str__(self) -> str:
        return self.number
```

### `CostCenter`

```python
@dataclass(frozen=True)
class CostCenter:
    """A cost center identifier.
    
    Typically an alphanumeric code assigned by the organization.
    Validated against the cost center registry at construction.
    """
    code: str
    _registry: ClassVar[set[str]] = set()  # Populated at startup
    
    def __post_init__(self) -> None:
        code = self.code.strip().upper()
        object.__setattr__(self, "code", code)
        if not code:
            raise ValueError("Cost center code cannot be empty")
    
    @classmethod
    def register(cls, code: str) -> None:
        """Register a valid cost center code."""
        cls._registry.add(code.strip().upper())
    
    @property
    def is_valid(self) -> bool:
        """Check if this cost center is in the registry."""
        return self.code in self._registry
```

### `Department`, `EntityId`, `VendorId`

```python
@dataclass(frozen=True)
class Department:
    """A department identifier within the organization."""
    code: str
    
    def __post_init__(self) -> None:
        code = self.code.strip()
        object.__setattr__(self, "code", code)
        if not code:
            raise ValueError("Department code cannot be empty")


@dataclass(frozen=True)
class EntityId:
    """A legal entity / tenant identifier."""
    id: str
    
    def __post_init__(self) -> None:
        _id = self.id.strip()
        object.__setattr__(self, "id", _id)
        if not _id:
            raise ValueError("Entity ID cannot be empty")


@dataclass(frozen=True)
class VendorId:
    """A vendor/supplier identifier."""
    id: str
    
    def __post_init__(self) -> None:
        _id = self.id.strip()
        object.__setattr__(self, "id", _id)
        if not _id:
            raise ValueError("Vendor ID cannot be empty")
```

---

## Serialization Summary

| Object | `to_dict()` | `to_json()` | `from_dict()` | Notes |
|--------|-------------|-------------|---------------|-------|
| `Money` | `{"amount": "str(Decimal)", "currency": "str"}` | JSON string | `from_dict(dict)` | Amount serialized as string to preserve precision |
| `Percentage` | `{"value": "str(Decimal)", "formatted": "str"}` | JSON string | `from_decimal(Decimal)` | Formatted key added |
| `CurrencyCode` | `{"code": "str"}` | `str(code)` | `CurrencyCode(str)` | Simple wrapper |
| `FiscalPeriod` | `{"year": int, "period": int, "type": str, "period_str": str}` | JSON string | `from_string(str)` | Period_str is the canonical key |
| `ExchangeRate` | `{"from": str, "to": str, "rate": str, "date": "iso", "inverse_rate": str}` | JSON string | `from_dict(dict)` | Inverse rate included |
| `GLAccountNumber` | `str(number)` | `str(number)` | `GLAccountNumber(str)` | |
| `CostCenter` | `str(code)` | `str(code)` | `CostCenter(str)` | |

---

## Implementation Location

Proposed directory structure:

```
shared/
└── value_objects/
    ├── __init__.py              # Re-exports all canonical objects
    ├── money.py                 # Money class
    ├── percentage.py            # Percentage class
    ├── currency.py              # CurrencyCode class
    ├── fiscal_period.py         # FiscalPeriod class
    ├── exchange_rate.py         # ExchangeRate class
    ├── identifiers.py           # GLAccountNumber, CostCenter, Department, EntityId, VendorId
    ├── _errors.py               # CurrencyMismatchError, DivisionByZeroError, etc.
    └── _iso_currencies.py       # ISO 4217 currency set
```

`shared/` is the correct layer for canonical value objects because:
1. They have **zero internal dependencies** — no import of `finance/`, `agents/`, or `apps/`.
2. They are used **across all layers** — domain models, data contracts, API schemas, agent context.
3. They provide **structural guarantees** that the rest of the system depends on.

---

## Migration from Current Usage

| Current Pattern | Replacement | Impact |
|----------------|-------------|--------|
| `amount: Decimal` on domain models | `amount: Money` | Requires currency field on every monetary model |
| `percentage: float` in materiality rules | `percentage: Percentage` | Replaces `float` with `Decimal`-based type |
| `currency: str` in entities | `currency: CurrencyCode` | Validation at Pydantic boundary |
| `period: str` in all models | `period: FiscalPeriod` | Breaks legacy string-period code; major migration |
| `gl_account_number: str` | `gl_account_number: GLAccountNumber` | Minimal — same string semantics, with validation |

**Migration strategy:** Phase in during normal development. New code must use canonical objects. Legacy code can be migrated incrementally with adapter functions.

---

*This document defines the canonical value objects for the FinSight Business Knowledge Layer. Last updated: 2026-07-30.*
