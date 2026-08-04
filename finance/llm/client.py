from __future__ import annotations

from pydantic import BaseModel

from finance.llm.model_router import ModelRouter
from finance.llm.structured_generation import StructuredGeneration
from finance.llm.telemetry import Telemetry


class LLMClient:
    def __init__(
        self,
        router: ModelRouter | None = None,
        telemetry: Telemetry | None = None,
    ):
        self._router = router or ModelRouter()
        self._telemetry = telemetry or Telemetry()

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
    ) -> BaseModel:
        last_error: Exception | None = None
        while True:
            provider = self._router.select()
            if provider is None:
                raise last_error or RuntimeError("No providers available")

            gen = StructuredGeneration(
                api_key=provider.api_key,
                base_url=provider.base_url,
                model=provider.model,
            )

            import time
            start = time.monotonic()
            try:
                result = gen.generate(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_model=response_model,
                )
                latency_ms = int((time.monotonic() - start) * 1000)
                self._telemetry.record(
                    provider=provider.name,
                    model=provider.model,
                    prompt_name=response_model.__name__,
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=latency_ms,
                    success=True,
                )
                self._router.record_success(provider.name)
                return result
            except Exception as e:
                latency_ms = int((time.monotonic() - start) * 1000)
                self._telemetry.record(
                    provider=provider.name,
                    model=provider.model,
                    prompt_name=response_model.__name__,
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=latency_ms,
                    success=False,
                )
                self._router.record_failure(provider.name)
                last_error = e
