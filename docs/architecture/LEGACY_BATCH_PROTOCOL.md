# LEGACY BATCH PROTOCOL — P5-10 COBOL Settlement Ledger

**Status:** Implemented
**Author:** Meridian Commerce Integration Team
**Date:** 2026-09-16

## 1. Overview

This document specifies the fixed-width batch protocol for outbound settlement data
transferred from FinSight to the Meridian Commerce COBOL settlement ledger via S3.
There is **no HTTP interface** — all communication is file-based through two S3 buckets:

- **`finsight-legacy-outbound`** — FinSight writes outbound `.DAT` files here.
- **`finsight-legacy-result`** — Legacy system writes result `.DAT` files here.

## 2. Flow

```
┌──────────────┐    OUTBOUND (.DAT)    ┌──────────────────────┐    RESULT (.DAT)    ┌──────────────┐
│  FinSight    │ ──────────────────────>│  COBOL Settlement    │ ──────────────────> │  FinSight    │
│  (Producer)  │   S3: outbound bucket  │  Ledger (Consumer)   │   S3: result bucket │  (Consumer)  │
└──────────────┘                        └──────────────────────┘                     └──────────────┘
```

1. FinSight constructs a `LegacyBatch` and serialises to fixed-width `.DAT`.
2. File is uploaded to `finsight-legacy-outbound/{company_id}/{batch_id}/CORRECTION_YYYYMMDD_231.DAT`.
3. Legacy COBOL system polls, parses, processes records.
4. Legacy system writes a result `.DAT` to `finsight-legacy-result/{company_id}/{batch_id}/...`.
5. FinSight polls for result, parses, and updates batch status.

## 3. File Identity

| Field | Format | Example |
|-------|--------|---------|
| File name | `CORRECTION_YYYYMMDD_231.DAT` | `CORRECTION_20260916_231.DAT` |
| YYYYMMDD | Processing date (UTC) | `20260916` |
| 231 | Fixed record-type code for settlement corrections | `231` |

## 4. Batch Identity

| Field | Format | Example |
|-------|--------|---------|
| Batch ID | `LEGACY-YYYYMMDD-NNNN` | `LEGACY-20260916-0042` |
| YYYYMMDD | Batch creation date (UTC) | `20260916` |
| NNNN | Zero-padded monotonically increasing sequence (0001–9999) | `0042` |

## 5. Fixed-Width Schema (80 Characters)

Every line in a `.DAT` file is exactly **80 characters**. Fields are zero/space-padded
to their fixed width.

| Column Range | Width | Field | Type | Description |
|-------------|-------|-------|------|-------------|
| 1–2 | 2 | `version` | `NUM(2)` | Protocol version. Current: `01` |
| 3–16 | 14 | `batch_id` | `CHAR(14)` | Batch identifier: `LEGACY-YYYYMMDD-NNNN` |
| 17–24 | 8 | `sequence` | `NUM(8)` | Zero-padded sequence within batch (00000001–99999999) |
| 25–76 | 52 | `record` | `CHAR(52)` | Record payload (see §5.1) |
| 77–80 | 4 | `checksum` | `CHAR(4)` | Last 4 hex chars of SHA-256 of (version + batch_id + sequence + record) |

### 5.1 Record Payload Layout (Columns 25–76, 52 chars)

The record payload is domain-specific to the settlement correction. It carries the
financial data fields that the COBOL ledger expects. The first 2 characters of the
record payload encode the **record type**:

| Record Type | Meaning |
|-------------|---------|
| `01` | Settlement correction (amount adjustment) |
| `02` | Settlement reversal |
| `03` | Settlement reconciliation match |
| `99` | Control record (batch totals) |

The remaining 50 characters carry the type-specific payload fields.

## 6. Control Total

The **control total** is the sum of all monetary amounts in the batch, expressed as a
`Decimal` with exactly 2 decimal places. It is stored in the **control record** (record
type `99`) as the last 52 characters of the record payload.

**Computation:**
```python
from decimal import Decimal
control_total = sum(record.amount for record in records if record.type != "99")
```

If the control total in the received result does not match, the batch is **rejected**
(fail-closed). No partial acceptance is permitted for control-total mismatches.

## 7. SHA-256 Checksum

Each 80-character line carries a 4-character checksum at columns 77–80:

```
checksum = SHA-256(version + batch_id + sequence + record)[-4:]
```

The checksum covers the 76-character body (cols 1–76). The last 4 hex characters of the
SHA-256 digest are appended. This provides:
- Tamper detection per line.
- Fast verification without external signing infrastructure.

## 8. Accepted vs. Rejected Records

| Status | Meaning |
|--------|---------|
| **Accepted** | Record processed by legacy system without error. Amount applied to ledger. |
| **Rejected** | Record failed legacy validation (duplicate, invalid amount, account mismatch). |

The result file contains one **result line per input line** with the same sequence number
and a result code at columns 25–26:

| Code | Meaning |
|------|---------|
| `AC` | Accepted |
| `RJ` | Rejected |
| `DU` | Duplicate (already processed) |

## 9. Partial Processing

Partial processing occurs when some records in a batch are accepted and others rejected.
This is **allowed** — the result file reflects per-record status. FinSight must:

1. Parse each result line.
2. Update individual record status.
3. Log rejected records with rejection reason.
4. **Not** retry rejected records automatically — human review required.

## 10. Duplicate Detection

| Level | Mechanism |
|-------|-----------|
| **Batch** | Duplicate batch_id is rejected outright. Legacy returns `DU` for the entire batch. |
| **Record** | Same (batch_id, sequence) pair already processed → record returns `DU`. |

FinSight must generate monotonically increasing sequence numbers within each batch.
Re-use of sequence numbers across batches is allowed (batch_id provides namespace).

## 11. Result Semantics

The result file mirrors the outbound file structure:

| Column Range | Field | Description |
|-------------|-------|-------------|
| 1–2 | `version` | Protocol version (must match input) |
| 3–16 | `batch_id` | Batch identifier (must match input) |
| 17–24 | `sequence` | Sequence number (must match input) |
| 25–26 | `result_code` | `AC`, `RJ`, or `DU` |
| 27–76 | `detail` | Rejection reason or empty (50 chars) |
| 77–80 | `checksum` | SHA-256 checksum of result line body |

## 12. Retry Semantics

| Scenario | Behaviour |
|----------|-----------|
| **S3 upload failure** | Retry up to 3 times with exponential backoff (1s, 2s, 4s). Then raise `LegacyUploadError`. |
| **Result not found** | Poll for up to 30 minutes (every 60s). Then raise `LegacyResultTimeoutError`. |
| **Result parse failure** | Log raw bytes, raise `LegacyParseError`. No retry — data corruption assumed. |
| **Rejected records** | No automatic retry. Queue for human review. |

## 13. Timeout Semantics

| Timeout | Duration | Action |
|---------|----------|--------|
| **S3 read** | 10 seconds per object | Raise `LegacyTimeoutError` |
| **Result poll** | 30 minutes total | Raise `LegacyResultTimeoutError` |
| **Batch processing** | 5 minutes per 1000 records | Raise `LegacyTimeoutError` |

## 14. S3 Key Convention

```
{company_id}/{batch_id}/CORRECTION_YYYYMMDD_231.DAT
```

Example:
```
meridian-commerce/LEGACY-20260916-0042/CORRECTION_20260916_231.DAT
```

**Tenant isolation is enforced at the key prefix level.** Cross-tenant access raises
`TenantIsolationError` (alias `CompanyIsolationError`).

## 15. Error Types

| Error | Condition |
|-------|-----------|
| `TenantIsolationError` | Company A attempts to read/write Company B's key prefix |
| `LegacyParseError` | Fixed-width line is not 80 chars or fields fail validation |
| `LegacyChecksumError` | SHA-256 checksum mismatch on any line |
| `LegacyControlTotalError` | Control total in result does not match computed total |
| `LegacyUploadError` | S3 upload failed after retries |
| `LegacyResultTimeoutError` | Result file not found within timeout window |
| `LegacyTimeoutError` | S3 read or processing exceeded time limit |
