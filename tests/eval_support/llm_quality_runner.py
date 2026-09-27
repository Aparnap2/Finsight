"""Deterministic LLM quality runner: FakeLLM -> P8 typed check -> P7 chain -> score.

Quality-only harness. Scores NEVER gate execution and NEVER replace the
deterministic safety tests in ``agents/evaluation/harness.py``; the harness
verdict is recorded alongside each case purely as an observational safety
floor. No network, no credentials, no live calls.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from agents.authority.claims import AgentCapability, AuthorityBoundary
from agents.authority.evidence import EvidenceRecord, EvidenceRegistry
from agents.brief import brief
from agents.discovery import DiscoveryRequest
from agents.discovery.engine import discover
from agents.evaluation.harness import evaluate
from agents.p8_runtime import contract as p8_01
from agents.reasoning.resolution import reason
from agents.runtime import RuntimeFactory
from agents.runtime.context import RuntimeContext
from shared.llm.fake import FakeLLM
from shared.llm.types import InvestigationPrompt

RUNNER_VERSION = "llm-quality-runner-v1"
MODEL_LABEL = "fake-llm-1"
PROVIDER_LABEL = "fake"

_EVIDENCE_PATTERN = re.compile(r"ev-[A-Za-z0-9-]+")
_CONFIDENCE_PATTERN = re.compile(r"confidence:\s*([0-9]+(?:\.[0-9]+)?)")

_FIXED_NOW = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
_FIXED_AT = datetime(2026, 1, 1, 0, 0, 0)
_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64


class _JournalMarker(BaseModel):
    """Trivial schema used only to journal one FakeLLM provider call."""

    model_config = ConfigDict(extra="forbid")

    marker: str = "ok"


def _registry(now: datetime = _FIXED_NOW) -> EvidenceRegistry:
    """Build the deterministic two-record evidence registry double."""
    records = {
        "ev-ledger-001": EvidenceRecord(
            source_id="src-ledger-001",
            evidence_id="ev-ledger-001",
            captured_at=now - timedelta(seconds=60),
            digest=_DIGEST_A,
            provenance="p6_evidence_store",
            ttl_seconds=3600,
        ),
        "ev-ledger-002": EvidenceRecord(
            source_id="src-ledger-002",
            evidence_id="ev-ledger-002",
            captured_at=now - timedelta(seconds=60),
            digest=_DIGEST_B,
            provenance="p6_evidence_store",
            ttl_seconds=3600,
        ),
    }
    return EvidenceRegistry(records, accessible_ids=set(records))


def _context(situation_id: str, now: datetime = _FIXED_NOW) -> RuntimeContext:
    """Issue a factory-bound runtime context for one eval case."""
    return RuntimeFactory().create_context(
        situation_id=situation_id,
        now=now,
        registry=_registry(now),
        boundary=AuthorityBoundary(),
    )


def _blob(summary: str, findings: list[str]) -> str:
    """Join model text for substring scoring (case-insensitive)."""
    return (f"{summary}\n" + "\n".join(findings)).lower()


def _fraction_present(blob: str, required: list[str]) -> float:
    """Return the fraction of required markers present in the blob."""
    if not required:
        return 1.0
    hits = sum(1 for marker in required if marker.lower() in blob)
    return hits / len(required)


def score_case(task_type: str, summary: str, findings: list[str], bar: dict[str, Any]) -> float:
    """Score one typed output against its quality bar (0.0 to 1.0, pure)."""
    blob = _blob(summary, findings)
    if task_type in ("extraction", "reasoning"):
        required = list(bar.get("must_extract", bar.get("must_reason", [])))
        return _fraction_present(blob, [str(m) for m in required])
    if task_type == "contradiction":
        return _fraction_present(blob, [str(m) for m in list(bar.get("must_preserve", []))])
    if task_type == "refusal":
        refusal = [str(m) for m in list(bar.get("refusal_markers", []))]
        authority = [str(m) for m in list(bar.get("authority_markers", []))]
        if not refusal:
            return 0.0
        refused = all(m.lower() in blob for m in refusal)
        clean = not any(m.lower() in blob for m in authority)
        return 1.0 if (refused and clean) else 0.0
    if task_type == "scope":
        forbidden = [str(m) for m in list(bar.get("must_not_mention", []))]
        return 1.0 if not any(m.lower() in blob for m in forbidden) else 0.0
    if task_type == "grounding":
        allowed = {str(m) for m in list(bar.get("allowed_ids", []))}
        mentioned = set(_EVIDENCE_PATTERN.findall(summary + "\n" + "\n".join(findings)))
        if not mentioned:
            return 1.0
        return sum(1 for m in mentioned if m in allowed) / len(mentioned)
    if task_type == "calibration":
        band = list(bar.get("confidence_band", [0.0, 1.0]))
        match = _CONFIDENCE_PATTERN.search(blob)
        if match is None:
            return 0.0
        value = float(match.group(1))
        return 1.0 if float(band[0]) <= value <= float(band[1]) else 0.0
    if task_type == "injection":
        authority = [str(m) for m in list(bar.get("authority_markers", []))]
        return 1.0 if not any(m.lower() in blob for m in authority) else 0.0
    return 0.0


def _objective(summary: str, findings: list[str]) -> str:
    """Map validated P8 content to DiscoveryRequest evidence input text only."""
    return f"Evaluate model notes. Summary: {summary} Findings: {'; '.join(findings)}"


def run_variant(
    case: dict[str, Any],
    variant: str,
    output: dict[str, Any],
    *,
    repo_root: Path,
) -> dict[str, Any]:
    """Run one case variant end to end; return its report row (pure I/O-free)."""
    _ = repo_root  # fixture refs are resolved by the caller, not the runner
    fake = FakeLLM(scripted={"_JournalMarker": {"marker": "ok"}})
    fake.generate_structured(InvestigationPrompt(user_prompt=case["input_text"]), _JournalMarker)
    fake_calls = len(fake.journal)

    raw_text = json.dumps(output)
    typed_ok = True
    typed_error: str | None = None
    summary = ""
    findings: list[str] = []
    try:
        structured = p8_01.validate_raw_output(
            p8_01.RawModelOutput(
                run_id=f"eval-{case['id']}-{variant}",
                text=raw_text,
                received_at=_FIXED_AT,
            )
        )
        summary = structured.summary
        findings = list(structured.findings)
    except p8_01.InvalidStructuredOutputError as exc:
        typed_ok = False
        typed_error = str(exc)

    p7_ok = False
    safety_verdict = "NO_P7_ENTRY"
    evidence_refs: list[str] = []
    if typed_ok:
        ctx = _context(f"eval-{case['id']}-{variant}")
        req = DiscoveryRequest(
            situation_id=ctx.situation_id,
            company_id=ctx.company_id,
            now=ctx.now,
            allowed_evidence_ids=("ev-ledger-001",),
            objective=_objective(summary, findings),
            allowed_capabilities=(AgentCapability.READ,),
        )
        disc = discover(req, context=ctx)
        rea = reason(disc, context=ctx)
        br = brief(rea, context=ctx)
        p7_ok = bool(disc.success and rea.success and br.success)
        if p7_ok:
            safety_verdict = evaluate(
                "E", "E1", context=ctx, discovery=disc, reasoning=rea, brief=br
            )
            evidence_refs = sorted(r.evidence_id for r in (disc.evidence_refs or ()))

    bar = dict(case["quality_bar"])
    threshold = float(bar.get("threshold", 1.0))
    score = score_case(case["task_type"], summary, findings, bar) if typed_ok else 0.0
    passed = bool(typed_ok and p7_ok and score >= threshold)
    return {
        "case_id": case["id"],
        "task_type": case["task_type"],
        "variant": variant,
        "typed_ok": typed_ok,
        "typed_error": typed_error,
        "score": score,
        "threshold": threshold,
        "passed": passed,
        "p7_ok": p7_ok,
        "safety_verdict": safety_verdict,
        "evidence_refs": evidence_refs,
        "fake_calls": fake_calls,
    }


def resolve_security_ref(case: dict[str, Any], repo_root: Path) -> Path | None:
    """Resolve a case's security fixture reference, asserting it exists."""
    ref = case.get("security_fixture_ref")
    if ref is None:
        return None
    path = repo_root / str(ref)
    if not path.exists():
        raise FileNotFoundError(f"security fixture ref missing: {path}")
    return path


def run_suite(
    dataset: dict[str, Any],
    *,
    repo_root: Path,
    variants: tuple[str, str] = ("valid", "degraded"),
) -> dict[str, Any]:
    """Run every case/variant and emit the JSON regression report structure."""
    for case in dataset["cases"]:
        resolve_security_ref(case, repo_root)
    rows: list[dict[str, Any]] = []
    for case in dataset["cases"]:
        for variant in variants:
            key = "valid_output" if variant == "valid" else "degraded_output"
            rows.append(run_variant(case, variant, dict(case[key]), repo_root=repo_root))
    passed = sum(1 for r in rows if r["passed"])
    mean_score = sum(float(r["score"]) for r in rows) / len(rows) if rows else 0.0
    return {
        "model": MODEL_LABEL,
        "provider": PROVIDER_LABEL,
        "provenance": {
            "runner": RUNNER_VERSION,
            "dataset": str(dataset.get("dataset_id", "unknown")),
            "dataset_cases": len(dataset["cases"]),
        },
        "cases": rows,
        "summary": {
            "total": len(rows),
            "passed": passed,
            "failed": len(rows) - passed,
            "mean_score": mean_score,
        },
    }


def load_dataset(path: Path) -> dict[str, Any]:
    """Load the golden dataset JSON from disk."""
    dataset: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return dataset
