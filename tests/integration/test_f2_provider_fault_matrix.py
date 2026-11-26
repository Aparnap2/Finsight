"""F2 contract slice: provider-fault classification and replay-provider typing.

This file retains only the assertions that do NOT depend on the deleted P8
execution runtime (``execute_run`` / ``replay_run`` / ``should_retry``):
the frozen failure-kind taxonomy and the ReplayProvider error typing.
All execution-dependent fault-matrix cases were removed with
``agents/p8_runtime/execution.py``.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict

from agents.p8_runtime import contract as p8_01
from shared.llm.errors import ProviderError
from shared.llm.fake import FakeLLM
from shared.llm.types import InvestigationPrompt


class _JournalMark(BaseModel):
    """Trivial schema used only to journal one FakeLLM provider call."""

    model_config = ConfigDict(extra="forbid")

    marker: str = "ok"


class TestGClassificationFidelity:
    """Frozen taxonomy: every kind maps to its class; retry flags exact."""

    _EXPECTED: dict[p8_01.FailureKind, p8_01.FailureClass] = {
        p8_01.FailureKind.TIMEOUT: p8_01.FailureClass.TRANSIENT,
        p8_01.FailureKind.PROVIDER_UNAVAILABLE: p8_01.FailureClass.TRANSIENT,
        p8_01.FailureKind.RATE_LIMITED: p8_01.FailureClass.TRANSIENT,
        p8_01.FailureKind.MALFORMED_RESPONSE: p8_01.FailureClass.TERMINAL,
        p8_01.FailureKind.INVALID_STRUCTURED_OUTPUT: (p8_01.FailureClass.TERMINAL),
        p8_01.FailureKind.BUDGET_EXHAUSTED: p8_01.FailureClass.TERMINAL,
        p8_01.FailureKind.POLICY_REFUSAL: p8_01.FailureClass.TERMINAL,
        p8_01.FailureKind.SAFETY_INJECTION_REJECTION: (p8_01.FailureClass.TERMINAL),
    }

    def test_g1_every_failure_kind_classifies_to_its_class(self) -> None:
        """Table test over all 8 frozen kinds: exact class per kind."""
        assert set(p8_01.FailureKind) == set(self._EXPECTED)
        for kind, expected in self._EXPECTED.items():
            assert p8_01.classify_failure(kind) is expected, kind

    def test_g2_is_retryable_true_only_for_three_transient_kinds(self) -> None:
        """Retry eligibility: true for exactly TIMEOUT/UNAVAILABLE/RATE_LIMITED."""
        retryable = {k for k in p8_01.FailureKind if p8_01.is_retryable(k)}
        assert retryable == {
            p8_01.FailureKind.TIMEOUT,
            p8_01.FailureKind.PROVIDER_UNAVAILABLE,
            p8_01.FailureKind.RATE_LIMITED,
        }


class TestHReplayProviderAccounting:
    """ReplayProvider double: scripted playback journals without network."""

    def test_h2_replay_provider_error_kind_is_typed(self) -> None:
        """Unscripted FakeLLM failure carries a typed ProviderError only."""
        fake = FakeLLM()
        with pytest.raises(ProviderError):
            fake.generate_structured(InvestigationPrompt(user_prompt="probe"), _JournalMark)
        assert fake.journal[0].success is False
