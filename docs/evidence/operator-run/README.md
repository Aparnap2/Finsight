# Operator run — three-source reconciliation triangle

A reproducible, synthetic demonstration that the composed workflow in
`finance/reconciliation/statement_workflow.py` runs from one command and prints
a report a finance operator can act on without reading the source.

This is an evidence artifact, not a product surface. It uses the frozen
`triangle` fixture only (`tenant-triangle`, `USD`) and makes no claim about
customer data, accuracy on real statements, latency, or production readiness.

## One command

```bash
python -m finance.reconciliation.operator_report
```

That loads the checked-in fixture, runs the workflow, verifies the nine expected
results plus 266 accounting and safety invariants, and prints the Markdown
report to stdout. Fixture paths resolve from the module, not the shell's
working directory, so the command works from anywhere in the checkout.

Exit codes:

| Code | Meaning |
|---|---|
| `0` | every expectation, cross-check, and invariant passed |
| `1` | a check failed (the failing checks are printed to stderr) |
| `2` | input problem: missing, empty, directory, invalid JSON, or wrong shape |

Explicit overrides are unchanged; supplying one does not reset the others:

```bash
python -m finance.reconciliation.operator_report \
  --cases /tmp/custom-cases.json \
  --expected /tmp/custom-expected.json
```

An explicitly supplied path that does not exist fails with exit `2` and the
path named; it never falls back to the fixture.

## Writing the artifacts

The committed bundle was produced with explicit output paths:

```bash
python -m finance.reconciliation.operator_report \
  --markdown docs/evidence/operator-run/report.md \
  --json docs/evidence/operator-run/report.json \
  --evidence docs/evidence/operator-run/run.json \
  --source-commit "$(git rev-parse HEAD)"
```

The default invocation prints the same report body; only the recorded
`Command:` line differs, because it reflects the flags actually used. That was
verified by diffing the two outputs.

## Negative control

Copy `operator_expected.json`, change any expected value (for example
`s6_duplicate.allocated_total` to `149.00`), and rerun with `--expected <copy>`.
The command exits `1`, the Markdown verdict reads `FAIL`, and stderr names the
failing check:

```text
FAIL s6_duplicate expected/allocated_total: expected '149.00', observed '148.00'
```

`tests/unit/reconciliation/test_operator_report.py` pins this behaviour, so a
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

The summary table adds a `Reason` column for any non-zero difference, derived
only from recorded fees and refunds:

- `Fee` — the difference equals the processor fee (`s2`, `s3`).
- `Refund + fee` — the difference equals refund plus fee (`s4a`).
- `Unexplained` — the difference is not attributable to fee or refund (`s6`).
- `—` — no derived difference, or the difference is zero.

`Open balance` is charge value that no deposit has matched yet. It is not a
liability or a payout; `s7` shows 1940.00 of charge value against a 970.00
deposit, and the scenario limitation says so explicitly.

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
| `run.json` | provenance: source commit, module sha256, fixture digests, argv, exit code, verdict, status counts, documented one-command form |

`report.md`, `report.json`, and `run.json` were generated from commit
`86550e18ea779e26d48a5e161f19670eb212b930`. The commit that updates this
directory changes documentation and generated artifacts only, so the recorded
`source_commit` remains the code under test.

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
  its frozen surfaces are unchanged.

## Local gates at the code commit

| Gate | Result |
|---|---|
| `ruff check .` | pass |
| `ruff format --check .` | 750 files formatted |
| `mypy .` + baseline check | recorded 1137, current 1137, new 0 |
| `pytest tests/unit/reconciliation` | 237 passed |
| `pytest tests/unit tests/contract` | 3625 passed, 1 skipped |
| operator run | exit 0, 266 checks passed, 0 failed |

The Postgres-gated integration tier and the golden-dataset eval gate run in CI;
see PR #129 for the result attached to this branch.

## What this does not prove

- It does not prove correctness on real bank or processor exports.
- It does not prove that the ambiguous case can be resolved automatically.
- It does not replace operator validation. Synthetic fixtures show technical
  behaviour, not that a finance team would adopt or pay for the workflow.
