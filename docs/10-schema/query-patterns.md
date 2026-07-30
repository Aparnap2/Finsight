# Query Patterns & Optimization

## Period-over-Period Variance

```sql
SELECT
    a.account_id,
    ga.account_name,
    curr.amount AS current_amount,
    prev.amount AS previous_amount,
    (curr.amount - prev.amount) AS variance,
    CASE WHEN prev.amount <> 0
        THEN ((curr.amount - prev.amount) / prev.amount) * 100
        ELSE NULL
    END AS variance_pct
FROM actuals curr
JOIN gl_accounts ga ON ga.id = curr.account_id
LEFT JOIN actuals prev ON prev.account_id = curr.account_id
    AND prev.entity_id = curr.entity_id
    AND prev.period = to_char(
        to_date(curr.period, 'YYYY-MM') - INTERVAL '1 month',
        'YYYY-MM'
    )
WHERE curr.entity_id = :entity_id
  AND curr.period = :period;
```

**Index needed:** `(entity_id, period, account_id)` covering `amount`.

## Account Hierarchical Rollup

```sql
WITH RECURSIVE account_tree AS (
    -- Anchor: top-level accounts
    SELECT id, account_number, account_name, parent_id, 0 AS level
    FROM gl_accounts
    WHERE parent_id IS NULL AND entity_id = :entity_id
    UNION ALL
    -- Recursive: children
    SELECT c.id, c.account_number, c.account_name, c.parent_id, p.level + 1
    FROM gl_accounts c
    JOIN account_tree p ON p.id = c.parent_id
)
SELECT at.level, at.account_name, a.amount
FROM account_tree at
LEFT JOIN actuals a ON a.account_id = at.id
    AND a.entity_id = :entity_id AND a.period = :period
ORDER BY at.path;
```

**Index needed:** `gl_accounts(entity_id, parent_id)`.

## Multi-Tenant Isolation

```sql
-- RLS handles this automatically via app.tenant_id
-- But for bulk exports:
SELECT * FROM actuals
WHERE entity_id = :tenant_id
  AND period BETWEEN :start AND :end
ORDER BY period, account_id;
```

**Index needed:** `(entity_id, period, account_id)`.

## Materialized View Candidates

### Monthly Variance Summary

```sql
CREATE MATERIALIZED VIEW mv_monthly_variance AS
SELECT
    a.entity_id,
    a.period,
    a.account_id,
    a.amount AS actual_amount,
    b.amount AS budget_amount,
    (a.amount - b.amount) AS variance_amount,
    CASE WHEN b.amount <> 0
        THEN ((a.amount - b.amount) / b.amount) * 100
        ELSE NULL
    END AS variance_pct
FROM actuals a
LEFT JOIN budget_lines b ON b.entity_id = a.entity_id
    AND b.account_id = a.account_id
    AND b.period = a.period;

CREATE UNIQUE INDEX ON mv_monthly_variance (entity_id, period, account_id);

-- Refresh after each ingestion
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_monthly_variance;
```

### Account Rollup Summary

```sql
CREATE MATERIALIZED VIEW mv_account_rollup AS
WITH RECURSIVE account_tree (...) ...
```

## N+1 Prevention

- Batch load children: `SELECT * FROM gl_accounts WHERE parent_id = ANY(:ids)`
- Use `selectinload` in SQLAlchemy for relationship loading
- Eager load `account` on `Actual` queries with `joinedload(Actual.account)`

## Batch Insert Patterns

```python
# Use bulk_insert_mappings for ingestion
session.bulk_insert_mappings(
    Actual,
    [{"id": str(uuid4()), "entity_id": e, "period": p, ...} for e in records]
)
```

Or raw COPY for CSV ingestion:

```sql
COPY actuals (id, entity_id, period, account_id, department, amount)
FROM '/tmp/batch.csv' DELIMITER ',' CSV HEADER;
```
