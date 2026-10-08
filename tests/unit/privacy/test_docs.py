"""P10-08 RED: compliance documentation contract (failing: docs missing).

Asserts the documentation set exists, carries the required sections,
uses honest status language, keeps numeric policy in sync with code,
and cites only real evidence paths. Pure unit tests, no I/O beyond
reading the repo's own docs.
"""

from __future__ import annotations

import re
from pathlib import Path

DOCS = Path(__file__).resolve().parents[3] / "docs" / "privacy"

REQUIRED_DOCS = (
    "DATA_CLASSIFICATION.md",
    "PRIVACY_BOUNDARY.md",
    "RETENTION_POLICY.md",
    "SECURITY_MODEL.md",
    "INCIDENT_RESPONSE.md",
)

FORBIDDEN_CLAIMS = (
    "dpdp compliant",
    "gdpr compliant",
    "pci compliant",
    "certified compliant",
    "fully compliant",
    "is compliant",
)


class TestPresence:
    def test_required_docs_exist(self) -> None:
        for name in REQUIRED_DOCS:
            assert (DOCS / name).is_file(), name


class TestHonestLanguage:
    def test_no_compliance_claims(self) -> None:
        for name in REQUIRED_DOCS:
            text = (DOCS / name).read_text(encoding="utf-8").lower()
            for claim in FORBIDDEN_CLAIMS:
                assert claim not in text, f"{name}: {claim!r}"

    def test_status_labels_present(self) -> None:
        text = (DOCS / "SECURITY_MODEL.md").read_text(encoding="utf-8")
        for label in ("Implemented", "Partially implemented", "Not implemented"):
            assert label in text


class TestPolicySync:
    def test_retention_ttls_match_code(self) -> None:
        from shared.privacy import retention as policy

        text = (DOCS / "RETENTION_POLICY.md").read_text(encoding="utf-8")
        expectations = {
            "webhook_events": policy.WEBHOOK_ANONYMIZE_DAYS,
            "idempotency_keys": policy.IDEMPOTENCY_EXPIRE_DAYS,
            "telemetry": policy.TRACE_EXPIRE_DAYS,
            "eval_reports": policy.EVAL_REPORT_EXPIRE_DAYS,
        }
        for surface, days in expectations.items():
            section = re.search(
                rf"^## {re.escape(surface)}\s*$([\s\S]*?)(?=^## |\Z)",
                text,
                flags=re.M,
            )
            assert section is not None, surface
            assert str(days) in section.group(1), surface


class TestEvidenceLinks:
    def test_cited_test_paths_exist(self) -> None:
        repo_root = DOCS.parents[1]
        text = (DOCS / "SECURITY_MODEL.md").read_text(encoding="utf-8")
        cited = set(re.findall(r"`(tests/[A-Za-z0-9_/]+\.py)`", text))
        assert cited, "control matrix must cite evidence paths"
        missing = [c for c in cited if not (repo_root / c).is_file()]
        assert missing == [], missing
