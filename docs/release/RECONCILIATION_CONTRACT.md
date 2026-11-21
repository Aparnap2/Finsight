# Reconciliation behavioural contract

Purpose: make the reconciliation engine's financial behaviour **executable** and
**enforced**, so repository cleanup, the new API, the operator UI, and any AI
explanation layer cannot silently change what the engine decides.

The contract has four parts:

| Part | Enforced by |
|---|---|
| Scenario catalogue | `tests/unit/reconciliation/test_financial_contract.py`, `tests/fixtures/reconciliation/triangle/` |
| Financial invariants | the same module, plus the `__post_init__` guards in `finance/reconciliation/` |
| Frozen evidence | `tests/unit/reconciliation/test_golden_evidence.py` (byte-identical bundle) |
| Runtime boundary | `scripts/reconciliation_boundary.py --check` |

Run it locally:

```bash
make test-contract
```

That runs the reconciliation suite, verifies the boundary manifest, and writes
the machine-readable record to `/tmp/finsight-contract.json`. CI runs the same
assertions inside the fast gate and additionally uploads the record as the
`reconciliation-contract` artifact.

The record contains, for one commit and one interpreter: scenario id, expected
versus actual status / outcome / exception code / amounts, invariant totals,
fixture digests, commit SHA, and environment. It exits non-zero on any
divergence, so it is a gate and not only a report.

Two commit fields are recorded because they can differ: `commit` is the head
commit the evidence belongs to, and `checked_out_commit` is the tree that
actually ran. A `pull_request` CI run checks out a synthetic merge commit, whose
SHA is discarded after the run, so the workflow declares the head SHA through
`FINSIGHT_CONTRACT_COMMIT` and the artifact stays resolvable. Locally the two
fields are identical.

---

## 1. Scenario catalogue

The catalogue below is the product's acceptance list. Status is honest: a row is
**covered** only where a test asserts the financial outcome, not merely that a
call returned.

| ID | Scenario | Coverage | Status |
|---|---|---|---|
| S01 | Exact invoice, charge, deposit | `s1_exact_match` (fixture) | covered |
| S02 | Processor fee explained | `s2_fee_explained` (fixture) | covered |
| S03 | Many charges in one payout | `s3_many_to_one` (fixture) | covered |
| S04 | Full refund | `test_a_fully_refunded_charge_is_excluded_not_settled` | **gap** — see below |
| S05 | Partial refund | `s4a_refund_folded` (fixture) | covered |
| S06 | Deposit delayed | `s5_delayed` (fixture), `test_a_deposit_outside_the_window_is_pending_not_matched` | covered |
| S07 | Missing bank deposit | `s5b_missing_deposit` (fixture) | covered, with a semantics note |
| S08 | Duplicate processor record | `s6_duplicate` (fixture) | covered |
| S09 | Ambiguous allocation | `s7_ambiguous_allocation` (fixture) | covered |
| S10 | Partial customer payment | `s4b_partial_payment` (fixture) | covered |
| S11 | Payout contains unrelated money | `test_unexplained_over_deposit`, `test_deposit_with_no_processor_legs_is_pending_evidence` | covered at unit level, not in the fixture |
| S12 | Chargeback / dispute | — | **gap** — no dispute status exists |
| S13 | Out-of-order source records | `test_invoice_and_charge_order_does_not_change_the_result`, `test_bank_order_changes_only_the_authoritative_drift_row` | covered |
| S14 | Duplicate file upload | `test_reingest_is_deterministic_and_deduplicated`, `test_ensure_unique_deposits_raises_on_repeats` | covered at ingest level; API idempotency deferred |
| S15 | Negative or malformed amounts | `test_money_guards.py`, `test_bank_normalization.py`, `test_a_negative_net_charge_is_never_allocated` | covered, except an amount-range ceiling |

### S04 — full refund is excluded, not settled

A charge refunded in full has `net == gross - fee - refund == 0`. The engine
filters `net <= 0` out of the eligible set, so a deposit that matches only
refunded charges returns `PENDING_EVIDENCE` / `NO_CANDIDATE`.

That is **safe** — nothing is falsely settled — but it is not *correct*: a fully
refunded charge is settled by refund, not missing evidence. Fixing it changes
financial behaviour, so it needs an explicit product decision. The test records
today's behaviour and names the gap; it is not a silent xfail.

### S07 — missing deposit is pending, not an exception

The catalogue expectation was "Exception". The engine reports
`PENDING_EVIDENCE` / `NO_DEPOSIT`, because absence of evidence is not evidence
of a mismatch. That distinction is deliberate and is asserted in
`test_the_catalogue_status_matches_the_run`. If the product wants a hard
exception here, that is a spec change, not a bug fix.

### S12 / S15 — two real gaps

- **S12:** `PaymentStatus` has no `DISPUTED` value and no exception code covers a
  chargeback. A dispute is currently indistinguishable from a refund. Adding it
  is new domain behaviour.
- **S15 (range):** money must be a finite `Decimal`, but there is no upper bound
  or per-transaction ceiling. "Huge amount exceeds supported range" cannot pass
  until a ceiling is defined.

Both are recorded as gaps rather than papered over with a passing assertion.

---

## 2. Financial invariant matrix

| # | Invariant | Enforced by | Asserted by |
|---|---|---|---|
| A | **Allocation conservation**: `allocated + open == eligible net`, `allocated + unallocated == deposit` | `Allocation.__post_init__` | `test_every_deposit_conserves_its_money`, `test_generated_sweep_conserves_money_for_every_outcome` |
| B | **No double allocation**: a charge appears in at most one leg per run | `Allocation.__post_init__` (unique, sorted legs) | `test_no_charge_is_allocated_twice`; report check `no_leg_reused` |
| C | **Decimal-only money**: no float on the path or in the output | `_require_decimal` in `models.py` and `bank.py` | `test_money_guards.py`, `test_the_report_contains_no_float_money` |
| D | **No false settlement**: a settled deposit has no residual and fully credited legs | outcome/code coupling in `Allocation.__post_init__` | `test_a_settled_deposit_is_arithmetically_closed`, `test_missing_or_ambiguous_evidence_is_never_settled`, `test_unresolved_scenarios_are_never_labelled_reconciled` |
| E | **Determinism**: same inputs, same result and fingerprint | no clock, randomness, network, or model on the path | `test_replay_of_a_scenario_is_identical`, `test_generated_sweep_is_deterministic`, `test_committed_evidence_is_byte_reproducible` |
| F | **Provenance**: every leg and evidence line resolves to an input record | `fingerprint_payment`, `DepositEvidence` | `test_every_allocated_leg_resolves_to_an_input_charge`, `test_evidence_record_binds_commit_inputs_and_outcome` |
| G | **Currency and tenant isolation** | `_validate_inputs` raises `CurrencyMismatch` / `TenantIsolationError` | `test_cross_currency_*`, `test_tenant_mismatch_raises`, `test_tenant_isolation_is_enforced` |
| H | **Refund conservation**: refunds are separate and never increase settled value | `net == gross - fee - refund` on every leg | `test_refunds_never_increase_settled_value`, `test_the_refund_scenario_reports_the_refund_separately` |

Two invariants are worth stating precisely, because the obvious version is
wrong:

- **`open_balance` is scope-wide.** It is `eligible_net_total - allocated_total`,
  where the eligible scope is every charge in the window, not only the charges
  this deposit settled. A `MATCHED` deposit can therefore have a positive open
  balance when other charges await other deposits. Settlement is defined by a
  zero *residual* and fully credited legs, not by an empty scope.
- **`refund_total` covers allocated legs only.** A charge excluded from the
  eligible set (fully refunded, negative net) contributes no leg, so its refund
  is not in `refund_total`. The invariant is `allocated + refund <= gross` per
  leg, not a global refund ledger.

---

## 3. What was added

`tests/unit/reconciliation/test_financial_contract.py` — 111 tests. It reads the
engine's public outputs and asserts the invariants directly, instead of trusting
`operator_report._invariants`, which is computed by the module under test. New
coverage:

| Test | Closes |
|---|---|
| `test_every_deposit_conserves_its_money` | A on every fixture scenario |
| `test_no_charge_is_allocated_twice` | B on every fixture scenario |
| `test_a_settled_deposit_is_arithmetically_closed` | D, general form |
| `test_the_catalogue_status_matches_the_run` | the S01–S10 catalogue as executable assertions |
| `test_missing_or_ambiguous_evidence_is_never_settled` | D for every open outcome |
| `test_replay_of_a_scenario_is_identical` | E on every scenario |
| `test_invoice_and_charge_order_does_not_change_the_result` | S13 |
| `test_bank_order_changes_only_the_authoritative_drift_row` | S13 for statements |
| `test_every_allocated_leg_resolves_to_an_input_charge` | F |
| `test_refunds_never_increase_settled_value` | H |
| `test_the_report_contains_no_float_money` | C at the output boundary |
| `test_a_fully_refunded_charge_is_excluded_not_settled` | S04 (records the gap) |
| `test_a_negative_net_charge_is_never_allocated` | S15 |
| `test_an_unknown_deposit_amount_never_invents_a_match` | over-deposit residual |
| `test_generated_sweep_*` (3 tests) | A, B, D, E over 40 deterministic generated allocations |
| `test_a_deposit_outside_the_window_*` (2 tests) | S06 window gate |
| `test_the_contract_report_script_verifies_the_fixture` | the report script itself |
| `test_the_contract_report_records_the_declared_head_commit` | CI evidence resolves to a real commit |

The sweep is property-based without a new dependency: a seeded
`random.Random(20260101)` generates charge sets and deposits, so it is
deterministic and reproducible in CI.

No production module, fixture, or existing test was modified.

---

## 4. Deferred: failure cases that need the API and database

These are real requirements from the failure matrix. They cannot be written
against code that does not exist yet, and fabricating a test against a missing
endpoint would be worse than none.

| Failure | Expected behaviour | Blocked on | Planned test |
|---|---|---|---|
| CSV missing required columns | import rejected with per-column errors | no CSV reader (bank normalization accepts parsed rows) | `tests/integration/test_import_api.py::test_missing_columns_are_rejected` |
| Same file uploaded twice | no duplicate records | no upload endpoint | `test_duplicate_upload_is_idempotent` |
| Database unavailable during a run | no falsely completed run | no run persistence | `test_db_unavailable_does_not_mark_run_complete` |
| Killed after calculation, before completion | no duplicate allocation, no false success | no run state machine | `test_restart_after_calculation_is_safe` |
| Retry after timeout | no duplicate financial outcome | no idempotency key at the API | `test_retry_reuses_the_run` |
| Two concurrent runs | no conflicting allocation | no locking | `test_concurrent_runs_do_not_conflict` |
| LLM timeout | reconciliation results remain available | no investigation endpoint | `test_llm_timeout_leaves_results_intact` |
| LLM fabricates a record id | output rejected | no investigation endpoint | `test_unknown_evidence_reference_is_rejected` |
| Cross-tenant run access | access denied | no reconciliation tables / RLS | `test_foreign_tenant_run_is_denied` |
| Restart | historical results available | no persistence | `test_results_survive_restart` |

The engine-level half of several of these is already covered: duplicate ingest is
deterministic and deduplicated, and the allocation itself is a pure function, so
retrying it cannot change a result. What is missing is the durability boundary.

---

## 5. Execution record

Measured on `feat/reconciliation-three-source-workflow` at `fc0e19d` plus this
change set (2026-11-21), Python 3.12.3.

| Gate | Command | Result |
|---|---|---|
| Reconciliation suite | `pytest tests/unit/reconciliation -q` | **352 passed** (was 241; +111) |
| Contract module | `pytest tests/unit/reconciliation/test_financial_contract.py -q` | 111 passed |
| Fast suite | `pytest tests/unit tests/contract -q` | 3447 passed, 1 skipped |
| Operator demo | `python -m finance.reconciliation.operator_report` | exit 0, 266/266 checks, `Verdict: PASS` |
| Contract record | `python scripts/reconciliation_contract_report.py` | `verdict: pass`, 9 scenarios, 266/266 checks |
| Boundary | `python scripts/reconciliation_boundary.py --check` | exit 0 |
| Lint / format | `ruff check .`, `ruff format --check .` | pass |
| Types | `mypy .` + baseline check | 1137 recorded, 1137 current, **0 new** |

---

## 6. What this contract does not prove

- It does not prove the engine is correct for arbitrary real-world statements.
  It proves the frozen scenarios and the stated invariants hold.
- It does not prove the deployed application works end to end: there is no
  reconciliation API, persistence, or operator workflow yet.
- It does not cover AI behaviour. Explanation quality is a separate gate that
  runs only after the investigation endpoint exists, and it must never be able
  to alter a financial result.
- It does not replace the compose integration tier; that still covers
  PostgreSQL, migrations, and row-level security for the existing application.
