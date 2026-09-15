from typing import Any

from openai import OpenAI

from shared.config import get_settings


class LLMClient:
    """Routes LLM calls through OpenAI SDK with Poolside, Groq, and OpenRouter."""

    def __init__(self, model: str | None = None):
        self.settings = get_settings()
        self.model = model or self.settings.default_llm_model
        self._client: OpenAI | None = None
        self._provider = "poolside"

    def _get_client(self) -> OpenAI:
        if self._client is not None:
            return self._client

        if self.settings.poolside_api_key:
            self._client = OpenAI(
                api_key=self.settings.poolside_api_key,
                base_url=self.settings.poolside_base_url,
            )
            self._provider = "poolside"
            self.model = self.settings.poolside_chat_model
        elif self.settings.groq_api_key:
            self._client = OpenAI(
                api_key=self.settings.groq_api_key,
                base_url=self.settings.groq_base_url,
            )
            self._provider = "groq"
            self.model = self.settings.groq_chat_model
        elif self.settings.openrouter_api_key:
            self._client = OpenAI(
                api_key=self.settings.openrouter_api_key,
                base_url=self.settings.openrouter_base_url,
            )
            self._provider = "openrouter"
            self.model = self.settings.openrouter_chat_model
        else:
            raise RuntimeError("No LLM API key configured (poolside/groq/openrouter)")

        return self._client

    def generate(
        self, prompt: str, max_tokens: int = 512, temperature: float = 0.3
    ) -> str:
        client = self._get_client()
        request_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if self._provider == "poolside":
            request_kwargs["extra_body"] = {
                "chat_template_kwargs": {"enable_thinking": False}
            }

        response = client.chat.completions.create(**request_kwargs)
        return response.choices[0].message.content or ""

    @property
    def provider(self) -> str:
        return self._provider
