---
type: Module
title: finance.reconciliation.bank
description: Tenant-declared bank statement normalization into deposit records.
resource: /finance/reconciliation/bank.py
tags: [reconciliation, module]
generated: {by: 'process:knowledge-graph', at: '2026-01-01T00:00:00Z'}
verified: {by: 'process:knowledge-graph', at: '2026-01-01T00:00:00Z'}
status: stable
sources:
- {id: src, resource: /finance/reconciliation/bank.py, title: bank.py}
source_fingerprint: d3f1592828e79aeaf38b64d9d36fe047377b808e659c2c3ae519518be04cb705
---

# Bank

## Classes

- `AmountUnit`
- `BankDepositRecord`
- `BankIngestResult`
- `BankStatementMapping`
- `RejectReason`
- `RowReject`
- `SignConvention`
- `_RowError`

## Public functions

- `canonical_deposit()`
- `dedupe_deposits()`
- `digest()`
- `ensure_unique_deposits()`
- `exponent()`
- `find_duplicate_deposits()`
- `fingerprint_deposit()`
- `normalize_bank_statement()`
- `source_reference()`

## In-scope dependencies

- [finance.reconciliation.errors](/code/modules/finance-reconciliation-errors.md)
- [finance.reconciliation.normalizer](/code/modules/finance-reconciliation-normalizer.md)

## Provenance

Source fingerprint (SHA-256): `d3f1592828e79aeaf38b64d9d36fe047377b808e659c2c3ae519518be04cb705`

> Structural relationships above are derived from static AST analysis. Runtime behaviour (dependency injection, dynamic dispatch) is not captured; see `/coverage.md`.

