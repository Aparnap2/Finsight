"""Workflow boundary lock-in (APA-80 R4): CI proves Postgres + S3 only.

Fails if the integration workflow ever widens the emulated AWS
surface (SQS/SNS/EventBridge/Lambda/StepFunctions/DynamoDB), unpins
the LocalStack image, or drops the normative boundary statement.
Mirrors test_ministack_compose_healthcheck_and_transport_invariants
for the workflow file itself. No network required.
"""

from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "integration.yml"

_BOUNDARY_MARKERS = (
    "SERVICES=s3",
    "localstack/localstack:3.8",
    "SQS E2E",
    "managed AWS",
)


class TestWorkflowEmulatorBoundary:
    def test_services_restricted_to_s3(self) -> None:
        """The emulated surface stays S3-only unless explicitly reviewed."""
        text = WORKFLOW.read_text(encoding="utf-8")
        code = "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))
        assert "SERVICES: s3" in code or "SERVICES=s3" in code
        lowered = code.lower()
        for forbidden in (
            "services=sqs",
            "services=sns",
            "services=lambda",
            "eventbridge",
            "dynamodb",
            "stepfunctions",
        ):
            assert forbidden not in lowered, f"emulator surface widened: {forbidden}"

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
