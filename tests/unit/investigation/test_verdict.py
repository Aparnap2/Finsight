"""P6-05 investigation verdict + proposal engine tests (R1-R14, V18-V31).

RED-first acceptance for the FS-231 walk: findings from authoritative
ids, the correlation chain, the MEDIUM hypothesis, the 10000 proposal,
and the anti-promotion assertion. Refusal codes name the attack; data
is dropped with its code, never silently fixed or promoted.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from finance.correlation.chain import build_chain
from finance.correlation.collector import CollectedEvidence
from finance.correlation.converter import trust_class_for
from finance.correlation.package import EvidencePackage, MissingLeg, assemble_package
from finance.domain import lifecycle as frozen_lifecycle
from finance.domain.lifecycle import require_evidence_for_proposal
from finance.investigation.proposal import (
    AmountTransform,
    ResolutionProposal,
    assemble_verdict,
    bind_proposal_amount,
    proposal_hash,
    quarantine_llm_shaped,
    satisfies_d3_gate,
)
from finance.investigation.verdict import (
    NON_CAUSAL_BANNER,
    AuthorizedAction,
    CausalConclusion,
    Confidence,
    Correlation,
    FactualFinding,
    Hypothesis,
    InvestigationVerdict,
    assert_no_preauthorized,
    refuse_hypothesis_as_fact,
    refuse_promotion,
    verdict_canonical_bytes,
    verdict_handoff,
)

SITUATION = "FS-2026-0916-00231"
OTHER_SITUATION = "FS-2026-0916-00999"
VARIANCE = Decimal("10000")
POLICY = (
    "legacy correction always needs human approval plus valid "
    "account code plus balanced batch"
)

EV_RAZORPAY = "razorpay:stl-231:aaa111"
EV_QUICKBOOKS = "quickbooks:acc-231:bbb222"
EV_LEGACY = "cobol_legacy:leg-231:ccc333"
EV_SHEETS = "sheets:exp-231:ddd444"
ALL_AUTHORITATIVE = (EV_RAZORPAY, EV_QUICKBOOKS, EV_LEGACY)


def make_finding_v11() -> FactualFinding:
    """Build the V11 provider-adjustment FACT (+10000, razorpay)."""
    return FactualFinding(
        finding_id="FIND-V11",
        situation_id=SITUATION,
        evidence_ids=(EV_RAZORPAY,),
        quoted_value="+10000",
        source_system="razorpay",
        verified_ids=(EV_RAZORPAY,),
    )


def make_finding_v12() -> FactualFinding:
    """Build the V12 QB-absence FACT (book leg expects 10000)."""
    return FactualFinding(
        finding_id="FIND-V12",
        situation_id=SITUATION,
        evidence_ids=(EV_QUICKBOOKS,),
        quoted_value="expects posting 10000",
        source_system="quickbooks",
        verified_ids=(EV_QUICKBOOKS,),
    )


def make_finding_v13() -> FactualFinding:
    """Build the V13 legacy-RJ FACT (RJ, INVALID_ACCOUNT_CODE, 4812)."""
    return FactualFinding(
        finding_id="FIND-V13",
        situation_id=SITUATION,
        evidence_ids=(EV_LEGACY,),
        quoted_value="RJ INVALID_ACCOUNT_CODE expected 4812",
        source_system="cobol_legacy",
        verified_ids=(EV_LEGACY,),
    )


def make_correlation_v14() -> Correlation:
    """Build the V14 CORRELATION over the V11-V13 findings."""
    return Correlation(
        edge_id="EDGE-V14",
        situation_id=SITUATION,
        edge_refs=(EV_RAZORPAY, EV_QUICKBOOKS, EV_LEGACY),
        edge_label="CORRELATED_WITH",
        banner=NON_CAUSAL_BANNER,
    )


def make_hypothesis_v15() -> Hypothesis:
    """Build the V15 rejected-posting HYPOTHESIS (MEDIUM)."""
    return Hypothesis(
        hypothesis_id="HYP-V15",
        situation_id=SITUATION,
        text=(
            "legacy rejection of the 10000 correction leg under a wrong "
            "account code explains the residual as a candidate"
        ),
        confidence=Confidence.MEDIUM,
        basis_refs=("EDGE-V14", "FIND-V13"),
    )


def make_proposal_v16(amount: Decimal = VARIANCE) -> ResolutionProposal:
    """Build the V16 legacy-correction PROPOSAL (10000, code 4812)."""
    return ResolutionProposal(
        proposal_id="PROP-V16",
        situation_id=SITUATION,
        action="REPROCESS_LEGACY_RECORD",
        amount=amount,
        account_code="4812",
        evidence_refs=ALL_AUTHORITATIVE,
        hypothesis_ref="HYP-V15",
        policy_pointer=POLICY,
    )


def make_findings() -> tuple[FactualFinding, ...]:
    """Build the V11-V13 finding triple."""
    return (make_finding_v11(), make_finding_v12(), make_finding_v13())


def make_complete_package() -> EvidencePackage:
    """Assemble a real COMPLETE P6-04 package over the FS-231 ids."""
    collected = CollectedEvidence(
        evidence_ids=tuple(sorted(ALL_AUTHORITATIVE)),
        items={},
        contents={},
    )
    chain = build_chain(collected.evidence_ids)
    return assemble_package(
        tenant_id="meridian",
        case_id=SITUATION,
        batch_id="batch-231",
        collected=collected,
        chain=chain,
        missing=(),
    )


def make_incomplete_package() -> EvidencePackage:
    """Assemble a real INCOMPLETE P6-04 package missing the legacy leg."""
    collected = CollectedEvidence(
        evidence_ids=tuple(sorted((EV_RAZORPAY, EV_QUICKBOOKS))),
        items={},
        contents={},
    )
    chain = build_chain(collected.evidence_ids)
    return assemble_package(
        tenant_id="meridian",
        case_id=SITUATION,
        batch_id="batch-231",
        collected=collected,
        chain=chain,
        missing=(
            MissingLeg(
                source_system="cobol_legacy",
                key="leg-231",
                reason="LEGACY_RESULT_UNREADABLE",
            ),
        ),
    )


def test_r1_fs231_full_walk() -> None:
    """R1/V18: V11-V16 assemble in order; amount equals 10000."""
    findings = make_findings()
    edge = make_correlation_v14()
    hypothesis = make_hypothesis_v15()
    proposal = make_proposal_v16()
    package = make_complete_package()
    assert package.complete is True
    verdict = assemble_verdict(
        situation_id=SITUATION,
        discrepancy=VARIANCE,
        findings=findings,
        correlations=(edge,),
        hypotheses=(hypothesis,),
        proposal=proposal,
        package=package,
    )
    assert verdict.terminal_label == "PROPOSED"
    assert verdict.proposal is not None
    assert verdict.proposal.amount == Decimal("10000")
    assert verdict.proposal.account_code == "4812"
    assert set(verdict.proposal.evidence_refs) == set(ALL_AUTHORITATIVE)
    kinds = (
        [f.kind for f in verdict.findings]
        + [e.kind for e in verdict.correlations]
        + [h.kind for h in verdict.hypotheses]
        + [verdict.proposal.kind]
    )
    assert kinds == [
        "FACTUAL_FINDING",
        "FACTUAL_FINDING",
        "FACTUAL_FINDING",
        "CORRELATION",
        "HYPOTHESIS",
        "RESOLUTION_PROPOSAL",
    ]
    assert len(verdict.fingerprint) == 64
    handoff = verdict_handoff(verdict)
    assert set(handoff) == {"findings", "correlations", "hypotheses", "proposal"}
    assert_no_preauthorized(handoff)
    with pytest.raises(ValueError, match="PROMOTION_REFUSED"):
        refuse_promotion(
            from_kind="HYPOTHESIS", to_kind="FACTUAL_FINDING", item_id="HYP-V15"
        )
    with pytest.raises(ValueError, match="HYPOTHESIS_AS_FACT"):
        refuse_hypothesis_as_fact("HYP-V15")


def test_r2_unsupported_causal_claim_refused() -> None:
    """R2/V19: CAUSED_BY/ROOT_CAUSE wording refused; edge kept."""
    with pytest.raises(ValidationError, match="CAUSAL_UPGRADE"):
        Hypothesis(
            hypothesis_id="HYP-CAUSAL",
            situation_id=SITUATION,
            text="the RJ caused the variance and proves the root cause",
            confidence=Confidence.HIGH,
            basis_refs=("EDGE-V14",),
        )
    with pytest.raises(ValidationError, match="CAUSAL_UPGRADE"):
        Correlation(
            edge_id="EDGE-CAUSAL",
            situation_id=SITUATION,
            edge_refs=(EV_RAZORPAY, EV_LEGACY),
            edge_label="CAUSED_BY",
            banner=NON_CAUSAL_BANNER,
        )
    with pytest.raises(ValidationError, match="CAUSAL_UPGRADE"):
        CausalConclusion(situation_id=SITUATION, text="rj caused variance")
    with pytest.raises(ValidationError, match="PROPOSAL_AS_APPROVAL"):
        AuthorizedAction(situation_id=SITUATION, text="execute now")
    edge = make_correlation_v14()
    assert edge.edge_label == "CORRELATED_WITH"
    assert edge.banner == NON_CAUSAL_BANNER


def test_r3_missing_evidence_proposal_refused() -> None:
    """R3/V20: INCOMPLETE package holds the proposal, naming the leg."""
    package = make_incomplete_package()
    assert package.complete is False
    proposal = make_proposal_v16()
    with pytest.raises(ValueError, match="EVIDENCE_INCOMPLETE"):
        assemble_verdict(
            situation_id=SITUATION,
            discrepancy=VARIANCE,
            findings=(make_finding_v11(), make_finding_v12()),
            correlations=(),
            hypotheses=(make_hypothesis_v15(),),
            proposal=proposal,
            package=package,
        )
    try:
        assemble_verdict(
            situation_id=SITUATION,
            discrepancy=VARIANCE,
            findings=(make_finding_v11(), make_finding_v12()),
            correlations=(),
            hypotheses=(make_hypothesis_v15(),),
            proposal=proposal,
            package=package,
        )
    except ValueError as exc:
        assert "cobol_legacy" in str(exc)
        assert "leg-231" in str(exc)
    held = assemble_verdict(
        situation_id=SITUATION,
        discrepancy=VARIANCE,
        findings=(make_finding_v11(), make_finding_v12()),
        correlations=(),
        hypotheses=(),
        proposal=None,
        package=package,
        reasons=("legacy leg unreadable; held without guessing",),
    )
    assert held.terminal_label == "UNRESOLVED"
    assert held.proposal is None


def test_r4_conflicting_authoritative_stalemate() -> None:
    """R4/V21: silent winners refused; explicit cite or UNRESOLVED."""
    proposal = make_proposal_v16()
    with pytest.raises(ValueError, match="RECORD_SHOPPING"):
        assemble_verdict(
            situation_id=SITUATION,
            discrepancy=VARIANCE,
            findings=make_findings(),
            correlations=(make_correlation_v14(),),
            hypotheses=(make_hypothesis_v15(),),
            proposal=proposal,
            conflict_present=True,
        )
    citing = ResolutionProposal(
        proposal_id="PROP-V16",
        situation_id=SITUATION,
        action="REPROCESS_LEGACY_RECORD",
        amount=VARIANCE,
        account_code="4812",
        evidence_refs=ALL_AUTHORITATIVE,
        hypothesis_ref="HYP-V15",
        policy_pointer=POLICY,
        conflict_ref="CONFLICTING_EVIDENCE:cobol_legacy:leg-231",
    )
    cited = assemble_verdict(
        situation_id=SITUATION,
        discrepancy=VARIANCE,
        findings=make_findings(),
        correlations=(make_correlation_v14(),),
        hypotheses=(make_hypothesis_v15(),),
        proposal=citing,
        conflict_present=True,
    )
    assert cited.terminal_label == "PROPOSED"
    stalemate = assemble_verdict(
        situation_id=SITUATION,
        discrepancy=VARIANCE,
        findings=make_findings(),
        correlations=(make_correlation_v14(),),
        hypotheses=(make_hypothesis_v15(),),
        proposal=None,
        conflict_present=True,
        reasons=("authoritative collision preserved; no silent winner",),
    )
    assert stalemate.terminal_label == "UNRESOLVED"


def test_r5_kind_tags_survive_round_trip() -> None:
    """R5/V22: serialization preserves kinds; swaps fail KIND_MISMATCH."""
    finding = make_finding_v11()
    hypothesis = make_hypothesis_v15()
    finding_json = finding.model_dump_json()
    hypothesis_json = hypothesis.model_dump_json()
    assert FactualFinding.model_validate_json(finding_json).model_dump_json()
    assert (
        finding_json
        == FactualFinding.model_validate_json(finding_json).model_dump_json()
    )
    assert (
        hypothesis_json
        == Hypothesis.model_validate_json(hypothesis_json).model_dump_json()
    )
    assert Hypothesis.model_validate_json(hypothesis_json).confidence == "MEDIUM"
    swapped = json.loads(finding_json)
    swapped["kind"] = "HYPOTHESIS"
    with pytest.raises(ValidationError, match="KIND_MISMATCH"):
        Hypothesis.model_validate(swapped)
    dropped = json.loads(hypothesis_json)
    dropped["kind"] = "FACTUAL_FINDING"
    with pytest.raises(ValidationError, match="KIND_MISMATCH"):
        FactualFinding.model_validate(dropped)


def test_r6_proposal_without_evidence_refused() -> None:
    """R6/V23: zero evidence ids refused; hypothesis alone never passes."""
    with pytest.raises(ValidationError, match="PROPOSAL_WITHOUT_EVIDENCE"):
        ResolutionProposal(
            proposal_id="PROP-EMPTY",
            situation_id=SITUATION,
            action="REPROCESS_LEGACY_RECORD",
            amount=VARIANCE,
            account_code="4812",
            evidence_refs=(),
            hypothesis_ref="HYP-V15",
            policy_pointer=POLICY,
        )
    with pytest.raises(ValueError, match="D3 evidence gate"):
        require_evidence_for_proposal(
            SimpleNamespace(evidence_ids=(), hypothesis_count=1)
        )
    with pytest.raises(ValueError, match="D3 evidence gate"):
        require_evidence_for_proposal(
            SimpleNamespace(evidence_ids=(EV_RAZORPAY,), hypothesis_count=0)
        )
    satisfies_d3_gate(ALL_AUTHORITATIVE, 1)


def test_r7_amount_must_equal_discrepancy() -> None:
    """R7/V24: 9999 refused; 10000 accepted; other only with transform."""
    findings = make_findings()
    edge = make_correlation_v14()
    hypothesis = make_hypothesis_v15()
    off = make_proposal_v16(amount=Decimal("9999"))
    with pytest.raises(ValueError, match="AMOUNT_MISMATCH"):
        bind_proposal_amount(off, VARIANCE)
    with pytest.raises(ValueError, match="AMOUNT_MISMATCH"):
        assemble_verdict(
            situation_id=SITUATION,
            discrepancy=VARIANCE,
            findings=findings,
            correlations=(edge,),
            hypotheses=(hypothesis,),
            proposal=off,
        )
    assert bind_proposal_amount(make_proposal_v16(), VARIANCE).amount == VARIANCE
    split = ResolutionProposal(
        proposal_id="PROP-SPLIT",
        situation_id=SITUATION,
        action="REPROCESS_LEGACY_RECORD",
        amount=Decimal("12000"),
        account_code="4812",
        evidence_refs=ALL_AUTHORITATIVE,
        hypothesis_ref="HYP-V15",
        policy_pointer=POLICY,
        amount_transform=AmountTransform(
            rule_id="FEE_SPLIT_231",
            legs=("legacy:10000", "fee:2000"),
            arithmetic="10000 + 2000 = 12000",
            result=Decimal("12000"),
        ),
    )
    assert bind_proposal_amount(split, VARIANCE).amount == Decimal("12000")
    accepted = assemble_verdict(
        situation_id=SITUATION,
        discrepancy=VARIANCE,
        findings=findings,
        correlations=(edge,),
        hypotheses=(hypothesis,),
        proposal=split,
    )
    assert accepted.proposal is not None
    assert accepted.proposal.amount == Decimal("12000")


def test_r8_probabilistic_amount_never_wins() -> None:
    """R8/V25: estimates refused; the domain total stays authoritative."""
    with pytest.raises(ValidationError, match="PROBABILISTIC_AMOUNT"):
        ResolutionProposal(
            proposal_id="PROP-EST",
            situation_id=SITUATION,
            action="REPROCESS_LEGACY_RECORD",
            amount=VARIANCE,
            account_code="4812",
            evidence_refs=ALL_AUTHORITATIVE,
            hypothesis_ref="HYP-V15",
            policy_pointer=POLICY,
            amount_source="ESTIMATE",
        )
    with pytest.raises(ValidationError, match="PROBABILISTIC_AMOUNT"):
        ResolutionProposal(
            proposal_id="PROP-GUESS",
            situation_id=SITUATION,
            action="REPROCESS_LEGACY_RECORD",
            amount=Decimal("10500"),
            account_code="4812",
            evidence_refs=ALL_AUTHORITATIVE,
            hypothesis_ref="HYP-V15",
            policy_pointer=POLICY,
            amount_source="MODEL_COMPLETION",
        )
    bound = bind_proposal_amount(make_proposal_v16(), VARIANCE)
    assert bound.amount == VARIANCE


def test_r9_proposal_is_not_approval() -> None:
    """R9/V26: approval/execution stamps refused with exact code."""
    base = {
        "proposal_id": "PROP-STAMP",
        "situation_id": SITUATION,
        "action": "REPROCESS_LEGACY_RECORD",
        "amount": VARIANCE,
        "account_code": "4812",
        "evidence_refs": ALL_AUTHORITATIVE,
        "hypothesis_ref": "HYP-V15",
        "policy_pointer": POLICY,
    }
    for stamp in (
        "approval_id",
        "decider",
        "decision",
        "decided_at",
        "execution_id",
        "s3_key",
    ):
        with pytest.raises(ValidationError, match="PROPOSAL_AS_APPROVAL"):
            ResolutionProposal.model_validate({**base, stamp: "x"})
    fields = set(ResolutionProposal.model_fields)
    assert not (fields & {"approval_id", "decider", "execution_id", "s3_key"})


def test_r10_no_lifecycle_mutation() -> None:
    """R10/V27: APPROVED/EXECUTING/CLOSED outputs are unrepresentable."""
    with pytest.raises(ValidationError, match="LIFECYCLE_WRITE_REFUSED"):
        InvestigationVerdict.model_validate(
            {
                "situation_id": SITUATION,
                "findings": [],
                "correlations": [],
                "hypotheses": [],
                "proposal": None,
                "terminal_label": "APPROVED",
                "reasons": ("x",),
                "fingerprint": "0" * 64,
            }
        )
    with pytest.raises(ValidationError, match="LIFECYCLE_WRITE_REFUSED"):
        ResolutionProposal.model_validate(
            {
                "proposal_id": "P",
                "situation_id": SITUATION,
                "action": "REPROCESS_LEGACY_RECORD",
                "amount": VARIANCE,
                "evidence_refs": ALL_AUTHORITATIVE,
                "hypothesis_ref": "HYP-V15",
                "policy_pointer": POLICY,
                "status": "APPROVED",
            }
        )
    assert set(InvestigationVerdict.model_fields) & {"status", "transition"} == set()
    assert "UNRESOLVED" not in frozen_lifecycle.ALLOWED_TRANSITIONS


def test_r11_wrong_situation_evidence_refused() -> None:
    """R11/V28: evidence bound to another situation fails the cite."""
    binding = {
        EV_RAZORPAY: SITUATION,
        EV_QUICKBOOKS: SITUATION,
        EV_LEGACY: OTHER_SITUATION,
    }
    with pytest.raises(ValueError, match="CROSS_CASE_REFUSED"):
        assemble_verdict(
            situation_id=SITUATION,
            discrepancy=VARIANCE,
            findings=make_findings(),
            correlations=(make_correlation_v14(),),
            hypotheses=(make_hypothesis_v15(),),
            proposal=make_proposal_v16(),
            evidence_binding=binding,
        )


def test_r12_double_assembly_fingerprint_stable() -> None:
    """R12/V29: identical inputs yield byte-identical verdict bytes."""
    kwargs = {
        "situation_id": SITUATION,
        "discrepancy": VARIANCE,
        "findings": make_findings(),
        "correlations": (make_correlation_v14(),),
        "hypotheses": (make_hypothesis_v15(),),
        "proposal": make_proposal_v16(),
        "package": make_complete_package(),
    }
    first = assemble_verdict(**kwargs, envelope={"run_id": "run-1"})
    second = assemble_verdict(**kwargs, envelope={"run_id": "run-2"})
    assert verdict_canonical_bytes(first) == verdict_canonical_bytes(second)
    assert first.fingerprint == second.fingerprint
    assert first.proposal is not None and second.proposal is not None
    assert proposal_hash(first.proposal) == proposal_hash(second.proposal)


def test_r13_llm_shaped_input_quarantined() -> None:
    """R13/V30: root_cause shapes quarantine to LOW HYPOTHESIS at best."""
    quarantined = quarantine_llm_shaped(
        {"root_cause": "legacy RJ caused the variance"},
        situation_id=SITUATION,
        basis_refs=("EDGE-V14", "FIND-V13"),
    )
    assert quarantined.kind == "HYPOTHESIS"
    assert quarantined.confidence == Confidence.LOW
    assert quarantined.quarantined is True
    assert "LLM_SHAPED_QUARANTINED" in quarantined.flags
    with pytest.raises(ValueError, match="PROMOTION_REFUSED"):
        refuse_promotion(
            from_kind="HYPOTHESIS",
            to_kind="CAUSAL_CONCLUSION",
            item_id=quarantined.hypothesis_id,
        )
    with pytest.raises(ValueError, match="HYPOTHESIS_AS_FACT"):
        refuse_hypothesis_as_fact(quarantined.hypothesis_id)


def test_r14_no_viable_resolution_unresolved() -> None:
    """R14/V31: void ends UNRESOLVED with reasons; no invented proposal."""
    verdict = assemble_verdict(
        situation_id=SITUATION,
        discrepancy=VARIANCE,
        findings=(),
        correlations=(),
        hypotheses=(),
        proposal=None,
        reasons=("empty evidence; no hypothesis supports a proposal",),
    )
    assert verdict.terminal_label == "UNRESOLVED"
    assert verdict.proposal is None
    assert verdict.reasons
    with pytest.raises(ValueError, match="PROPOSAL_INVENTED"):
        assemble_verdict(
            situation_id=SITUATION,
            discrepancy=VARIANCE,
            findings=make_findings(),
            correlations=(make_correlation_v14(),),
            hypotheses=(),
            proposal=make_proposal_v16(),
        )


def test_advisory_only_grounding_refused() -> None:
    """V1/V6: sheets-only grounding is never factual; edges are not facts."""
    with pytest.raises(ValidationError, match="FINDING_WITHOUT_GROUNDING"):
        FactualFinding(
            finding_id="FIND-ADV",
            situation_id=SITUATION,
            evidence_ids=(EV_SHEETS,),
            quoted_value="expected 10000",
            source_system="sheets",
            verified_ids=(EV_SHEETS,),
        )
    assert trust_class_for("razorpay") == "AUTHORITATIVE"
    assert trust_class_for("sheets") == "ADVISORY"
    with pytest.raises(ValidationError, match="CORRELATION_AS_FACT"):
        Correlation.model_validate(
            {
                "edge_id": "E",
                "situation_id": SITUATION,
                "edge_refs": [EV_RAZORPAY, EV_LEGACY],
                "edge_label": "CORRELATED_WITH",
                "banner": NON_CAUSAL_BANNER,
                "quoted_value": "+10000",
            }
        )


def test_money_decimal_only() -> None:
    """Money stays Decimal-only: floats refused at every boundary."""
    with pytest.raises(ValidationError, match="AMOUNT_MUST_BE_DECIMAL"):
        ResolutionProposal(
            proposal_id="P",
            situation_id=SITUATION,
            action="REPROCESS_LEGACY_RECORD",
            amount=10000.0,  # type: ignore[arg-type]
            account_code="4812",
            evidence_refs=ALL_AUTHORITATIVE,
            hypothesis_ref="HYP-V15",
            policy_pointer=POLICY,
        )


def test_p602_lifecycle_table_frozen() -> None:
    """P6-02 untouched: the 12-state table gains no UNRESOLVED state."""
    assert set(frozen_lifecycle.ALLOWED_TRANSITIONS) == {
        "DETECTED",
        "TRIAGED",
        "INVESTIGATING",
        "CORRELATED",
        "EXPLAINED",
        "PROPOSED",
        "APPROVED",
        "EXECUTING",
        "VERIFYING",
        "ESCALATED",
        "REJECTED",
        "CLOSED",
    }
    assert "UNRESOLVED" not in frozen_lifecycle.ALLOWED_TRANSITIONS


def test_module_hygiene_no_side_effects() -> None:
    """New code performs no calls, writes, network, or clock reads."""
    root = Path(__file__).resolve().parents[3]
    sources = [
        (root / "finance" / "investigation" / name).read_text()
        for name in ("verdict.py", "proposal.py", "__init__.py")
    ]
    forbidden = [
        "transition_to",
        "openai",
        "anthropic",
        "litellm",
        "langchain",
        "boto3",
        "temporal",
        "httpx",
        "urlopen",
        "datetime.now",
        "utcnow",
        "time.time",
        "smtplib",
        "subprocess",
        "os.system",
    ]
    for source in sources:
        for token in forbidden:
            assert token not in source, token
        assert re.search(r"(?<![A-Za-z0-9_.])print\s*\(", source) is None, "print("
