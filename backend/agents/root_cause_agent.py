from backend.models.state import PipelineState, Variance, RootCauseFinding


def investigate_root_causes(variances: list[Variance]) -> list[RootCauseFinding]:
    findings = []
    for v in variances:
        finding = RootCauseFinding(
            variance_id=v.account_id,
            summary=f"Investigation pending for {v.account_name} variance of {v.variance_amount:,.0f}",
            evidence=[],
            confidence_score=0.5,
            recommended_action="Review with department head",
        )
        findings.append(finding)
    return findings


def root_cause_node(state: PipelineState) -> dict:
    material_variances = [v for v in state.get("variances", []) if v.is_material]
    findings = investigate_root_causes(material_variances)
    return {"root_causes": findings, "current_step": "root_cause_complete"}
