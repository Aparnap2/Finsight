from enum import Enum


class DegradedMode(str, Enum):
    NONE = "none"
    PRELIMINARY_ONLY = "preliminary_only"
    MISSING_FX = "missing_fx"
    LOW_COVERAGE = "low_coverage"
    STALE_SOURCE = "stale_source"
    INSUFFICIENT_CAUSAL_EVIDENCE = "insufficient_causal_evidence"
    FACT_VERIFIED_CAUSE_UNVERIFIED = "fact_verified_cause_unverified"
    PRECEDENT_ONLY_SUPPORT = "precedent_only_support"
