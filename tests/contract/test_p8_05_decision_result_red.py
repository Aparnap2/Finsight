"""RED P8-05 decision result — discriminated APPROVE/ABSTAIN contract.

Gate: abstention must be a first-class typed runtime outcome, and the
four result classes must be provably distinct:

- valid APPROVE  → ApproveDecision (summary/findings/evidence)
- valid ABSTAIN  → AbstainDecision (reason/explanation/missing evidence)
- malformed model output → InvalidStructuredOutputError, never ABSTAIN
- provider/transport failure → ProviderError, never a decision

Leakage rules under test: malformed JSON is never coerced into ABSTAIN;
ABSTAIN-shaped input is rejected by validate_raw_output (it cannot enter
the approval path); refusal heuristics are not the definition of
abstention. Pure pytest, no network, deterministic.
"""

from __future__ import annotations

import pytest

from agents.p8_runtime import contract as p8_01

RUN_ID = "run-p805-001"
FIXED_AT = __import__("datetime").datetime(2026, 10, 5, 12, 0, 0)


def _raw(text: str) -> p8_01.RawModelOutput:
    return p8_01.RawModelOutput(run_id=RUN_ID, text=text, received_at=FIXED_AT)


class TestApproveDecision:
    def test_valid_approve_returns_typed_decision(self) -> None:
        result = p8_01.validate_decision_output(
            _raw('{"outcome": "approve", "summary": "s", "findings": ["f"]}')
        )
        assert result.outcome == p8_01.DecisionOutcome.APPROVE
        assert result.summary == "s"
        assert result.findings == ["f"]

    def test_approve_accepts_evidence_ids(self) -> None:
        result = p8_01.validate_decision_output(
            _raw('{"outcome": "approve", "summary": "s", "findings": [], "evidence_ids": ["ev-1"]}')
        )
        assert result.evidence_ids == ["ev-1"]

    def test_approve_rejects_unknown_keys(self) -> None:
        with pytest.raises(p8_01.InvalidStructuredOutputError):
            p8_01.validate_decision_output(
                _raw('{"outcome": "approve", "summary": "s", "findings": [], "extra": 1}')
            )

    def test_approve_rejects_empty_summary(self) -> None:
        with pytest.raises(p8_01.InvalidStructuredOutputError):
            p8_01.validate_decision_output(
                _raw('{"outcome": "approve", "summary": "", "findings": []}')
            )

    def test_approve_rejects_non_string_findings(self) -> None:
        with pytest.raises(p8_01.InvalidStructuredOutputError):
            p8_01.validate_decision_output(
                _raw('{"outcome": "approve", "summary": "s", "findings": [1]}')
            )


class TestAbstainDecision:
    def test_valid_abstain_returns_typed_decision(self) -> None:
        result = p8_01.validate_decision_output(
            _raw(
                '{"outcome": "abstain", '
                '"reason_code": "insufficient_evidence", '
                '"explanation": "no invoice date", '
                '"missing_evidence": ["invoice_date"]}'
            )
        )
        assert result.outcome == p8_01.DecisionOutcome.ABSTAIN
        assert result.reason_code == p8_01.AbstainReason.INSUFFICIENT_EVIDENCE
        assert result.explanation == "no invoice date"
        assert result.missing_evidence == ["invoice_date"]

    def test_abstain_accepts_all_reason_codes(self) -> None:
        for code in (
            "insufficient_evidence",
            "ambiguous_evidence",
            "policy_refusal",
            "out_of_scope",
        ):
            result = p8_01.validate_decision_output(
                _raw(
                    '{"outcome": "abstain", "reason_code": "'
                    + code
                    + '", "explanation": "why", "missing_evidence": []}'
                )
            )
            assert result.reason_code is not None
            assert result.reason_code.value == code

    def test_abstain_rejects_unknown_reason_code(self) -> None:
        with pytest.raises(p8_01.InvalidStructuredOutputError):
            p8_01.validate_decision_output(
                _raw(
                    '{"outcome": "abstain", "reason_code": "vibes", '
                    '"explanation": "why", "missing_evidence": []}'
                )
            )

    def test_abstain_rejects_empty_explanation(self) -> None:
        with pytest.raises(p8_01.InvalidStructuredOutputError):
            p8_01.validate_decision_output(
                _raw(
                    '{"outcome": "abstain", '
                    '"reason_code": "insufficient_evidence", '
                    '"explanation": "", "missing_evidence": []}'
                )
            )

    def test_abstain_carries_no_approval_content(self) -> None:
        result = p8_01.validate_decision_output(
            _raw(
                '{"outcome": "abstain", '
                '"reason_code": "policy_refusal", '
                '"explanation": "cannot approve refunds", '
                '"missing_evidence": []}'
            )
        )
        assert result.summary == ""
        assert result.findings == []
        assert result.evidence_ids == []
        assert result.reason_code == p8_01.AbstainReason.POLICY_REFUSAL


class TestMalformedNeverBecomesAbstain:
    def test_non_json_is_not_abstain(self) -> None:
        with pytest.raises(p8_01.InvalidStructuredOutputError):
            p8_01.validate_decision_output(_raw("I cannot approve this refund."))

    def test_empty_text_is_not_abstain(self) -> None:
        with pytest.raises(p8_01.InvalidStructuredOutputError):
            p8_01.validate_decision_output(_raw(""))

    def test_non_object_json_is_not_abstain(self) -> None:
        with pytest.raises(p8_01.InvalidStructuredOutputError):
            p8_01.validate_decision_output(_raw('["abstain"]'))

    def test_missing_outcome_is_not_abstain(self) -> None:
        with pytest.raises(p8_01.InvalidStructuredOutputError):
            p8_01.validate_decision_output(
                _raw('{"reason_code": "policy_refusal", "explanation": "x"}')
            )

    def test_unknown_outcome_is_not_abstain(self) -> None:
        with pytest.raises(p8_01.InvalidStructuredOutputError):
            p8_01.validate_decision_output(_raw('{"outcome": "maybe", "summary": "s"}'))

    def test_refusal_text_with_json_shape_words_is_not_abstain(self) -> None:
        with pytest.raises(p8_01.InvalidStructuredOutputError):
            p8_01.validate_decision_output(
                _raw('{"text": "I abstain because policy_refusal reasons"}')
            )


class TestAbstainCannotEnterApprovalPath:
    def test_abstain_shaped_input_rejected_by_legacy_gate(self) -> None:
        with pytest.raises(p8_01.InvalidStructuredOutputError):
            p8_01.validate_raw_output(
                _raw(
                    '{"outcome": "abstain", '
                    '"reason_code": "policy_refusal", '
                    '"explanation": "cannot approve refunds", '
                    '"missing_evidence": []}'
                )
            )

    def test_decision_and_legacy_validators_agree_on_approve(self) -> None:
        text = '{"outcome": "approve", "summary": "s", "findings": ["f"]}'
        decision = p8_01.validate_decision_output(_raw(text))
        legacy = p8_01.validate_raw_output(
            p8_01.RawModelOutput(
                run_id=RUN_ID, text='{"summary": "s", "findings": ["f"]}', received_at=FIXED_AT
            )
        )
        assert decision.summary == legacy.summary
        assert decision.findings == legacy.findings
