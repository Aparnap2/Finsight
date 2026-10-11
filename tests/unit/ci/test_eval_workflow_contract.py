"""Eval workflow contract lock-in (APA-80 R2): manual-only live LLM.

Fails if the live-LLM job can run on push/PR: it must carry an
explicit workflow_dispatch-only condition, and the deterministic
golden job must exist as the push/PR gate. Mirrors the boundary
lock-in pattern. No network required.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ai-evals.yml"

_MANUAL_ONLY = "github.event_name == 'workflow_dispatch'"


def _job_blocks(text: str) -> dict[str, list[str]]:
    """Split top-level job blocks (two-space indent) into name -> lines."""
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if match:
            current = match.group(1)
            blocks[current] = []
        elif current is not None:
            blocks[current].append(line)
    return blocks


class TestEvalWorkflowContract:
    def test_live_llm_job_is_dispatch_only(self) -> None:
        """The live-LLM job cannot run on push/PR even if triggers widen."""
        blocks = _job_blocks(WORKFLOW.read_text(encoding="utf-8"))
        assert "llm-evals" in blocks, "llm-evals job missing"
        conditions = [
            line.strip().removeprefix("if:").strip()
            for line in blocks["llm-evals"]
            if line.strip().startswith("if:")
        ]
        # Exact match (normalized): a broadened condition such as
        # "... == 'workflow_dispatch' || always()" must NOT pass.
        assert conditions == [_MANUAL_ONLY], (
            f"llm-evals must carry exactly the workflow_dispatch-only condition, got {conditions}"
        )

    def test_deterministic_gate_exists_for_push_pr(self) -> None:
        """The push/PR path is owned by the deterministic golden job."""
        blocks = _job_blocks(WORKFLOW.read_text(encoding="utf-8"))
        assert "golden-dataset" in blocks, "golden-dataset job missing"
        golden = "\n".join(blocks["golden-dataset"])
        assert "finance.evaluation.runner" in golden
        assert "total" in golden and "failed" in golden

    def test_broadened_condition_rejected(self) -> None:
        """Negative control: an || always() disjunct must not satisfy the gate."""
        text = (
            "  llm-evals:\n"
            "    if: github.event_name == 'workflow_dispatch' || always()\n"
            "    runs-on: ubuntu-latest\n"
        )
        blocks = _job_blocks(text)
        conditions = [
            line.strip().removeprefix("if:").strip()
            for line in blocks["llm-evals"]
            if line.strip().startswith("if:")
        ]
        assert conditions != [_MANUAL_ONLY]
