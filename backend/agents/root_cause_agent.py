from backend.models.state import PipelineState, Variance, RootCauseFinding, EvidenceItem
from backend.agents.llm_client import LLMClient


def _build_prompt(variance: Variance) -> str:
    return (
        "You are a senior financial analyst investigating budget variances.\n"
        "Analyze the variance below and respond in EXACTLY this format — no markdown, no extra text:\n\n"
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


def _parse_llm_response(text: str) -> dict:
    import re
    result = {"summary": "", "evidence": [], "confidence_score": 0.5, "recommended_action": ""}

    m = re.search(r'SUMMARY:\s*(.+)', text, re.IGNORECASE)
    if m:
        result["summary"] = m.group(1).strip()

    m = re.search(r'CONFIDENCE:\s*([\d.]+)', text, re.IGNORECASE)
    if m:
        try:
            result["confidence_score"] = float(m.group(1))
        except ValueError:
            pass

    m = re.search(r'ACTION:\s*(.+)', text, re.IGNORECASE)
    if m:
        result["recommended_action"] = m.group(1).strip()

    m = re.search(r'EVIDENCE:\s*(.+)', text, re.IGNORECASE)
    if m:
        items = [e.strip() for e in m.group(1).split(",")]
        result["evidence"] = [
            EvidenceItem(
                source_table="llm_analysis", record_id="", field="observation",
                value=0.0, period="", description=e,
            )
            for e in items if e
        ]

    return result


def investigate_root_causes(
    variances: list[Variance],
    llm_client: LLMClient | None = None,
) -> list[RootCauseFinding]:
    findings = []
    for v in variances:
        if llm_client:
            prompt = _build_prompt(v)
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
                summary=f"Investigation pending for {v.account_name} variance of {float(v.variance_amount):,.0f}",
                evidence=[],
                confidence_score=0.5,
                recommended_action="Review with department head",
            )
        findings.append(finding)
    return findings


def root_cause_node(state: PipelineState, llm_client: LLMClient | None = None) -> dict:
    if llm_client is None:
        llm_client = LLMClient()
    material_variances = [v for v in state.get("variances", []) if v.is_material]
    findings = investigate_root_causes(material_variances, llm_client=llm_client)
    return {"root_causes": findings, "current_step": "root_cause_complete"}
