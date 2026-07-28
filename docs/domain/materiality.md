# Materiality

## Business Meaning

**Materiality** is the concept that determines which variances are significant enough to warrant investigation, commentary, and action. The materiality engine acts as a filter — it separates variances that matter from those that are within an acceptable range of expectation. This ensures that financial commentary focuses attention on the areas of greatest business impact.

The materiality engine in FinSight is **100% deterministic** — it uses no LLM or external service. All materiality decisions are made through configurable threshold rules applied consistently across all accounts.

## Sensitivity Tiers

Accounts are classified into sensitivity tiers that reflect their strategic importance to the business:

| Tier | Label | Typical Accounts | Default % Threshold | Default Absolute Threshold |
|------|-------|-----------------|-------------------|--------------------------|
| **CRITICAL** | Highest scrutiny | Revenue (4xxx), Cash | 3% | \$50,000 |
| **HIGH** | Above-average scrutiny | COGS (5xxx), Gross Margin | 5% | \$100,000 |
| **MEDIUM** | Standard scrutiny | Operating Expenses (6xxx) | 10% | \$250,000 |
| **LOW** | Minimal scrutiny | Other Income/Expense (7xxx), Balance Sheet (8xxx), Statistical (9xxx) | 15% | \$500,000 |

### Tier Characteristics

- **CRITICAL** accounts have the **lowest thresholds** — they are the most sensitive and trigger investigation for smaller relative movements.
- **LOW** accounts have the **highest thresholds** — only significant deviations trigger investigation.
- Tier assignment drives both the percentage and absolute thresholds used in materiality assessment.

## Threshold Configuration

Each materiality rule contains two threshold dimensions:

### Percentage Threshold (`pct_threshold`)

The minimum absolute percentage variance that is considered material. Expressed as a decimal (e.g., `0.03` = 3%).

```
Is Material by % = abs(variance_pct) > pct_threshold × 100
```

### Absolute Threshold (`abs_threshold`)

The minimum absolute monetary variance that is considered material. Expressed as a `Decimal` monetary value.

```
Is Material by $ = abs(variance_amount) > abs_threshold
```

### Default Values (as Decimal)

```python
DEFAULT_CRITICAL_PCT = Decimal("0.03")    # 3%
DEFAULT_CRITICAL_ABS = Decimal("50000")   # $50,000

DEFAULT_HIGH_PCT     = Decimal("0.05")    # 5%
DEFAULT_HIGH_ABS     = Decimal("100000")  # $100,000

DEFAULT_MEDIUM_PCT   = Decimal("0.10")    # 10%
DEFAULT_MEDIUM_ABS   = Decimal("250000")  # $250,000

DEFAULT_LOW_PCT      = Decimal("0.15")    # 15%
DEFAULT_LOW_ABS      = Decimal("500000")  # $500,000
```

All thresholds use `decimal.Decimal` — never `float` — to avoid floating-point rounding errors in materiality decisions.

## Combined Rules

The `combined_rule` field on a `MaterialityRule` determines how the two thresholds interact:

| Rule | Behavior | Use Case |
|------|----------|----------|
| **`"any"`** | Material if EITHER % threshold OR \$ threshold is exceeded (inclusive OR) | Default — catches both large-percentage-but-small-dollar and small-percentage-but-large-dollar variances |
| **`"both"`** | Material only if BOTH % threshold AND \$ threshold are exceeded (AND) | Stricter — requires significance in both relative and absolute terms |

**Default**: All tiers use `"any"`.

## Account-to-Tier Mappings

The default account-to-tier mapping uses glob patterns on account codes:

| Pattern | Tier | Example Accounts |
|---------|------|-----------------|
| `4*` | **CRITICAL** | 4100 (Product Revenue), 4200 (Service Revenue) |
| `5*` | **HIGH** | 5100 (Direct Materials), 5200 (Direct Labor) |
| `6*` | **MEDIUM** | 6100 (Sales & Marketing), 6200 (R&D) |
| `7*`, `8*`, `9*` | **LOW** | 7100 (Interest Income), 8100 (Current Assets) |

### Classification Priority

Account classification follows a priority order:

1. **Exact account code match** — tenant-specific overrides checked first.
2. **Glob pattern match** — first matching pattern wins, checked in tier priority order (CRITICAL → HIGH → MEDIUM → LOW).
3. **Fallback** — if no match is found, defaults to **MEDIUM**.

This is implemented in `MaterialityEngine.classify_account()` in `finance/variance_engine/materiality.py`.

## Tenant-Specific Overrides

Individual companies (tenants) can override the global default configuration:

```python
class TenantMaterialityConfig(BaseModel):
    tenant_id: str
    rules: list[MaterialityRule]         # tenant-specific rules
    base_config: MaterialityConfig       # global defaults to merge with
```

### Merge Logic

When tenant rules are applied:

1. Start with the global base configuration.
2. Add all tenant rules to their respective tiers.
3. If a tenant rule has the same exact `account_code` as a base rule, the base rule is **replaced** by the tenant rule.
4. Pattern-based rules from the tenant are appended alongside base pattern rules (they do not replace base patterns).

This allows, for example, raising the revenue threshold for a specific entity: `MaterialityRule(account_code="4100", pct_threshold="0.05", ...)`.

## Materiality Assessment Output

Each variance assessed by the materiality engine produces a `MaterialityAssessment`:

| Field | Description |
|-------|-------------|
| `variance_id` | Account identifier of the variance |
| `account_id` | Account code |
| `account_name` | Human-readable account name |
| `tier` | Sensitivity tier assigned (CRITICAL/HIGH/MEDIUM/LOW) |
| `variance_pct` | Percentage variance (absolute) |
| `variance_abs` | Absolute monetary variance |
| `pct_exceeds` | Whether the percentage threshold was exceeded |
| `abs_exceeds` | Whether the absolute threshold was exceeded |
| `is_material` | Final materiality decision |
| `rule_matched` | The specific rule that produced the decision |

## Edge Cases

### Negative Variances

The materiality engine uses **absolute values** for threshold comparison:

```python
abs_variance = abs(variance.variance_amount)
abs_pct = abs(variance.variance_pct)

pct_exceeds = abs_pct > rule.pct_threshold * 100
abs_exceeds = abs_variance > rule.abs_threshold
```

This means a -6% variance is treated identically to a +6% variance for materiality purposes — both exceed the CRITICAL 3% threshold. The direction (favorable vs. adverse) is determined later by the commentary pipeline, not by the materiality engine.

### Zero Variances

When `variance_amount` is zero:

- `abs_variance = 0`
- `abs_pct = 0`
- Neither threshold is exceeded.
- `is_material = False`.
- No special handling required — zero variances naturally fall below all thresholds.

### Zero Budget (Division by Zero)

When budget is zero, `variance_pct` is mathematically undefined. The materiality engine handles this by:

- The percentage threshold check will not be exceeded (the variance_pct from the variance engine is set to `0` for zero-budget cases).
- The absolute threshold is the only effective criterion.
- The assessment notes the zero-budget condition in the matched rule metadata.

### Rounding

All threshold comparisons use `Decimal` arithmetic with no floating-point conversions. Comparisons use strict greater-than (`>`), not greater-than-or-equal (`>=`). This means:

- A variance exactly equal to the threshold is **not material**.
- To avoid edge-case disputes, thresholds can be configured with additional decimal places (e.g., `0.0301` instead of `0.03`).

### Batch Assessment Sorting

When assessing multiple variances in batch, results are sorted by severity:

1. Material variances first.
2. Within material/non-material groups, larger absolute variances first.

This ensures the most significant items appear at the top of assessment reports.
