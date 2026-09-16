## ADDED Requirements

### Requirement: Evidence Model

The system SHALL support `source`, `source identifier`, `tenant`, `content hash`, `retrieval time`, `provenance` (adapter, endpoint, correlation_id), and `immutability` per evidence, with stored artifacts as `raw artifact → content hash → immutable reference → canonical extraction → claim/evidence relationship` via `finance/object_store/port.py:ObjectMeta` and `finance/evidence/models.py:EvidenceItem`, and `exception.tenant_id` indexed. `S3` SHALL remain transport, not authoritative.

#### Scenario: Evidence lineage is hash-verifiable

- **WHEN** a Gmail retrieval is stored as `tenant-a/case-1027/gmail.json` (bytes B) via `S3Adapter.put_object`
- **THEN** `ObjectMeta.content_hash == sha256(B)`, `content_length == len(B)`, `retrieval time` is recorded, and a second `put` with same key+bytes returns same hash (idempotent)

### Requirement: Grounding Contract

The system SHALL enforce `FACTUAL CLAIM → must cite evidence → evidence exists → belongs to tenant → provenance valid → claim supported → eligible for verification`, with `HYPOTHESIS != FACT`, `FACT != VERIFIED`, `LLM confidence != authority` (confidence `0.99` never establishes financial truth). `MoneyDecimal` amounts remain deterministic (`finance/reconciliation/models.py`).

#### Scenario: High confidence without citation is not verification

- **WHEN** an `InvestigationPlan` claims `refund = ₹10,000` with `confidence=0.99` but cites no `evidence_required` that maps to a tenant-owned, provenance-valid `EvidenceItem`
- **THEN** `Verifier` (claim classification + grounding) rejects the claim and no `ResolutionProposal` is built

### Requirement: Claim Verification

The system SHALL verify every factual claim against `evidence_exists`, `belongs to tenant`, `provenance valid` (adapter+hash+time), and `supported` (claim text matches extracted canonical value within tolerance), with `evidence_required` non-blank, bounded, unique, and tenant-scoped; unverified claims remain `HYPOTHESIS`.

#### Scenario: Claim with valid provenance passes, otherwise fails

- **WHEN** a claim cites `evidence_required=["tenant-a/case-1027/qb.json"]` whose `EvidenceItem.source_value=Decimal("35000.00")` matches the claim `35000.00` within `tolerances.py`
- **THEN** the claim is `supported` and eligible for `VERIFIED`; citing `tenant-b` evidence fails as `not belongs to tenant`
