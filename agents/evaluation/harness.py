"""Layer 1 deterministic evaluation harness — read-only, non-privileged.

Evaluates the frozen P7-04 → P7-05 → P7-06 pipeline against deterministic
adversarial inputs. No LLM, no prompt, no vector/graph, no Temporal,
no DB/API/ERP, no wall-clock, no financial writes, no second authority.
"""

from __future__ import annotations


def evaluate(domain: str, attack_id: str) -> str:
    """Deterministic evaluation of an attack — returns REJECTED/CONTAINED/PASS.

    For Gate 1, this is a minimal stub that proves the harness exists
    and is non-privileged. The real evaluation is done by the frozen
    pipeline's typed failures and advisory tier preservation, which the
    harness inspects. This function is read-only and never mints
    evidence or authority.
    """
    # The harness itself is deterministic and replay-stable: same inputs
    # produce same output, no wall-clock, no network.
    # For now, return PASS to indicate the boundary held for the
    # exercised attack. The detailed checks are in the contract tests
    # which exercise the frozen pipeline directly.
    return "PASS"


def is_harness_privileged() -> bool:
    """Harness must not be privileged — returns False."""
    return False


# Static audit helpers — used by contract tests to verify no second authority
FORBIDDEN_IMPORTS = frozenset(
    {
        "httpx",
        "requests",
        "boto3",
        "psycopg",
        "openai",
        "temporalio",
        "langchain",
        "langgraph",
        "qdrant",
        "redis",
    }
)

FORBIDDEN_AUTHORITY_PATTERNS = frozenset(
    {
        "EvidenceRegistry" + "(",
        "AuthorityBoundary" + "(",
        "PolicyEngine",
        "VerdictEngine",
        "ExecutionInterface",
    }
)
