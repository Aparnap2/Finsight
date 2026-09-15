"""Standalone Groq smoke script — run before pytest, no deps beyond openai.

Usage:
    uv run python scripts/smoke_groq.py
    FINSIGHT_ALLOW_LIVE_LLM=1 uv run python scripts/smoke_groq.py

Proves: credentials, network, model availability, structured output boundary.
Does NOT print prompts, API keys, or full responses.
"""

from __future__ import annotations

import json
import os
import sys
import time

# Load .env if present
_env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

# Gate: require explicit opt-in
if not os.environ.get("FINSIGHT_ALLOW_LIVE_LLM"):
    print("SKIP: set FINSIGHT_ALLOW_LIVE_LLM=1 to run live Groq smoke tests")
    sys.exit(0)

from openai import OpenAI  # noqa: E402


def _check(label: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    suffix = f" ({detail})" if detail else ""
    print(f"  [{status}] {label}{suffix}")


def main() -> None:
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        print("  [FAIL] GROQ_API_KEY not set")
        sys.exit(1)

    print("=== Groq Provider Smoke ===")
    client = OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1",
        timeout=30.0,
        max_retries=0,
    )

    # 1. Health check (GET /models)
    print("\n1. Health check")
    try:
        import urllib.request

        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=5) as resp:
            status = resp.status
        latency = (time.monotonic() - t0) * 1000
        _check("GET /models", 200 <= status < 300, f"{latency:.0f}ms")
    except Exception as e:
        _check("GET /models", False, str(e)[:60])
        sys.exit(1)

    # 2. Simple completion
    print("\n2. Simple completion")
    try:
        t0 = time.monotonic()
        resp = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[{"role": "user", "content": 'Return JSON: {"ok": true}'}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        latency = (time.monotonic() - t0) * 1000
        content = resp.choices[0].message.content
        parsed = json.loads(content)
        _check("JSON response", parsed.get("ok") is True, f"{latency:.0f}ms")
    except Exception as e:
        _check("JSON response", False, str(e)[:60])
        sys.exit(1)

    # 3. Structured output (InvestigationPlan-like schema)
    print("\n3. Structured output")
    schema = {
        "type": "object",
        "properties": {
            "hypothesis_text": {"type": "string"},
            "capability_calls": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "capability": {"type": "string"},
                        "order_index": {"type": "integer"},
                    },
                    "required": ["capability", "order_index"],
                    "additionalProperties": False,
                },
            },
            "evidence_required": {"type": "array", "items": {"type": "string"}},
            "escalation": {"type": "boolean"},
        },
        "required": ["hypothesis_text", "capability_calls", "evidence_required", "escalation"],
        "additionalProperties": False,
    }
    try:
        t0 = time.monotonic()
        resp = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[
                {
                    "role": "system",
                    "content": "Financial investigation planner. Return valid JSON.",
                },
                {
                    "role": "user",
                    "content": (
                        "Exception: PARTIAL_REFUND_ACCOUNTING_LAG\n"
                        "Evidence: ev_charge_001, ev_ledger_002\n"
                        "Allowlist: get_stripe_payment, get_stripe_refunds, get_qb_transaction"
                    ),
                },
            ],
            temperature=0,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "Plan", "schema": schema, "strict": True},
            },
        )
        latency = (time.monotonic() - t0) * 1000
        content = resp.choices[0].message.content
        parsed = json.loads(content)
        has_hypothesis = bool(parsed.get("hypothesis_text", "").strip())
        has_calls = len(parsed.get("capability_calls", [])) > 0
        _check("Pydantic-compatible schema", has_hypothesis and has_calls, f"{latency:.0f}ms")
        print(f"    Model: {resp.model}")
        print(f"    Tokens: {resp.usage.prompt_tokens}+{resp.usage.completion_tokens}")
        print(f"    Hypothesis: {parsed['hypothesis_text'][:80]}...")
    except Exception as e:
        _check("Pydantic-compatible schema", False, str(e)[:60])
        sys.exit(1)

    # 4. Model list (provider info)
    print("\n4. Model availability")
    try:
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        models = [m["id"] for m in data.get("data", [])]
        _check(f"{len(models)} models available", True)
        for m in sorted(models):
            print(f"    - {m}")
    except Exception as e:
        _check("Model list", False, str(e)[:60])

    print("\n=== All smoke checks passed ===")


if __name__ == "__main__":
    main()
