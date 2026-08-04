from __future__ import annotations

from datetime import datetime
from typing import Any


class Telemetry:
    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []

    def record(
        self,
        provider: str,
        model: str,
        prompt_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        success: bool,
    ) -> None:
        self._records.append({
            "provider": provider,
            "model": model,
            "prompt_name": prompt_name,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "latency_ms": latency_ms,
            "success": success,
            "timestamp": datetime.now(),
        })

    def summary(self) -> dict[str, Any]:
        total_calls = len(self._records)
        if total_calls == 0:
            return {
                "total_calls": 0,
                "total_tokens": 0,
                "success_rate": 0.0,
                "avg_latency_ms": 0.0,
                "by_provider": {},
            }

        total_tokens = sum(r["prompt_tokens"] + r["completion_tokens"] for r in self._records)
        successes = sum(1 for r in self._records if r["success"])
        avg_latency = sum(r["latency_ms"] for r in self._records) / total_calls

        by_provider: dict[str, dict[str, Any]] = {}
        for r in self._records:
            p = r["provider"]
            if p not in by_provider:
                by_provider[p] = {
                    "calls": 0,
                    "tokens": 0,
                    "avg_latency_ms": 0.0,
                    "success_rate": 0.0,
                }
            by_provider[p]["calls"] += 1
            by_provider[p]["tokens"] += r["prompt_tokens"] + r["completion_tokens"]

        for p, stats in by_provider.items():
            prov_records = [r for r in self._records if r["provider"] == p]
            stats["avg_latency_ms"] = sum(r["latency_ms"] for r in prov_records) / len(prov_records)
            prov_successes = sum(1 for r in prov_records if r["success"])
            stats["success_rate"] = prov_successes / len(prov_records)

        return {
            "total_calls": total_calls,
            "total_tokens": total_tokens,
            "success_rate": successes / total_calls,
            "avg_latency_ms": avg_latency,
            "by_provider": by_provider,
        }
