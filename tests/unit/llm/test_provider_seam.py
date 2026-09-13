"""P4.1 provider-seam tests: conformance, boundary, hygiene, fallback.

All transport is stubbed or monkeypatched. These tests NEVER touch the
network: ``socket.socket`` is disabled for the live-call guard tests and
every Groq interaction goes through an injectable stub or a monkeypatched
``urlopen``.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import logging
import socket
import urllib.error
import urllib.request
from typing import Any

import pytest
from pydantic import BaseModel

from shared.config import get_settings
from shared.llm import (
    CredentialMissingError,
    FakeLLM,
    GroqProvider,
    InvestigationPrompt,
    LLMProvider,
    ModelMetadata,
    ProviderCallLog,
    ProviderError,
    ProviderHealth,
    ProviderUnavailableError,
    SchemaMismatchError,
)


class PlanOut(BaseModel):
    explanation: str
    count: int


class SummaryOut(BaseModel):
    explanation: str


_SENTINEL_KEY = "gsk-test-sentinel-key-abc123xyz"


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> str:
    """Isolate Groq env vars and reset the settings cache."""
    monkeypatch.setenv("GROQ_API_KEY", _SENTINEL_KEY)
    monkeypatch.setenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setenv("GROQ_CHAT_MODEL", "llama-3.3-70b-versatile")
    get_settings.cache_clear()
    yield _SENTINEL_KEY
    get_settings.cache_clear()


@pytest.fixture
def no_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explode on any real socket use."""

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("live socket use forbidden in provider-seam tests")

    monkeypatch.setattr(socket, "socket", _explode)


def _groq_ok_transport(payload_content: dict[str, Any]) -> Any:
    """Build a stub transport returning ``payload_content`` as chat content."""

    def _transport(
        url: str, payload: dict[str, Any], headers: dict[str, str], timeout_s: float
    ) -> dict[str, Any]:
        assert url.endswith("/chat/completions")
        assert payload["model"]
        assert isinstance(payload["messages"], list)
        return {
            "choices": [{"message": {"content": json.dumps(payload_content)}}],
            "model": payload["model"],
        }

    return _transport


def _p3_template_narrative() -> SummaryOut:
    """Deterministic P3-plane template path: zero provider calls."""
    return SummaryOut(explanation="p3-template: reconciled deterministically")


def _investigate_or_fallback(provider: LLMProvider) -> tuple[str, SummaryOut]:
    """Caller-side degraded-mode contract: unhealthy -> P3 template."""
    health = provider.health_check()
    if not health.ok:
        return ("p3-fallback", _p3_template_narrative())
    return ("llm", provider.generate_structured("hi", SummaryOut))


# --- protocol conformance ----------------------------------------------------


def test_protocol_conformance_groq_and_fake(isolated_env: str) -> None:
    """GroqProvider and FakeLLM satisfy the runtime-checkable protocol."""
    groq = GroqProvider(transport=_groq_ok_transport({"explanation": "x"}))
    fake = FakeLLM(scripted={"SummaryOut": {"explanation": "ok"}})
    assert isinstance(groq, LLMProvider)
    assert isinstance(fake, LLMProvider)
    for provider in (groq, fake):
        assert callable(provider.generate_structured)
        assert callable(provider.health_check)
        assert callable(provider.model_metadata)
    sig = inspect.signature(LLMProvider.generate_structured)
    assert list(sig.parameters.keys()) == ["self", "prompt", "response_schema"]


def test_model_metadata_shapes(isolated_env: str) -> None:
    """model_metadata exposes provider/model identity for cost auditing."""
    groq = GroqProvider(transport=_groq_ok_transport({"explanation": "x"}))
    assert groq.model_metadata() == ModelMetadata(provider="groq", model="llama-3.3-70b-versatile")
    fake = FakeLLM(model="fake-test-1")
    assert fake.model_metadata() == ModelMetadata(provider="fake", model="fake-test-1")


def test_boundary_types_are_frozen() -> None:
    """InvestigationPrompt/Health/Metadata/CallLog are frozen dataclasses."""
    for cls in (InvestigationPrompt, ProviderHealth, ModelMetadata, ProviderCallLog):
        assert dataclasses.is_dataclass(cls)
        assert cls.__dataclass_params__.frozen is True
    prompt = InvestigationPrompt(user_prompt="u")
    with pytest.raises(dataclasses.FrozenInstanceError):
        prompt.user_prompt = "mutated"  # type: ignore[misc]


def test_call_log_carries_no_secret_fields() -> None:
    """ProviderCallLog schema has model/cost fields and no secret slots."""
    field_names = {f.name for f in dataclasses.fields(ProviderCallLog)}
    assert {"provider", "model", "success"} <= field_names
    for banned in ("api_key", "apikey", "secret", "token", "authorization", "password"):
        assert banned not in field_names


# --- typed boundary ----------------------------------------------------------


def test_typed_boundary_valid_parses(no_sockets: None, isolated_env: str) -> None:
    """Valid payloads parse into the requested model via both providers."""
    prompt = InvestigationPrompt(user_prompt="explain", system_prompt="be brief")
    groq = GroqProvider(transport=_groq_ok_transport({"explanation": "up", "count": 2}))
    result = groq.generate_structured(prompt, PlanOut)
    assert result == PlanOut(explanation="up", count=2)
    fake = FakeLLM(scripted={"PlanOut": {"explanation": "up", "count": 2}})
    assert fake.generate_structured(prompt, PlanOut) == PlanOut(explanation="up", count=2)
    # Plain-string prompts are also accepted.
    assert fake.generate_structured("hi", PlanOut) == PlanOut(explanation="up", count=2)


def test_typed_boundary_unknown_fields_rejected(no_sockets: None, isolated_env: str) -> None:
    """Unknown fields raise SchemaMismatchError even when extra would be allowed."""
    groq = GroqProvider(
        transport=_groq_ok_transport({"explanation": "up", "count": 1, "rogue": True})
    )
    with pytest.raises(SchemaMismatchError):
        groq.generate_structured("hi", PlanOut)
    fake = FakeLLM(scripted={"PlanOut": {"explanation": "up", "count": 1, "rogue": 1}})
    with pytest.raises(SchemaMismatchError):
        fake.generate_structured("hi", PlanOut)


def test_typed_boundary_wrong_types_rejected(no_sockets: None, isolated_env: str) -> None:
    """Wrong field types raise SchemaMismatchError (strict validation)."""
    groq = GroqProvider(transport=_groq_ok_transport({"explanation": 123, "count": "two"}))
    with pytest.raises(SchemaMismatchError):
        groq.generate_structured("hi", PlanOut)
    fake = FakeLLM(scripted={"PlanOut": {"explanation": "ok", "count": "not-an-int"}})
    with pytest.raises(SchemaMismatchError):
        fake.generate_structured("hi", PlanOut)


def test_typed_boundary_malformed_json_rejected(no_sockets: None, isolated_env: str) -> None:
    """Non-JSON content surfaces as SchemaMismatchError, not a raw decode error."""

    def _bad_transport(
        url: str, payload: dict[str, Any], headers: dict[str, str], timeout_s: float
    ) -> dict[str, Any]:
        return {"choices": [{"message": {"content": "not json"}}]}

    groq = GroqProvider(transport=_bad_transport)
    with pytest.raises(SchemaMismatchError):
        groq.generate_structured("hi", PlanOut)


# --- credential leakage ------------------------------------------------------


def test_credential_hygiene_no_leak(
    no_sockets: None, isolated_env: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Key sentinel appears in no repr, error, log, journal, or metadata."""
    sentinel = isolated_env
    assert sentinel == "gsk-test-sentinel-key-abc123xyz"

    def _timeout_transport(
        url: str, payload: dict[str, Any], headers: dict[str, str], timeout_s: float
    ) -> dict[str, Any]:
        raise TimeoutError("simulated timeout")

    groq = GroqProvider(transport=_timeout_transport)
    artifacts: list[str] = [repr(groq)]
    with caplog.at_level(logging.DEBUG):
        try:
            groq.generate_structured("hello", SummaryOut)
        except ProviderUnavailableError as exc:
            artifacts.append(str(exc))
            artifacts.append(repr(exc))
        health = groq.health_check()
        artifacts.append(str(health))
        artifacts.append(repr(health))
        artifacts.append(str(groq.model_metadata()))
        for entry in groq.call_log:
            artifacts.append(str(entry))
            artifacts.append(repr(entry))
        artifacts.append(caplog.text)

    fake = FakeLLM(scripted={"SummaryOut": {"explanation": "ok"}})
    artifacts.append(repr(fake))
    artifacts.append(str(fake.model_metadata()))
    for entry in fake.journal:
        artifacts.append(str(entry))
    try:
        GroqProvider(api_key="").generate_structured("hi", SummaryOut)
    except CredentialMissingError as exc:
        artifacts.append(str(exc))
    for artifact in artifacts:
        assert sentinel not in artifact


def test_missing_credential_raises_without_storing(
    monkeypatch: pytest.MonkeyPatch, no_sockets: None
) -> None:
    """Empty env key raises CredentialMissingError; repr stays key-free."""
    monkeypatch.setenv("GROQ_API_KEY", "")
    get_settings.cache_clear()
    try:
        provider = GroqProvider(transport=_groq_ok_transport({"explanation": "x"}))
        with pytest.raises(CredentialMissingError):
            provider.generate_structured("hi", SummaryOut)
        assert "GROQ_API_KEY" not in repr(provider)
        assert "gsk" not in repr(provider)
        health = provider.health_check()
        assert health.ok is False
    finally:
        get_settings.cache_clear()


# --- failure behavior --------------------------------------------------------


def test_timeout_maps_to_provider_unavailable(no_sockets: None, isolated_env: str) -> None:
    """Transport timeouts surface as ProviderUnavailableError after retries."""

    def _timeout_transport(
        url: str, payload: dict[str, Any], headers: dict[str, str], timeout_s: float
    ) -> dict[str, Any]:
        raise TimeoutError("boom")

    provider = GroqProvider(transport=_timeout_transport, max_retries=3)
    with pytest.raises(ProviderUnavailableError):
        provider.generate_structured("hi", SummaryOut)
    assert provider.call_log[-1].success is False
    assert provider.call_log[-1].error_kind == "TimeoutError"


def test_http_5xx_maps_to_provider_unavailable(no_sockets: None, isolated_env: str) -> None:
    """HTTP 500 failures surface as ProviderUnavailableError."""

    def _failing_transport(
        url: str, payload: dict[str, Any], headers: dict[str, str], timeout_s: float
    ) -> dict[str, Any]:
        raise urllib.error.HTTPError(url, 500, "Internal Error", {}, None)

    provider = GroqProvider(transport=_failing_transport)
    with pytest.raises(ProviderUnavailableError):
        provider.generate_structured("hi", SummaryOut)


def test_retries_capped_at_three(no_sockets: None, isolated_env: str) -> None:
    """Retries never exceed 3 total attempts."""
    calls = {"n": 0}

    def _counting_transport(
        url: str, payload: dict[str, Any], headers: dict[str, str], timeout_s: float
    ) -> dict[str, Any]:
        calls["n"] += 1
        raise TimeoutError("down")

    provider = GroqProvider(transport=_counting_transport, max_retries=99)
    with pytest.raises(ProviderUnavailableError):
        provider.generate_structured("hi", SummaryOut)
    assert calls["n"] == 3


def test_health_unhealthy_is_caller_visible_degraded() -> None:
    """health_check False routes the caller to the P3-template path."""
    fake = FakeLLM(scripted={"SummaryOut": {"explanation": "should-not-be-used"}}, healthy=False)
    mode, output = _investigate_or_fallback(fake)
    assert mode == "p3-fallback"
    assert output == SummaryOut(explanation="p3-template: reconciled deterministically")
    assert fake.journal == []


def test_scripted_failure_surfaces_and_journals() -> None:
    """FakeLLM scripted failures raise and record error_kind."""
    fake = FakeLLM(failures={"SummaryOut": ProviderUnavailableError("fake down")})
    with pytest.raises(ProviderUnavailableError):
        fake.generate_structured("hi", SummaryOut)
    assert len(fake.journal) == 1
    assert fake.journal[0].success is False
    assert fake.journal[0].error_kind == "ProviderUnavailableError"


# --- fallback contract -------------------------------------------------------


def test_fallback_contract_zero_provider_calls() -> None:
    """P3-template path produces output with an empty provider journal."""
    fake = FakeLLM(healthy=False)
    mode, output = _investigate_or_fallback(fake)
    assert mode == "p3-fallback"
    assert output.explanation.startswith("p3-template")
    assert fake.journal == []
    assert fake.call_journal == []


def test_healthy_fake_uses_provider_journal() -> None:
    """Healthy path records exactly one successful journal entry."""
    fake = FakeLLM(scripted={"SummaryOut": {"explanation": "llm says hi"}})
    mode, output = _investigate_or_fallback(fake)
    assert mode == "llm"
    assert output == SummaryOut(explanation="llm says hi")
    assert len(fake.journal) == 1
    assert fake.journal[0].success is True


# --- live-call guard ---------------------------------------------------------


def test_groq_uses_only_injected_transport(
    no_sockets: None, isolated_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stubbed urlopen proves Groq calls flow through the seam, not sockets."""

    def _forbidden_urlopen(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("default urllib transport must not run in this test")

    monkeypatch.setattr(urllib.request, "urlopen", _forbidden_urlopen)
    provider = GroqProvider(transport=_groq_ok_transport({"explanation": "stubbed"}))
    result = provider.generate_structured("hi", SummaryOut)
    assert result == SummaryOut(explanation="stubbed")


def test_fake_performs_no_network(monkeypatch: pytest.MonkeyPatch, no_sockets: None) -> None:
    """FakeLLM works with urlopen disabled (deterministic, no network)."""

    def _forbidden_urlopen(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("FakeLLM must never touch the network")

    monkeypatch.setattr(urllib.request, "urlopen", _forbidden_urlopen)
    fake = FakeLLM(scripted={"SummaryOut": {"explanation": "local"}})
    assert fake.generate_structured("hi", SummaryOut).explanation == "local"
    assert fake.health_check().ok is True


def test_groq_health_probe_uses_monkeypatched_urlopen(
    no_sockets: None, isolated_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Health probe goes through urlopen (monkeypatched) and reports ok."""

    class _FakeResponse:
        status = 200

        def __enter__(self) -> _FakeResponse:
            return self

        def __exit__(self, *args: Any) -> bool:
            return False

    seen: dict[str, Any] = {}

    def _ok_urlopen(request: Any, timeout: Any = None) -> _FakeResponse:
        seen["url"] = request.full_url
        return _FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", _ok_urlopen)
    provider = GroqProvider()
    health = provider.health_check()
    assert health.ok is True
    assert seen["url"].endswith("/models")


def test_groq_module_imports_no_vendor_sdk() -> None:
    """Provider layer uses thin direct transport only (no agent frameworks)."""
    import shared.llm.groq as groq_module

    source = inspect.getsource(groq_module)
    assert "import socket" not in source
    assert "from groq" not in source
    assert "import groq" not in source
    assert "langchain" not in source.lower()
    assert "litellm" not in source.lower()


def test_error_hierarchy() -> None:
    """ProviderUnavailableError/SchemaMismatchError/CredentialMissingError extend ProviderError."""
    assert issubclass(ProviderUnavailableError, ProviderError)
    assert issubclass(SchemaMismatchError, ProviderError)
    assert issubclass(CredentialMissingError, ProviderError)
    assert isinstance(ProviderHealth(ok=False, reason="x").reason, str)
