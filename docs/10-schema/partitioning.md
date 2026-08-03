# Table Partitioning Design

## Partitioning Strategy

### Partitioned Tables

| Table | Strategy | Partition Key | Interval | Retention |
|-------|----------|---------------|----------|-----------|
| `actuals` | RANGE | `period` | 1 quarter | 10 years |
| `trial_balance` | RANGE | `period` | 1 quarter | 10 years |
| `forecast_lines` | RANGE | `period` | 1 quarter | 5 years |
| `budget_lines` | RANGE | `period` | 1 year | 10 years |
| `audit_logs` | RANGE | `created_at` | 1 month | 7 years |
| `variance_snapshots` | RANGE | `created_at` | 1 quarter | 7 years |

### Partition DDL

```sql
-- Actuals — quarterly partitions
CREATE TABLE actuals (
    id          TEXT NOT NULL,
    entity_id   TEXT NOT NULL REFERENCES entities(id),
    period      VARCHAR(7) NOT NULL,
    account_id  TEXT NOT NULL REFERENCES gl_accounts(id),
    department  TEXT,
    amount      NUMERIC(15,2) NOT NULL,
    PRIMARY KEY (id, period)
) PARTITION BY RANGE (period);

CREATE TABLE actuals_2024_q1 PARTITION OF actuals
    FOR VALUES FROM ('2024-01') TO ('2024-04');
CREATE TABLE actuals_2024_q2 PARTITION OF actuals
    FOR VALUES FROM ('2024-04') TO ('2024-07');
CREATE TABLE actuals_2024_q3 PARTITION OF actuals
    FOR VALUES FROM ('2024-07') TO ('2024-10');
CREATE TABLE actuals_2024_q4 PARTITION OF actuals
    FOR VALUES FROM ('2024-10') TO ('2025-01');
```

```sql
-- Audit logs — monthly partitions
CREATE TABLE audit_logs (
    id          TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    period      VARCHAR(7) NOT NULL,
    event_type  TEXT NOT NULL,
    event_data  JSONB,
    user_id     TEXT,
    created_at  TIMESTAMP NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

CREATE TABLE audit_logs_2026_07 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
```

```sql
-- Budget lines — yearly partitions
CREATE TABLE budget_lines (
    id          TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    period      VARCHAR(7) NOT NULL,
    account_id  TEXT NOT NULL,
    department  TEXT,
    amount      NUMERIC(15,2) NOT NULL,
    notes       TEXT,
    PRIMARY KEY (id, period)
) PARTITION BY RANGE (period);

CREATE TABLE budget_lines_2026 PARTITION OF budget_lines
    FOR VALUES FROM ('2026-01') TO ('2027-01');
```

### Partition Pruning

Queries that filter on the partition key prune automatically:

```sql
-- Only scans actuals_2024_q3
EXPLAIN SELECT SUM(amount) FROM actuals
WHERE period >= '2024-07' AND period < '2024-10'
  AND entity_id = 'ent-1';

-- Seq Scan on actuals_2024_q3  (cost=0.00..35.00 rows=...)
```

### Retention Policy (pg_partman)

```sql
CREATE EXTENSION pg_partman;

SELECT partman.create_parent(
    p_parent_table   := 'public.actuals',
    p_control        := 'period',
    p_type           := 'range',
    p_interval       := '3 months',
    p_premake        := 4,
    p_start_partition := '2024-01-01'
);

-- Detach + drop partitions older than 10 years
SELECT partman.undo_partition(
    p_parent_table  := 'public.actuals',
    p_interval      := '3 months',
    p_batch         := 1,
    p_keep          := 40   -- 10 years of quarterly
);
```

### Converting Existing Tables

1. Create partitioned table with same schema
2. Create default partition for out-of-range data
3. INSERT INTO partitioned SELECT FROM existing (batched)
4. RENAME tables
5. Recreate indexes on new parent

### Indexing Partitions

Indexes on the parent table automatically propagate to children:

```sql
CREATE INDEX idx_actuals_entity ON actuals (entity_id, period);
```
