"""Real LLM provider integration tests (pytest -m llm)."""

import pytest
from dotenv import load_dotenv
from pydantic import BaseModel

from finance.llm.client import LLMClient
from finance.llm.model_router import ModelRouter


class VarianceOutput(BaseModel):
    explanation: str
    root_causes: list[str]
    confidence: str


load_dotenv()


@pytest.fixture
def client() -> LLMClient:
    return LLMClient()


@pytest.fixture
def router() -> ModelRouter:
    return ModelRouter()


@pytest.mark.llm
@pytest.mark.parametrize("provider_name", ["groq", "openrouter", "poolside"])
def test_each_provider_individually(provider_name: str, router: ModelRouter) -> None:
    router._providers = [p for p in router._providers if p.name == provider_name]
    client = LLMClient(router=router)
    result = client.generate(
        system_prompt=(
            'Return ONLY valid JSON: {"explanation": str, "root_causes": [str], '
            '"confidence": str}. No markdown.'
        ),
        user_prompt="Revenue: actual 10.5M, budget 9.3M, variance +1.2M (12.9% favorable).",
        response_model=VarianceOutput,
    )
    assert isinstance(result, VarianceOutput)
    assert result.explanation
    assert len(result.root_causes) >= 1
    assert result.confidence.lower() in ("low", "medium", "high")


@pytest.mark.llm
def test_llm_fallback_chain(router: ModelRouter) -> None:
    class SimpleOutput(BaseModel):
        explanation: str
        confidence: str

    router.record_failure("groq")
    router.record_failure("openrouter")
    client = LLMClient(router=router)
    result = client.generate(
        system_prompt=(
            'Return ONLY valid JSON: {"explanation": str, "confidence": str}. No markdown.'
        ),
        user_prompt="Revenue up 12.9% favorable.",
        response_model=SimpleOutput,
    )
    assert isinstance(result, SimpleOutput)
    assert result.explanation
    assert result.confidence.lower() in ("low", "medium", "high")


@pytest.mark.llm
def test_router_all_healthy(router: ModelRouter) -> None:
    names = [p.name for p in router.list_providers()]
    assert "groq" in names
    assert "openrouter" in names
    assert "poolside" in names


@pytest.mark.llm
def test_llm_telemetry(client: LLMClient) -> None:
    class SimpleOutput(BaseModel):
        explanation: str

    client.generate(
        system_prompt='Return ONLY valid JSON: {"explanation": str}.',
        user_prompt="Say hi.",
        response_model=SimpleOutput,
    )
    stats = client._telemetry.summary()
    assert stats["total_calls"] >= 1
    for _provider, data in stats["by_provider"].items():
        assert data["calls"] >= 0
        assert "avg_latency_ms" in data
        assert "success_rate" in data
