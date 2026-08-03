"""TDD tests for Phase 6 — LLM Runtime.

Multi-provider support with automatic fallback (Groq → OpenRouter → Poolside).
All three use OpenAI-compatible APIs. Tests mock at the HTTP level.
"""
from __future__ import annotations

import os
import pytest
from pydantic import BaseModel


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _set_env():
    """Set env vars for all tests so ModelRouter finds providers."""
    old = {}
    for k in ("GROQ_API_KEY", "GROQ_BASE_URL", "GROQ_CHAT_MODEL",
              "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "OPENROUTER_CHAT_MODEL",
              "POOLSIDE_API_KEY", "POOLSIDE_BASE_URL", "POOLSIDE_CHAT_MODEL"):
        old[k] = os.environ.get(k)
    os.environ["GROQ_API_KEY"] = "gsk-test-key"
    os.environ["GROQ_BASE_URL"] = "https://api.groq.com/openai/v1"
    os.environ["GROQ_CHAT_MODEL"] = "llama-3.3-70b-versatile"
    os.environ["OPENROUTER_API_KEY"] = "sk-or-test-key"
    os.environ["OPENROUTER_BASE_URL"] = "https://openrouter.ai/api/v1"
    os.environ["OPENROUTER_CHAT_MODEL"] = "meta-llama/llama-3.1-8b-instruct:free"
    os.environ["POOLSIDE_API_KEY"] = "sky-test-key"
    os.environ["POOLSIDE_BASE_URL"] = "https://inference.poolside.ai/v1"
    os.environ["POOLSIDE_CHAT_MODEL"] = "poolside/laguna-m.1"
    yield
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# ── Model Router ─────────────────────────────────────────────────────────────


class TestModelRouter:
    def test_router_has_configured_providers(self):
        from finance.llm.model_router import ModelRouter
        router = ModelRouter()
        providers = router.list_providers()
        assert len(providers) > 0

    def test_router_selects_preferred_provider(self):
        from finance.llm.model_router import ModelRouter
        router = ModelRouter()
        provider = router.select(tasks=["analysis"])
        assert provider is not None
        assert hasattr(provider, "name")

    def test_router_falls_back_on_provider_failure(self):
        from finance.llm.model_router import ModelRouter
        router = ModelRouter()
        provider = router.select(tasks=["analysis"])
        router.record_failure(provider.name)
        fallback = router.select(tasks=["analysis"])
        assert fallback is not None
        assert fallback.name != provider.name

    def test_router_returns_none_when_all_fail(self):
        from finance.llm.model_router import ModelRouter
        router = ModelRouter()
        for _ in range(6):
            p = router.select(tasks=["analysis"])
            if p is None:
                break
            router.record_failure(p.name)
        last = router.select(tasks=["analysis"])
        assert last is None

    def test_router_recovers_after_cooldown(self):
        from finance.llm.model_router import ModelRouter
        router = ModelRouter(cooldown_minutes=0)
        p1 = router.select(tasks=["analysis"])
        router.record_failure(p1.name)
        recovered = router.select(tasks=["analysis"])
        assert recovered is not None

    def test_model_router_config(self):
        from finance.llm.model_router import ProviderConfig
        cfg = ProviderConfig(
            name="test",
            model="test-model",
            base_url="https://test.example.com/v1",
            api_key_env="TEST_KEY",
        )
        assert cfg.name == "test"
        assert cfg.model == "test-model"


# ── Structured Generation ───────────────────────────────────────────────────


class TestStructuredGeneration:
    def test_generate_returns_typed_output(self, httpx_mock):
        from finance.llm.structured_generation import StructuredGeneration

        class TestOutput(BaseModel):
            summary: str
            confidence: str

        httpx_mock.add_response(
            url="https://api.test.com/v1/chat/completions",
            method="POST",
            json={
                "choices": [{
                    "message": {
                        "content": '{"summary": "Revenue up 10%", "confidence": "high"}',
                    },
                }],
                "usage": {"prompt_tokens": 50, "completion_tokens": 20},
            },
        )

        gen = StructuredGeneration(api_key="test", base_url="https://api.test.com/v1")
        result = gen.generate(
            system_prompt="Analyze this variance.",
            user_prompt="Revenue is up 10%.",
            response_model=TestOutput,
        )
        assert isinstance(result, TestOutput)
        assert result.summary == "Revenue up 10%"
        assert result.confidence == "high"

    def test_generate_retries_on_failure(self, httpx_mock):
        from finance.llm.structured_generation import StructuredGeneration

        class TestOutput(BaseModel):
            result: str

        httpx_mock.add_response(
            url="https://api.test.com/v1/chat/completions",
            method="POST",
            status_code=500,
            json={"error": "Internal error"},
        )
        httpx_mock.add_response(
            url="https://api.test.com/v1/chat/completions",
            method="POST",
            json={
                "choices": [{"message": {"content": '{"result": "success"}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

        gen = StructuredGeneration(api_key="test", base_url="https://api.test.com/v1")
        result = gen.generate(
            system_prompt="Test.",
            user_prompt="Test.",
            response_model=TestOutput,
            max_retries=2,
        )
        assert result.result == "success"

    def test_generate_raises_on_invalid_json(self, httpx_mock):
        from finance.llm.structured_generation import StructuredGeneration

        class TestOutput(BaseModel):
            value: str

        httpx_mock.add_response(
            url="https://api.test.com/v1/chat/completions",
            method="POST",
            json={
                "choices": [{"message": {"content": "not valid json"}}],
            },
        )

        gen = StructuredGeneration(api_key="test", base_url="https://api.test.com/v1")
        with pytest.raises(Exception, match="JSON|valid"):
            gen.generate(
                system_prompt="Test.",
                user_prompt="Test.",
                response_model=TestOutput,
                max_retries=1,
            )

    def test_generate_exhausts_retries(self, httpx_mock):
        from finance.llm.structured_generation import StructuredGeneration

        class TestOutput(BaseModel):
            value: str

        httpx_mock.add_response(
            url="https://api.test.com/v1/chat/completions",
            method="POST",
            status_code=500,
            json={"error": "Error"},
            is_reusable=True,
        )

        gen = StructuredGeneration(api_key="test", base_url="https://api.test.com/v1")
        with pytest.raises(Exception):
            gen.generate(
                system_prompt="Test.",
                user_prompt="Test.",
                response_model=TestOutput,
                max_retries=2,
            )


# ── Response Validator ───────────────────────────────────────────────────────


class TestResponseValidator:
    def test_validate_valid_output(self):
        from finance.llm.response_validator import ResponseValidator

        class TestOutput(BaseModel):
            summary: str
            confidence: str

        validator = ResponseValidator()
        result = validator.validate(
            output=TestOutput(summary="Good quarter.", confidence="high"),
            expected_schema=TestOutput,
        )
        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_validate_missing_field(self):
        from finance.llm.response_validator import ResponseValidator

        class TestOutput(BaseModel):
            summary: str
            confidence: str
            evidence_ids: list[str]

        validator = ResponseValidator()
        result = validator.validate(
            output=TestOutput(summary="Test", confidence="high", evidence_ids=[]),
            expected_schema=TestOutput,
        )
        assert result.is_valid is True

    def test_validate_evidence_requirement(self):
        from finance.llm.response_validator import ResponseValidator

        validator = ResponseValidator()
        result = validator.validate_evidence(
            claim="Revenue increased 10%",
            evidence_ids=[],
            min_evidence=1,
        )
        assert result.is_valid is False
        assert "evidence" in str(result.errors).lower()

    def test_validate_evidence_passes_with_sources(self):
        from finance.llm.response_validator import ResponseValidator

        validator = ResponseValidator()
        result = validator.validate_evidence(
            claim="Revenue increased 10% due to volume.",
            evidence_ids=["var_4010", "kpi_revenue_growth"],
            min_evidence=1,
        )
        assert result.is_valid is True


# ── Telemetry ────────────────────────────────────────────────────────────────


class TestTelemetry:
    def test_record_completion(self):
        from finance.llm.telemetry import Telemetry
        t = Telemetry()
        t.record(
            provider="groq",
            model="llama-3.3-70b",
            prompt_name="variance_analysis",
            prompt_tokens=150,
            completion_tokens=45,
            latency_ms=1200,
            success=True,
        )
        stats = t.summary()
        assert stats["total_calls"] == 1
        assert stats["total_tokens"] == 195

    def test_multiple_records(self):
        from finance.llm.telemetry import Telemetry
        t = Telemetry()
        for _ in range(3):
            t.record(
                provider="groq",
                model="llama-3.3-70b",
                prompt_name="test",
                prompt_tokens=100,
                completion_tokens=20,
                latency_ms=500,
                success=True,
            )
        t.record(
            provider="openrouter",
            model="llama-3.1-8b",
            prompt_name="test",
            prompt_tokens=50,
            completion_tokens=10,
            latency_ms=800,
            success=False,
        )
        stats = t.summary()
        assert stats["total_calls"] == 4
        assert stats["total_tokens"] == 420
        assert stats["success_rate"] == 0.75

    def test_per_provider_breakdown(self):
        from finance.llm.telemetry import Telemetry
        t = Telemetry()
        t.record(provider="groq", model="m1", prompt_name="t", prompt_tokens=100, completion_tokens=20, latency_ms=500, success=True)
        t.record(provider="poolside", model="m2", prompt_name="t", prompt_tokens=200, completion_tokens=40, latency_ms=1000, success=True)
        stats = t.summary()
        assert "groq" in stats["by_provider"]
        assert "poolside" in stats["by_provider"]
        assert stats["by_provider"]["groq"]["calls"] == 1
        assert stats["by_provider"]["poolside"]["calls"] == 1


# ── Unified Client ───────────────────────────────────────────────────────────


class TestLLMClient:
    def test_client_generate_returns_typed_output(self, httpx_mock):
        from finance.llm.client import LLMClient
        from pydantic import BaseModel

        class TestOutput(BaseModel):
            result: str

        httpx_mock.add_response(
            url="https://api.groq.com/openai/v1/chat/completions",
            method="POST",
            json={
                "choices": [{"message": {"content": '{"result": "success"}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

        client = LLMClient()
        result = client.generate(
            system_prompt="Test.",
            user_prompt="Test.",
            response_model=TestOutput,
        )
        assert isinstance(result, TestOutput)
        assert result.result == "success"

    def test_client_falls_back_on_provider_error(self, httpx_mock):
        from finance.llm.client import LLMClient
        from pydantic import BaseModel

        class TestOutput(BaseModel):
            result: str

        httpx_mock.add_response(
            url="https://api.groq.com/openai/v1/chat/completions",
            method="POST",
            status_code=500,
            json={"error": "Server error"},
            is_reusable=True,
        )
        httpx_mock.add_response(
            url="https://openrouter.ai/api/v1/chat/completions",
            method="POST",
            json={
                "choices": [{"message": {"content": '{"result": "fallback_worked"}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

        client = LLMClient()
        result = client.generate(
            system_prompt="Test.",
            user_prompt="Test.",
            response_model=TestOutput,
        )
        assert result.result == "fallback_worked"
