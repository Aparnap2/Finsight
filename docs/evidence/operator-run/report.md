# Operator reconciliation report — three-source triangle

Synthetic fixture only. No customer or production financial data is involved.

- Fixture: `triangle` (version 1)
- Cases sha256: `f642f26cc409bf8fd938e510581995ed705b7f0117fe7cd354f3d9f50bd78988`
- Expected sha256: `d54beb4770f67dd719c1e590ee661a333a61ed941c0ecfbd4357c4cb71e257a3`
- Operator expectation sha256: `5b64b1dbc240118df824ae9f1112f8fa17e0deaaac702788e5b4cff2e76d915b`
- Command: `python -m finance.reconciliation.operator_report --markdown docs/evidence/operator-run/report.md --json docs/evidence/operator-run/report.json --evidence docs/evidence/operator-run/run.json --source-commit 86550e18ea779e26d48a5e161f19670eb212b930`
- Verdict: **PASS**

## Summary

| Scenario | Status | Outcome | Classification | Allocated | Open | Unallocated | Difference | Reason |
|---|---|---|---|---|---|---|---|---|
| `s1_exact_match` | Reconciled | MATCHED | — | 250.00 | 0.00 | 0.00 | 0.00 | — |
| `s2_fee_explained` | Reconciled | MATCHED | — | 971.00 | 0.00 | 0.00 | -29.00 | Fee |
| `s3_many_to_one` | Reconciled | MATCHED | — | 970.00 | 0.00 | 0.00 | -30.00 | Fee |
| `s4a_refund_folded` | Reconciled | MATCHED | — | 571.00 | 0.00 | 0.00 | -429.00 | Refund + fee |
| `s4b_partial_payment` | Pending evidence | PENDING_EVIDENCE | NO_CANDIDATE | 0.00 | 0.00 | 600.00 | — | — |
| `s5_delayed` | Reconciled | MATCHED | — | 500.00 | 0.00 | 0.00 | 0.00 | — |
| `s5b_missing_deposit` | Pending evidence | — | NO_DEPOSIT | 0.00 | 0.00 | 0.00 | — | — |
| `s6_duplicate` | Exception | EXCEPTION | I-DUPLICATE | 148.00 | 2.00 | 0.00 | -2.00 | Unexplained |
| `s7_ambiguous_allocation` | Ambiguous | REQUIRES_HUMAN | AMBIGUOUS | 0.00 | 1940.00 | 970.00 | — | — |

Status meanings:

- **reconciled** — Reconciled — invoice, processor, and bank evidence agree.
- **exception** — Exception — investigate before treating this deposit as settled.
- **pending_evidence** — Pending evidence — the run cannot decide yet; do not book as settled.
- **ambiguous** — Ambiguous — more than one valid allocation; a human must choose.
- **open balance** — charge value that no deposit has matched yet; it is not a liability or a payout.

## `s1_exact_match` — Reconciled

Invoice, charge, and deposit agree to the cent with no fee.

| Item | Value |
|---|---|
| Invoice expected (net) | 250.00 |
| Processor evidence (net) | 250.00 |
| Bank deposit recorded | 250.00 |
| Allocated | 250.00 |
| Unallocated deposit | 0.00 |
| Fees | 0.00 |
| Refunds | 0.00 |
| Open balance | 0.00 |
| Derived difference (deposit − invoice) | 0.00 |
| Outcome | MATCHED |
| Classification | none |

Evidence:

- Invoice `INV-1000` → charge `ch_1000`: difference 0.00 (MATCHED)
- Deposit `stmt-2026-01:4` line 2 (f642f26cc409bf8fd938e510581995ed705b7f0117fe7cd354f3d9f50bd78988:2): 250.00

## `s2_fee_explained` — Reconciled

Invoice 1000.00, Stripe charges 1000.00 with a 29.00 fee, bank credits 971.00.

| Item | Value |
|---|---|
| Invoice expected (net) | 1000.00 |
| Processor evidence (net) | 971.00 |
| Bank deposit recorded | 971.00 |
| Allocated | 971.00 |
| Unallocated deposit | 0.00 |
| Fees | 29.00 |
| Refunds | 0.00 |
| Open balance | 0.00 |
| Derived difference (deposit − invoice) | -29.00 |
| Outcome | MATCHED |
| Classification | none |

Evidence:

- Invoice `INV-1001` → charge `ch_1001`: difference -29.00 (EXCEPTION, I-FEE-DRIFT)
- Deposit `stmt-2026-01:9` line 2 (f642f26cc409bf8fd938e510581995ed705b7f0117fe7cd354f3d9f50bd78988:2): 971.00

## `s3_many_to_one` — Reconciled

Three charges (388.00 + 291.00 + 291.00) settle as one 970.00 bank deposit.

| Item | Value |
|---|---|
| Invoice expected (net) | 1000.00 |
| Processor evidence (net) | 970.00 |
| Bank deposit recorded | 970.00 |
| Allocated | 970.00 |
| Unallocated deposit | 0.00 |
| Fees | 30.00 |
| Refunds | 0.00 |
| Open balance | 0.00 |
| Derived difference (deposit − invoice) | -30.00 |
| Outcome | MATCHED |
| Classification | none |

Evidence:

- Invoice `INV-2001` → charge `ch_2001`: difference -12.00 (EXCEPTION, I-FEE-DRIFT)
- Invoice `INV-2002` → charge `ch_2002`: difference -9.00 (EXCEPTION, I-FEE-DRIFT)
- Invoice `INV-2003` → charge `ch_2003`: difference -9.00 (EXCEPTION, I-FEE-DRIFT)
- Deposit `stmt-2026-01:21` line 2 (f642f26cc409bf8fd938e510581995ed705b7f0117fe7cd354f3d9f50bd78988:2): 970.00

## `s4a_refund_folded` — Reconciled

1000.00 charge, 29.00 fee, 400.00 refund, 571.00 net deposit.

| Item | Value |
|---|---|
| Invoice expected (net) | 1000.00 |
| Processor evidence (net) | 571.00 |
| Bank deposit recorded | 571.00 |
| Allocated | 571.00 |
| Unallocated deposit | 0.00 |
| Fees | 29.00 |
| Refunds | 400.00 |
| Open balance | 0.00 |
| Derived difference (deposit − invoice) | -429.00 |
| Outcome | MATCHED |
| Classification | none |

Evidence:

- Invoice `INV-1004` → charge `ch_1004`: difference -429.00 (EXCEPTION, I-REFUND-LAG)
- Deposit `stmt-2026-01:33` line 2 (f642f26cc409bf8fd938e510581995ed705b7f0117fe7cd354f3d9f50bd78988:2): 571.00

## `s4b_partial_payment` — Pending evidence

Invoice 1000.00 but only 600.00 arrives, with no refund or fee.

| Item | Value |
|---|---|
| Invoice expected (net) | 1000.00 |
| Processor evidence (net) | 0.00 |
| Bank deposit recorded | 600.00 |
| Allocated | 0.00 |
| Unallocated deposit | 600.00 |
| Fees | 0.00 |
| Refunds | 0.00 |
| Open balance | 0.00 |
| Derived difference (deposit − invoice) | not derivable |
| Outcome | PENDING_EVIDENCE |
| Classification | NO_CANDIDATE |

Evidence:

- Deposit `stmt-2026-01:41` line 2 (f642f26cc409bf8fd938e510581995ed705b7f0117fe7cd354f3d9f50bd78988:2): 600.00

Limitations:

- stmt-2026-01:41: no candidate charge matched the deposit; the money is unallocated, not lost.

Warnings:

- no processor legs: the invoice_to_charge and charge_to_deposit edges have no evidence
- deposit 'stmt-2026-01:41' is pending evidence (NO_CANDIDATE)
- unlinked invoices: INV-1005

## `s5_delayed` — Reconciled

Deposit arrives three days after the charge; 500.00 in both.

| Item | Value |
|---|---|
| Invoice expected (net) | 500.00 |
| Processor evidence (net) | 500.00 |
| Bank deposit recorded | 500.00 |
| Allocated | 500.00 |
| Unallocated deposit | 0.00 |
| Fees | 0.00 |
| Refunds | 0.00 |
| Open balance | 0.00 |
| Derived difference (deposit − invoice) | 0.00 |
| Outcome | MATCHED |
| Classification | none |

Evidence:

- Invoice `INV-1006` → charge `ch_1006`: difference 0.00 (MATCHED)
- Deposit `stmt-2026-01:52` line 2 (f642f26cc409bf8fd938e510581995ed705b7f0117fe7cd354f3d9f50bd78988:2): 500.00

## `s5b_missing_deposit` — Pending evidence

Charge settles in Stripe but no bank line ever arrives for it.

| Item | Value |
|---|---|
| Invoice expected (net) | 300.00 |
| Processor evidence (net) | 300.00 |
| Bank deposit recorded | none |
| Allocated | 0.00 |
| Unallocated deposit | 0.00 |
| Fees | 0.00 |
| Refunds | 0.00 |
| Open balance | 0.00 |
| Derived difference (deposit − invoice) | not derivable |
| Outcome | no deposit result |
| Classification | NO_DEPOSIT |

Evidence:

- Invoice `INV-1007` → charge `ch_1007`: difference 0.00 (MATCHED)

Limitations:

- No bank statement rows are present, so the bank leg is absent; the scenario is pending evidence, not reconciled.

Warnings:

- no bank evidence: the charge_to_deposit edge has no deposits

## `s6_duplicate` — Exception

The same bank line is imported twice, plus a re-import that was edited to 148.00.

| Item | Value |
|---|---|
| Invoice expected (net) | 150.00 |
| Processor evidence (net) | 150.00 |
| Bank deposit recorded | 148.00 |
| Allocated | 148.00 |
| Unallocated deposit | 0.00 |
| Fees | 0.00 |
| Refunds | 0.00 |
| Open balance | 2.00 |
| Derived difference (deposit − invoice) | -2.00 |
| Outcome | EXCEPTION |
| Classification | I-DUPLICATE |

Evidence:

- Invoice `INV-1008` → charge `ch_1008`: difference 0.00 (MATCHED)
- Deposit `stmt-2026-01:60` line 2 (f642f26cc409bf8fd938e510581995ed705b7f0117fe7cd354f3d9f50bd78988:2): 150.00
- Deposit `stmt-2026-01:60` line 4 (f642f26cc409bf8fd938e510581995ed705b7f0117fe7cd354f3d9f50bd78988:4): 148.00
- Exact duplicate lines: line 2 (150.00), line 3 (150.00)
- Drifted duplicate lines: line 2 (150.00), line 4 (148.00)

Limitations:

- stmt-2026-01:60: I-DUPLICATE recorded for review; the deposit is not settled.
- A repeated statement line carried a different amount; the latest line was reconciled once with duplicate evidence and the difference stays visible.
- Exact duplicate statement lines were reported once and never allocated twice.

Warnings:

- exact duplicate statement rows: f642f26cc409bf8fd938e510581995ed705b7f0117fe7cd354f3d9f50bd78988:2@150.00, f642f26cc409bf8fd938e510581995ed705b7f0117fe7cd354f3d9f50bd78988:3@150.00
- statement rows share an id with differing amounts: f642f26cc409bf8fd938e510581995ed705b7f0117fe7cd354f3d9f50bd78988:2@150.00, f642f26cc409bf8fd938e510581995ed705b7f0117fe7cd354f3d9f50bd78988:4@148.00

## `s7_ambiguous_allocation` — Ambiguous

A 970.00 deposit could be three charges or one 970.00 charge; nothing in the data decides.

| Item | Value |
|---|---|
| Invoice expected (net) | 970.00 |
| Processor evidence (net) | 1940.00 |
| Bank deposit recorded | 970.00 |
| Allocated | 0.00 |
| Unallocated deposit | 970.00 |
| Fees | 0.00 |
| Refunds | 0.00 |
| Open balance | 1940.00 |
| Derived difference (deposit − invoice) | not derivable |
| Outcome | REQUIRES_HUMAN |
| Classification | AMBIGUOUS |

Evidence:

- Invoice `INV-3001` → charge `ch_3001`: difference 0.00 (MATCHED)
- Invoice `INV-3002` → charge `ch_3002`: difference 0.00 (MATCHED)
- Invoice `INV-3003` → charge `ch_3003`: difference 0.00 (MATCHED)
- Deposit `stmt-2026-01:70` line 2 (f642f26cc409bf8fd938e510581995ed705b7f0117fe7cd354f3d9f50bd78988:2): 970.00
- Candidate 1: `ch_3001`, `ch_3002`, `ch_3003`
- Candidate 2: `ch_3004`

Limitations:

- stmt-2026-01:70: 2 candidate allocations; 1940.00 of charge value is unmatched against a 970.00 deposit, which is not a liability or a payout; a human must choose one.

Warnings:

- unlinked charges: ch_3004

## Documented surface notes

- s2_fee_invoice_vs_naive_bank remains an unsupported pairwise expectation: a bank row carries no fee column, so the composed workflow reconciles the processor's net (971.00) to the deposit and reports the invoice-to-deposit difference of -29.00 as a fee explanation, not as a refund.
- s4b_partial_payment remains unsupported pairwise. The composed workflow reports PENDING_EVIDENCE / NO_CANDIDATE because the processor leg is empty; the 600.00 deposit is unallocated and is not treated as settled.
- s6_duplicate_bank_row is MATCHED pairwise only because equal nets win before the duplicate flag can fire. The composed workflow deduplicates before allocation, reports exactly one result, retains both the exact-duplicate group (lines 2 and 3) and the drifted group (line 4), allocates 148.00 once, and keeps the 2.00 difference open as I-DUPLICATE.
- s5b_missing_deposit has no deposit result; the workflow emits the absence as pending evidence with reason NO_DEPOSIT rather than inventing a bank amount.
- All amounts are synthetic fixture values in USD. No customer, production, or personally identifying financial data is used.

## Verification

- Checks run: 266
- Passed: 266
- Failed: 0

A failed check makes this run exit nonzero; no unresolved case is reported as settled.
