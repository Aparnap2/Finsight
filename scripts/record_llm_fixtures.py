"""Record LLM outputs to fixture files for replay testing.

Usage:
    FINSIGHT_ALLOW_LIVE_LLM=1 uv run python scripts/record_llm_fixtures.py

Records representative LLM outputs for each exception type.
Fixtures are saved to tests/evals/llm/fixtures/.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Gate
if not os.environ.get("FINSIGHT_ALLOW_LIVE_LLM"):
    print("SKIP: set FINSIGHT_ALLOW_LIVE_LLM=1 to record fixtures")
    sys.exit(0)

# Load .env
_env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

from openai import OpenAI  # noqa: E402

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "evals" / "llm" / "fixtures"
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

SCHEMA = {
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

SCENARIOS = [
    {
        "name": "partial_refund",
        "user": (
            "Exception: PARTIAL_REFUND_ACCOUNTING_LAG\n"
            "Evidence IDs: ev_stripe_charge_001, ev_qb_ledger_002\n"
            "Capability allowlist: get_stripe_payment, get_stripe_refunds, "
            "get_qb_transaction, get_expected_state, search_gmail\n\n"
            "Charge: 50000 INR. Refund: 15000 INR. Expected ledger: 35000. Actual: 50000."
        ),
    },
    {
        "name": "fee_mismatch",
        "user": (
            "Exception: FEE_MISMATCH\n"
            "Evidence IDs: ev_stripe_fee_001, ev_expected_fee_002\n"
            "Capability allowlist: get_stripe_payment, get_stripe_refunds, "
            "get_qb_transaction, get_expected_state, search_gmail\n\n"
            "Stripe fee: 152.50. Expected: max(1.00, 0.5% of 30500) = 152.50. "
            "Close but off by 0.01."
        ),
    },
    {
        "name": "duplicate_entry",
        "user": (
            "Exception: DUPLICATE_LEDGER_ENTRY\n"
            "Evidence IDs: ev_qb_txn_a, ev_qb_txn_b, ev_stripe_ch_001\n"
            "Capability allowlist: get_stripe_payment, get_stripe_refunds, "
            "get_qb_transaction, get_expected_state, search_gmail\n\n"
            "Two QB entries for same Stripe charge. One matches exactly. Other is 2x."
        ),
    },
]


def main() -> None:
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        print("FAIL: GROQ_API_KEY not set")
        sys.exit(1)

    client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1", timeout=30.0)
    model = "openai/gpt-oss-20b"

    for scenario in SCENARIOS:
        print(f"\nRecording: {scenario['name']}")
        t0 = time.monotonic()
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "Financial investigation planner. Return valid JSON.",
                },
                {"role": "user", "content": scenario["user"]},
            ],
            temperature=0,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "Plan", "schema": SCHEMA, "strict": True},
            },
        )
        latency = (time.monotonic() - t0) * 1000
        content = resp.choices[0].message.content
        parsed = json.loads(content)

        fixture = {
            "model": resp.model,
            "scenario": scenario["name"],
            "response": parsed,
            "usage": {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
            },
        }

        path = FIXTURES_DIR / f"{scenario['name']}_plan.json"
        with open(path, "w") as f:
            json.dump(fixture, f, indent=2)
        print(f"  -> {path.name} ({latency:.0f}ms)")
        print(f"  Hypothesis: {parsed['hypothesis_text'][:80]}...")

    print(f"\nRecorded {len(SCENARIOS)} fixtures to {FIXTURES_DIR}")


if __name__ == "__main__":
    main()
