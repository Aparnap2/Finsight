# Operator run — three-source reconciliation triangle

A reproducible, synthetic demonstration that the composed workflow in
`finance/reconciliation/statement_workflow.py` can be run from one command and
inspected by an operator without reading internal data structures.

This is an evidence artifact, not a product surface. It uses the frozen
`triangle` fixture only (`tenant-triangle`, `USD`) and makes no claim about
customer data, accuracy on real statements, latency, or production readiness.

## Reproduce

From the repository root:

```bash
python -m finance.reconciliation.operator_report \
  --cases tests/fixtures/reconciliation/triangle/cases.json \
  --expected tests/fixtures/reconciliation/triangle/operator_expected.json \
  --pairwise-expected tests/fixtures/reconciliation/triangle/expected.json \
  --markdown docs/evidence/operator-run/report.md \
  --json docs/evidence/operator-run/report.json \
  --evidence docs/evidence/operator-run/run.json \
  --source-commit "$(git rev-parse HEAD)"
```

Exit `0` means every expectation and every invariant passed. Exit `1` means the
run must not be read as settled; the failing checks are printed to stderr and
recorded in the artifacts.

## Negative control

Copy `operator_expected.json`, change any expected value (for example
`s6_duplicate.allocated_total` to `149.00`), and run the same command with
`--expected <copy>`. The command exits `1`, the Markdown verdict reads `FAIL`,
and `report.json` names the failing check:

```text
FAIL s6_duplicate expected/allocated_total: expected '149.00', observed '148.00'
```

`tests/unit/reconciliation/test_operator_report.py` asserts this behaviour, so a
report that always says `PASS` cannot pass CI.

## What the run reports

| Scenario | Status | Outcome | Why it is not "settled" |
|---|---|---|---|
| `s1_exact_match` | Reconciled | `MATCHED` | — |
| `s2_fee_explained` | Reconciled | `MATCHED` | 29.00 processor fee explained |
| `s3_many_to_one` | Reconciled | `MATCHED` | three charges, one deposit, each leg once |
| `s4a_refund_folded` | Reconciled | `MATCHED` | refund folded into the net |
| `s5_delayed` | Reconciled | `MATCHED` | deposit arrives inside the window |
| `s4b_partial_payment` | Pending evidence | `PENDING_EVIDENCE` (`NO_CANDIDATE`) | 600.00 deposit has no processor leg |
| `s5b_missing_deposit` | Pending evidence | — (`NO_DEPOSIT`) | no bank line exists; nothing is synthesized |
| `s6_duplicate` | Exception | `EXCEPTION` (`I-DUPLICATE`) | 148.00 allocated once; 2.00 stays open |
| `s7_ambiguous_allocation` | Ambiguous | `REQUIRES_HUMAN` (`AMBIGUOUS`) | two valid allocations; a human must choose |

Statuses are fixed by `operator_expected.json`; they are not inferred from the
output being checked. The run also re-verifies, independently of that table:

- per-deposit conservation (`allocated + open == eligible net`,
  `allocated + unallocated == deposit amount`), leg totals and caps;
- one deposit result per statement deposit id, and no charge allocated twice;
- tenant and currency scope for every leg, link, and deposit;
- statement-line accounting: every bank row is in deposit evidence, a duplicate
  group, a reject, or a counted skipped debit;
- input files are unchanged by the run, and reprocessing yields the same
  workflow fingerprint and report;
- every monetary value in the rendered document has the declared scale.

## Artifacts

| File | Contents |
|---|---|
| `report.md` | operator view: summary table, per-scenario evidence, limitations, warnings, verdict |
| `report.json` | machine view: document + every check, byte-stable for a given commit and fixture |
| `run.json` | provenance: source commit, module sha256, fixture digests, argv, exit code, verdict, status counts |

`report.md`, `report.json`, and `run.json` were generated from commit
`1bc8bec927ced2e5f2b240263f771116d746b458`. That commit records the exact
invocation shown above in `report.json`; it sits on `7bb7527`, which introduced
`operator_report.py`, its tests, and `operator_expected.json`. The commit that
updates this directory changes documentation and generated artifacts only, so
the recorded `source_commit` remains the code under test.

Fixture digests are recorded in `run.json`. Changing `cases.json`,
`expected.json`, or `operator_expected.json` invalidates the recorded digests and
requires regenerating the artifacts.

## Scope decisions and known gaps

- The expectation table is additive (`operator_expected.json`). The frozen
  pairwise fixture (`expected.json`) and its gap markers are untouched.
- `s2_fee_invoice_vs_naive_bank` stays unsupported pairwise: a bank row has no
  fee column, so the composed run explains the 29.00 as a processor fee instead
  of pretending a direct bank comparison is exact.
- `s4b_partial_payment` stays unsupported pairwise: with no processor leg the
  composed run reports pending evidence and leaves the deposit unallocated.
- `s6_duplicate_bank_row` is `MATCHED` on the pairwise surface only because equal
  nets match before the duplicate flag fires. The composed run deduplicates
  first, reports both duplicate groups, allocates once, and keeps 2.00 open.
- `s5b_missing_deposit` has no deposit result at all; absence is reported, not
  filled in.
- No new OpenSpec change is opened by this work: the reconciliation contract and
  its frozen surfaces are unchanged. The composition and its retained gaps are
  already documented in `docs/reconciliation/triangle-contract-gap.md`.

## Local gates at the code commit

| Gate | Result |
|---|---|
| `ruff check .` | pass |
| `ruff format --check .` | 750 files formatted |
| `mypy .` + baseline check | recorded 1137, current 1137, new 0 |
| `pytest tests/unit/reconciliation` | 220 passed |
| `pytest tests/unit tests/contract` | 3608 passed, 1 skipped |
| operator run | exit 0, 266 checks passed, 0 failed |

The Postgres-gated integration tier and the golden-dataset eval gate are part of
`PR verification` in CI; they were not re-run locally for this documentation
commit. See PR #129 for the CI result attached to the code commit.

## What this does not prove

- It does not prove correctness on real bank or processor exports.
- It does not prove that the ambiguous case can be resolved automatically.
- It does not replace the independent review that GitHub still requires; the
  workspace has a single author-collaborator, so no non-author approval exists.
