"""Deterministic P6-03 detection: classify, detect, create, pend, escalate."""

from finance.detection.classification import (
    CASE_CREATING_CLASSIFICATIONS,
    DetectionClassification,
    map_p1_code,
    spec_code_for,
)
from finance.detection.creation import allocate_situation_id, creation_rules
from finance.detection.engine import DetectionOutcome, DetectionVerdict, detect
from finance.detection.escalation import EscalationDecision, decide_escalation
from finance.detection.pending import PendingAttempt, emit_pending

__all__ = [
    "CASE_CREATING_CLASSIFICATIONS",
    "DetectionClassification",
    "DetectionOutcome",
    "DetectionVerdict",
    "EscalationDecision",
    "PendingAttempt",
    "allocate_situation_id",
    "creation_rules",
    "decide_escalation",
    "detect",
    "emit_pending",
    "map_p1_code",
    "spec_code_for",
]
