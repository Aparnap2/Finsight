from __future__ import annotations

import json
import time
from typing import Any

import httpx
from pydantic import BaseModel


class StructuredGeneration:
    def __init__(self, api_key: str, base_url: str, model: str = "default"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        max_retries: int = 3,
    ) -> BaseModel:
        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
                return self._call(system_prompt, user_prompt, response_model)
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        raise last_error or RuntimeError("Generation failed after retries")

    def _call(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
    ) -> BaseModel:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )
            resp.raise_for_status()
            body = resp.json()

        content = body["choices"][0]["message"]["content"]
        parsed = self._extract_json(content)
        if parsed is None:
            raise ValueError(f"LLM returned invalid JSON: {content[:200]}")
        return response_model.model_validate(parsed)

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            start = 1 if lines[0].startswith("```") else 0
            end = -1 if lines[-1].strip().startswith("```") else len(lines)
            text = "\n".join(lines[start:end]).strip()
        try:
            parsed: Any = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
