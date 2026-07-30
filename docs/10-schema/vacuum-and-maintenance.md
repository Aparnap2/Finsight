# Vacuum & Maintenance Strategy

## Autovacuum Tuning

### Default Settings

```ini
# postgresql.conf
autovacuum = on
autovacuum_max_workers = 3
autovacuum_naptime = 1min
autovacuum_vacuum_threshold = 50
autovacuum_vacuum_scale_factor = 0.2
autovacuum_analyze_threshold = 50
autovacuum_analyze_scale_factor = 0.1
```

### Per-Table Tuning

| Table | Scale Factor | Threshold | Freeze Age | Notes |
|-------|-------------|-----------|------------|-------|
| actuals | 0.05 | 1000 | 200M | Heavy writes, low tolerance for bloat |
| trial_balance | 0.05 | 1000 | 200M | Same as actuals |
| forecast_lines | 0.1 | 500 | 300M | Moderate writes |
| budget_lines | 0.2 | 100 | 400M | Write-once, rarely updated |
| audit_logs | 0.01 | 5000 | 150M | Append-only, high volume |
| agent_runs | 0.1 | 500 | 300M | Moderate writes |
| entities | 0.2 | 50 | 500M | Rarely updated |
| gl_accounts | 0.2 | 50 | 500M | Rarely updated |

```sql
ALTER TABLE actuals SET (
    autovacuum_vacuum_scale_factor = 0.05,
    autovacuum_vacuum_threshold = 1000,
    autovacuum_freeze_min_age = 200000000
);

ALTER TABLE audit_logs SET (
    autovacuum_vacuum_scale_factor = 0.01,
    autovacuum_vacuum_threshold = 5000,
    autovacuum_freeze_min_age = 150000000
);
```

### Why Tune?

Financial workloads have distinct write patterns:
- **Bulk ingestion**: actuals/budget inserts in large batches (end-of-period loads)
- **Append-heavy**: audit_logs, variance_snapshots (never updated)
- **Read-heavy**: gl_accounts, entities (rarely change, no vacuum needed)
- **Update-in-place**: agent_runs status transitions (frequent small updates)

## Bloat Monitoring

```sql
-- Table bloat estimation
SELECT
    schemaname || '.' || relname AS table_name,
    n_dead_tup,
    n_live_tup,
    round(n_dead_tup * 100.0 / GREATEST(n_live_tup + n_dead_tup, 1), 2) AS dead_pct,
    last_autovacuum,
    last_vacuum
FROM pg_stat_all_tables
WHERE schemaname = 'public'
  AND n_dead_tup > 1000
ORDER BY dead_pct DESC;

-- Index bloat
SELECT
    indexrelname AS index_name,
    round(avg_leaf_density * 100) AS density_pct,
    pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
FROM pg_stat_user_indexes
JOIN pg_index USING (indexrelid)
CROSS JOIN LATERAL (
    SELECT avg(leaf_density) AS avg_leaf_density
    FROM pgstatindex(indexrelname::text)
) stats;
```

### Thresholds

| Metric | Warning | Critical | Action |
|--------|---------|----------|--------|
| Dead tuple % | > 20% | > 40% | Manual VACUUM |
| Index bloat | > 30% | > 50% | REINDEX CONCURRENTLY |
| Table bloat | > 50% | > 100% | VACUUM FULL (off-hours) |
| Transaction age | < 500M remaining | < 200M remaining | Aggressive freeze |

## Scheduled Maintenance

```bash
# Weekly — light cleanup
docker compose exec postgres vacuumdb --all --analyze-in-stages -U finsight

# Monthly — aggressive freeze during low-traffic window (Sunday 02:00)
docker compose exec postgres vacuumdb --all --freeze --verbose -U finsight

# Quarterly — REINDEX if bloat detected
docker compose exec postgres reindexdb --concurrently --verbose -U finsight
```

## Anti-Wraparound Strategy

```ini
# Prevent XID wraparound — set conservative thresholds
autovacuum_freeze_max_age = 500000000
autovacuum_multixact_freeze_max_age = 400000000
```

Monitoring:

```sql
SELECT
    relname,
    age(relfrozenxid) AS xid_age,
    mxid_age(relminmxid) AS mxid_age,
    round(100.0 * age(relfrozenxid) / 500000000, 1) AS xid_pct
FROM pg_class
WHERE relkind = 'r' AND relnamespace = 'public'::regnamespace
ORDER BY xid_age DESC;
```

## REINDEX Strategy

- Always use `REINDEX INDEX CONCURRENTLY` to avoid table locks
- Schedule during low write volume
- Target indexes > 30% bloat or after bulk loads

```sql
REINDEX INDEX CONCURRENTLY idx_actuals_entity_period;
```

## ANALYZE Frequency

- After every bulk ingestion (end-of-period load)
- Default autovacuum analyze is sufficient for normal operations
- Manually: `ANALYZE actuals, budget_lines;`

## Partition Maintenance

For partitioned tables, vacuum/analyze each partition individually:

```sql
-- Autovacuum works on partitions independently
-- Manual:
VACUUM ANALYZE actuals_2024_q3;
```
