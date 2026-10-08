"""Root cause agent — investigates material variances via LLM or fallback."""

import contextlib
from typing import Any

from shared.models.state import EvidenceItem, PipelineState, RootCauseFinding, Variance
from shared.privacy import boundary as privacy_boundary
from shared.privacy.boundary import Purpose
from shared.privacy.inventory import DataClassification
from shared.utils.llm_client import LLMClient

_VARIANCE_CLASSIFICATIONS: dict[str, DataClassification] = {
    "account_id": DataClassification.INTERNAL,
    "account_name": DataClassification.INTERNAL,
    "department": DataClassification.INTERNAL,
    "actual_amount": DataClassification.FINANCIAL_SENSITIVE,
    "budget_amount": DataClassification.FINANCIAL_SENSITIVE,
    "variance_amount": DataClassification.FINANCIAL_SENSITIVE,
    "variance_pct": DataClassification.FINANCIAL_SENSITIVE,
    "is_material": DataClassification.INTERNAL,
    "classification": DataClassification.INTERNAL,
    "confidence_score": DataClassification.INTERNAL,
}


def _authorize_variance(variance: Variance, tenant_id: str) -> Variance:
    """Gate variance prompt data (P10-03); amounts allowed for ROOT_CAUSE."""
    safe = privacy_boundary.authorize_llm_context(
        {
            "account_id": variance.account_id,
            "account_name": variance.account_name,
            "department": variance.department,
            "actual_amount": variance.actual_amount,
            "budget_amount": variance.budget_amount,
            "variance_amount": variance.variance_amount,
            "variance_pct": variance.variance_pct,
            "is_material": variance.is_material,
            "classification": variance.classification,
            "confidence_score": variance.confidence_score,
        },
        purpose=Purpose.ROOT_CAUSE,
        tenant_id=tenant_id,
        data_tenant_id=tenant_id,
        classifications=_VARIANCE_CLASSIFICATIONS,
    )
    return variance.model_copy(update=safe)


def _build_prompt(variance: Variance) -> str:
    return (
        "You are a senior financial analyst investigating budget variances.\n"
        "Analyze the variance below and respond in EXACTLY this format — no markdown, "
        "no extra text:\n\n"
        "SUMMARY: <one sentence root cause>\n"
        "EVIDENCE: <comma-separated data points that support your conclusion>\n"
        "CONFIDENCE: <number 0.0-1.0>\n"
        "ACTION: <one sentence recommended next step>\n\n"
        "--- VARIANCE DATA ---\n"
        f"Account: {variance.account_name} ({variance.account_id})\n"
        f"Department: {variance.department}\n"
        f"Actual: ${float(variance.actual_amount):,.2f}\n"
        f"Budget: ${float(variance.budget_amount):,.2f}\n"
        f"Variance: ${float(variance.variance_amount):,.2f} ({float(variance.variance_pct):.1f}%)\n"
        "---------------------\n"
        "Respond now:"
    )


def _parse_llm_response(text: str) -> dict[str, Any]:
    import re

    result = {"summary": "", "evidence": [], "confidence_score": 0.5, "recommended_action": ""}

    m = re.search(r"SUMMARY:\s*(.+)", text, re.IGNORECASE)
    if m:
        result["summary"] = m.group(1).strip()

    m = re.search(r"CONFIDENCE:\s*([\d.]+)", text, re.IGNORECASE)
    if m:
        with contextlib.suppress(ValueError):
            result["confidence_score"] = float(m.group(1))

    m = re.search(r"ACTION:\s*(.+)", text, re.IGNORECASE)
    if m:
        result["recommended_action"] = m.group(1).strip()

    m = re.search(r"EVIDENCE:\s*(.+)", text, re.IGNORECASE)
    if m:
        items = [e.strip() for e in m.group(1).split(",")]
        result["evidence"] = [
            EvidenceItem(
                source_table="llm_analysis",
                record_id="",
                field="observation",
                value=0.0,
                period="",
                description=e,
            )
            for e in items
            if e
        ]

    return result


def investigate_root_causes(
    variances: list[Variance],
    llm_client: LLMClient | None = None,
    *,
    tenant_id: str,
) -> list[RootCauseFinding]:
    findings = []
    for v in variances:
        if llm_client:
            safe_variance = _authorize_variance(v, tenant_id)
            prompt = _build_prompt(safe_variance)
            text = llm_client.generate(prompt, max_tokens=512)
            parsed = _parse_llm_response(text)
            finding = RootCauseFinding(
                variance_id=v.account_id,
                summary=parsed["summary"] or f"Root cause for {v.account_name}",
                evidence=parsed["evidence"],
                confidence_score=parsed["confidence_score"],
                recommended_action=parsed["recommended_action"],
            )
        else:
            finding = RootCauseFinding(
                variance_id=v.account_id,
                summary=(
                    f"Investigation pending for {v.account_name} variance of "
                    f"{float(v.variance_amount):,.0f}"
                ),
                evidence=[],
                confidence_score=0.5,
                recommended_action="Review with department head",
            )
        findings.append(finding)
    return findings


def root_cause_node(state: PipelineState, llm_client: LLMClient | None = None) -> dict[str, Any]:
    if llm_client is None:
        llm_client = LLMClient()
    material_variances = [v for v in state.get("variances", []) if v.is_material]
    findings = investigate_root_causes(
        material_variances, llm_client=llm_client, tenant_id=str(state.get("tenant_id", ""))
    )
    return {"root_causes": findings, "current_step": "root_cause_complete"}
