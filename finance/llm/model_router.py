from __future__ import annotations

import os
import time
from typing import Any, ClassVar

from pydantic import BaseModel


class ProviderConfig(BaseModel):
    name: str
    model: str
    base_url: str
    api_key_env: str

    @property
    def api_key(self) -> str:
        return os.environ.get(self.api_key_env, "")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key) and bool(self.base_url)


class ModelRouter:
    _PROVIDER_DEFS: ClassVar[list[dict[str, Any]]] = [
        {
            "name": "groq",
            "api_key_env": "GROQ_API_KEY",
            "base_url_env": "GROQ_BASE_URL",
            "model_env": "GROQ_CHAT_MODEL",
            "default_base_url": "https://api.groq.com/openai/v1",
            "default_model": "llama-3.3-70b-versatile",
        },
        {
            "name": "openrouter",
            "api_key_env": "OPENROUTER_API_KEY",
            "base_url_env": "OPENROUTER_BASE_URL",
            "model_env": "OPENROUTER_CHAT_MODEL",
            "default_base_url": "https://openrouter.ai/api/v1",
            "default_model": "nvidia/nemotron-3-ultra-550b-a55b:free",
        },
        {
            "name": "poolside",
            "api_key_env": "POOLSIDE_API_KEY",
            "base_url_env": "POOLSIDE_BASE_URL",
            "model_env": "POOLSIDE_CHAT_MODEL",
            "default_base_url": "https://inference.poolside.ai/v1",
            "default_model": "poolside/laguna-m.1",
        },
    ]

    def __init__(self, cooldown_minutes: int = 5):
        self.cooldown_minutes = cooldown_minutes
        self._failed_at: dict[str, float] = {}
        self._providers: list[ProviderConfig] = []
        for pdef in self._PROVIDER_DEFS:
            base_url = os.environ.get(pdef["base_url_env"], pdef["default_base_url"])
            model = os.environ.get(pdef["model_env"], pdef["default_model"])
            cfg = ProviderConfig(
                name=pdef["name"],
                model=model,
                base_url=base_url,
                api_key_env=pdef["api_key_env"],
            )
            if cfg.is_configured:
                self._providers.append(cfg)

    def list_providers(self) -> list[ProviderConfig]:
        return list(self._providers)

    def select(self, tasks: list[str] | None = None) -> ProviderConfig | None:
        now = time.time()
        for p in self._providers:
            failed_at = self._failed_at.get(p.name)
            if failed_at is not None:
                elapsed = now - failed_at
                if elapsed < self.cooldown_minutes * 60:
                    continue
                del self._failed_at[p.name]
            return p
        return None

    def record_failure(self, name: str) -> None:
        self._failed_at[name] = time.time()

    def record_success(self, name: str) -> None:
        self._failed_at.pop(name, None)
