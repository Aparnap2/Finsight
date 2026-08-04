# Domain Validation Report — Issue #7 (A2)

**Branch:** `feat/verification-readiness`
**Scope:** `tests/unit/test_domain/`
**Date:** 2026-08-04

## Executive Summary

Completed the domain validation effort for Issue #7. The domain test suite
grew from **138** to **703** passing tests (+565), covering **24 domain
aggregates** across the `finance/domain`, `business/ontology`,
`business/canonical_types`, `business/events`, and `shared/models` layers.

The effort surfaced **4 real defects** in production code (see
[Defects Found](#defects-found)), all of which are documented with
regression tests that pin the current behaviour. No production code was
modified — this issue is test-only by design.

## Scope & Method

- **Target:** 250+ tests across 15 domain aggregates. **Achieved: 703 tests
  across 24 aggregates.**
- **Style:** class-per-test-group (`TestX`), Arrange-Act-Assert, helper
  builders (`_money`, `_line`, `_entity`, …), `pytest.raises` for rejection
  paths, `Decimal`-only monetary assertions.
- **Monetary rule:** every monetary field is asserted to reject `float`
  at the API schema boundary (via `MoneyDecimal`) and to coerce
  `str`/`int` input; the `Money` / `ExchangeRate` value objects coerce
  `float` to `Decimal` (lossy) and are not asserted to reject it directly.
- **Property tests:** the plan called for `hypothesis` property tests, but
  `hypothesis` is **not installed** and cannot be added (no `pip`/`uv`
  access in this environment). Property-style invariants are instead
  enforced deterministically in `test_property.py` by iterating over
  generated datasets and asserting invariants that must hold for every
  value (commutativity, associativity, inverse, closure, round-trip).

## Coverage Matrix (24 aggregates)

| # | Aggregate | Module | Tests | Status |
|---|-----------|--------|------:|--------|
| 1 | Money / Percentage / ExchangeRate / Currency | `business/canonical_types` | 64 | PASS |
| 2 | Budget | `finance/domain/budget.py` | 28 | PASS |
| 3 | Variance | `finance/domain/variance.py` | 46 | PASS |
| 4 | Invoice (events) | `business/events/models.py` | 36 | PASS |
| 5 | Vendor / identifiers | `business/canonical_types/identifiers.py` | 37 | PASS |
| 6 | Forecast | `finance/domain/forecast.py` | 28 | PASS |
| 7 | Ledger (double-entry) | `business/ontology/ledger.py` | 29 | PASS |
| 8 | Trial Balance | ledger projection | 20 | PASS |
| 9 | Statements (BS/IS/CF) | `business/ontology/statements.py` | 49 | PASS |
| 10 | Recommendation | `finance/domain/recommendation.py` | 34 | PASS |
| 11 | Evidence | `finance/domain/evidence.py` | 31 | PASS |
| 12 | Assertion | `shared/models/assertions.py` | 34 | PASS |
| 13 | Commentary | `shared/models/state.py` | 27 | PASS |
| 14 | Actual | `finance/domain/actual.py` | 23 | PASS |
| 15 | Transaction | `finance/domain/transaction.py` | 23 | PASS |
| 16 | Chart of Accounts | `finance/domain/chart_of_accounts.py` | 24 | PASS |
| 17 | Company | `finance/domain/company.py` | 17 | PASS |
| 18 | Driver | `finance/domain/driver.py` | 29 | PASS |
| 19 | KPI | `finance/domain/kpi.py` | 28 | PASS |
| 20 | Fiscal Calendar | `finance/domain/fiscal_calendar.py` | 20 | PASS |
| 21 | Board Report | `finance/domain/board_report.py` | 28 | PASS |
| 22 | Cost Center | `finance/domain/cost_center.py` | 13 | PASS |
| 23 | Department | `finance/domain/department.py` | 12 | PASS |
| 24 | Property invariants | `test_property.py` | 23 | PASS |
| | **Total** | | **703** | **PASS** |

## Defects Found

Four defects were identified and documented with regression tests that pin
the current behaviour. Each is a candidate for a follow-up fix.

### D1 — `Money.__mul__` is not closed under quantization
**File:** `business/canonical_types/money.py` (`__mul__`, line ~132)
**Test:** `test_property.py::TestMoneyArithmeticProperties::test_multiplication_not_closed_under_quantization`

`Money.__mul__` returns the raw product without quantizing to 4 decimal
places (unlike `Money.convert`, which does quantize). Multiplying a valid
`Money` by a multi-place factor can therefore raise `ValidationError`
instead of returning a `Money`:

```python
Money(Decimal("0.0001"), USD) * Decimal("3.5")  # 0.00035 → raises
```

**Impact:** valid monetary arithmetic can fail at runtime. **Fix:** quantize
the product to `Decimal("0.0001")` in `__mul__`.

### D2 — `FiscalPeriod` accepts invalid quarter/year periods
**File:** `business/canonical_types/fiscal_period.py` (`_validate_period`)
**Test:** `test_property.py::TestFiscalPeriodProperties::test_invalid_quarter_period_not_rejected`, `test_invalid_year_period_not_rejected`

The period validator reads `info.data.get("type", "month")` to pick the
valid range, but pydantic validates fields in declaration order
(`year`, `period`, `type`) — so `type` is **not yet available** when
`period` is validated, and the `"month"` default is always used. As a
result:

- `FiscalPeriod(year=2026, period=6, type="quarter")` constructs (should be rejected; quarter range is 1-4).
- `FiscalPeriod(year=2026, period=12, type="quarter")` constructs.
- `FiscalPeriod(year=2026, period=6, type="year")` constructs (year period must be 1).

**Fix:** move the range check into a `model_validator(mode="after")` (or
reorder so `type` is validated first).

### D3 — `MoneyDecimal` does not enforce 4-dp precision
**File:** `finance/domain/_types.py`
**Test:** `test_recommendation.py::TestRecommendationImpact::test_high_precision_impact_preserved`

The finance-domain `MoneyDecimal` alias rejects `float` but does **not**
quantize or reject values with more than 4 decimal places, unlike
`business.canonical_types.Money`. A 5-dp value (e.g. `"1.00001"`) is
accepted at the model boundary and only normalized downstream.

**Impact:** inconsistent precision guarantees between the two money types.
**Fix:** add a precision validator to `MoneyDecimal` (or document that
quantization is deferred to engines).

### D4 — `Assertion.value` and `Assertion.confidence` accept out-of-range / float input
**File:** `shared/models/assertions.py`
**Test:** `test_assertion.py::TestAssertionValue::test_confidence_out_of_range_representable`

`Assertion.value` is a plain `Decimal | None` (no float rejection, no
precision guard) and `confidence` is a plain `float` with no `[0, 1]` range
check. A confidence of `1.5` is accepted. The model is a container; callers
must validate. **Fix:** add a `[0, 1]` range validator for `confidence` and
a float-rejection guard for `value` if these are treated as monetary.

## Residual Risks / Notes

- **No standalone `TrialBalance` Pydantic aggregate** exists in production
  (only a SQLAlchemy model in `shared/models/database.py`). Trial-balance
  invariants are tested through the ledger ontology and a projection helper
  in `test_trial_balance.py`. The projection nets each account to a single
  side to match the physical `trial_balance` CHECK constraints
  (`debit = 0 OR credit = 0`).
- **Invoice/Vendor have no Pydantic domain model** (only DB tables and
  feature-store builders that require `polars`). Tests target the closest
  real classes: `business/events/models.py` events and typed identifiers.
  The `InvoiceImported` event allows negative amounts and empty `vendor_id`
  (no such invariant exists) — tests assert representability, not rejection.
- **Commentary** lives in `shared/models/state.py` (`CommentarySection`,
  `CommentaryDraft`) and `apps/api/schemas.py`; there is no
  `finance/domain/commentary.py`.

## Verification Gates

| Gate | Command | Result |
|------|---------|--------|
| Domain tests | `pytest tests/unit/test_domain/ -q` | **703 passed** |
| Lint | `uv run ruff check .` | **NOT RUN** — `uv`/`ruff` blocked by sandbox permissions |
| Type-check | `uv run python -m mypy .` | **NOT RUN** — `uv`/`mypy` blocked by sandbox permissions |
| Full suite | `pytest -q` | **BLOCKED** — pre-existing collection errors: `polars`, `pytest_httpx`, `starlette`, `psycopg` not installed in this environment |

> The sandbox only permits `pytest <path>` invocations; `uv`, `git`, `ruff`,
> `mypy`, and `pip` are denied. The lint/type-check gates must be run in a
> full environment before merge. The full-suite collection errors are
> pre-existing (missing third-party deps) and unrelated to this change.

## Files Added

```
tests/unit/test_domain/test_invoice.py
tests/unit/test_domain/test_vendor.py
tests/unit/test_domain/test_forecast.py
tests/unit/test_domain/test_ledger.py
tests/unit/test_domain/test_trial_balance.py
tests/unit/test_domain/test_statements.py
tests/unit/test_domain/test_recommendation.py
tests/unit/test_domain/test_evidence.py
tests/unit/test_domain/test_assertion.py
tests/unit/test_domain/test_commentary.py
tests/unit/test_domain/test_actual.py
tests/unit/test_domain/test_transaction.py
tests/unit/test_domain/test_chart_of_accounts.py
tests/unit/test_domain/test_company.py
tests/unit/test_domain/test_driver.py
tests/unit/test_domain/test_kpi.py
tests/unit/test_domain/test_fiscal_calendar.py
tests/unit/test_domain/test_board_report.py
tests/unit/test_domain/test_cost_center.py
tests/unit/test_domain/test_department.py
tests/unit/test_domain/test_property.py
```

## Recommended Follow-ups

1. Fix D1 (`Money.__mul__` quantization) and D2 (`FiscalPeriod` validator
   ordering) — both are low-risk, high-value correctness fixes.
2. Reconcile D3 (`MoneyDecimal` precision) with `Money` quantization.
3. Add a standalone `TrialBalance` Pydantic aggregate to production so the
   invariant is enforced at the domain layer rather than in tests.
4. Run `ruff` and `mypy` in a full environment and re-run the complete suite
   once `polars`/`pytest_httpx`/`starlette`/`psycopg` are installed.