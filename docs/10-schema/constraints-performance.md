# Constraint Performance Impact

## Cost Summary

| Constraint | Planning Cost | Write Cost | Read Benefit | Storage Overhead |
|------------|--------------|------------|--------------|------------------|
| NOT NULL | None | None | High (optimizer) | None |
| CHECK | None | Negligible | Medium (trust) | None |
| UNIQUE | Low | B-tree insert | High (stats) | B-tree index |
| FOREIGN KEY | Low | Trigger on write | Low | None |
| EXCLUDE | Low | GiST index write | High (if queried) | GiST index |
| GENERATED (STORED) | None | Write + recompute | Low | Full column |
| GENERATED (VIRTUAL) | None | None | None | None |
| RLS | Moderate per query | None | None | None |

## NOT NULL

- Zero cost: stored in the null bitmap header (2 bytes per row, always present)
- Planner benefits: can use anti-join and other optimizations knowing a column is non-null
- **Always use** for columns that should never be null

## CHECK Constraints

- Evaluated inline with the write — no additional I/O
- No index overhead
- Cost per row: sub-microsecond for simple expressions (`amount > 0`)
- Planner can use constraints for partition pruning and join simplification
- For complex CHECK involving subqueries (not supported in PostgreSQL), use triggers instead

## UNIQUE Constraints

- Backed by a B-tree index — introduces write overhead (O(log n))
- Multi-column unique on `(entity_id, period, account_id)`:
  - Index size: ~\( 16 + 4 \times (\text{approx } 2\times \text{table size}) \) bytes
  - INSERT: one B-tree insert
  - UPDATE: one B-tree delete + one insert
  - DELETE: one B-tree delete
- **Partial UNIQUE** on nullable columns: NULLs excluded from the index, saving space

## FOREIGN KEY Constraints

- No cost on read (planner may use for join elimination)
- On INSERT: checks referenced table for existence — index lookup on PK
- On DELETE of referenced row: checks child table — requires index on FK column
- **Without** `ON DELETE CASCADE/SET NULL`: no additional write cost on child
- **Critical**: always index FK columns to avoid sequential scan on every child INSERT

## EXCLUDE Constraints

- Backed by GiST index — more expensive to maintain than B-tree
- Only for critical temporal overlap detection (e.g., fiscal period non-overlap)
- Cost: GiST insert is ~2-5x B-tree insert
- Requires `btree_gist` extension for mixed btree/GiST types

## GENERATED Columns

- `STORED`: stored physically, computed on write — full column storage cost
- `VIRTUAL` (PG 12+): not stored, computed on read — no storage cost
- Best use: precomputed expressions that are frequently filtered (`variance_amount = actual - budget`)
- Trade-off: STORED adds ~8 bytes per row (NUMERIC) vs recompute on every read

## Row-Level Security

- RLS policies add a qualifier to every query on the table
- Planner cost: ~1-5% overhead for simple equality policies (`entity_id = current_setting('app.tenant_id')`)
- Chained policies (joining via agent_runs): adds one extra JOIN qualifier
- **Mitigation**: ensure policy columns are indexed
- **No overhead** for table owners and `BYPASSRLS` roles

## Write Amplification Summary

| Table | Constraints | Write Amp Factor (est.) |
|-------|-------------|------------------------|
| actuals | PK, FK(entity), FK(account), CHECK(amount>0) | ~1.3x (index writes) |
| trial_balance | PK, FKs, CHECK, UNIQUE(composite) | ~1.5x |
| audit_logs | PK, RLS, FK(tenant), CHECK(event_types) | ~1.1x |
| root_cause_findings_db | PK, UNIQUE, CHECK | ~1.2x |
