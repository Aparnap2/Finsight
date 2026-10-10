"""Workflow boundary lock-in (APA-80 R4): CI proves Postgres + S3 only.

Fails if the integration workflow ever widens the emulated AWS
surface (SQS/SNS/EventBridge/Lambda/StepFunctions/DynamoDB), unpins
the LocalStack image, or drops the normative boundary statement.
Mirrors test_ministack_compose_healthcheck_and_transport_invariants
for the workflow file itself. No network required.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "integration.yml"

_BOUNDARY_MARKERS = (
    "SERVICES=s3",
    "localstack/localstack:3.8",
    "SQS E2E",
    "managed AWS",
)

_ALLOWED_SERVICES = frozenset({"s3"})
_SERVICES_LINE = re.compile(r"^\s*SERVICES:\s*(.+?)\s*$")


def _emulator_services() -> set[str]:
    """Parse effective LocalStack SERVICES values (no yaml dependency).

    Catches comma-joined widening (``SERVICES: s3,sqs``) that substring
    greps miss. Comment lines are excluded.
    """
    services: set[str] = set()
    for line in WORKFLOW.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("#"):
            continue
        match = _SERVICES_LINE.match(line)
        if match:
            services.update(part.strip().lower() for part in match.group(1).split(","))
    return services


class TestWorkflowEmulatorBoundary:
    def test_services_restricted_to_s3(self) -> None:
        """The effective emulated surface is exactly S3 (parsed, not grepped)."""
        assert _emulator_services() == _ALLOWED_SERVICES

    def test_localstack_image_pinned(self) -> None:
        """No floating :latest emulator image."""
        text = WORKFLOW.read_text(encoding="utf-8")
        assert "localstack/localstack:3.8" in text
        assert "localstack/localstack:latest" not in text

    def test_normative_boundary_statement_present(self) -> None:
        """The workflow states what CI may and may not claim."""
        text = WORKFLOW.read_text(encoding="utf-8")
        for marker in _BOUNDARY_MARKERS:
            assert marker in text, f"boundary statement missing marker: {marker}"
