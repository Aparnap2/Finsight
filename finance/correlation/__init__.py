"""Deterministic P6-04 evidence correlation: collect, link, package."""

from finance.correlation.chain import (
    ChainEdge,
    ConflictMarker,
    EvidenceChain,
    build_chain,
    detect_conflicts,
    make_edge,
)
from finance.correlation.collector import (
    SCOPE_REFUSED_MESSAGE,
    CollectedEvidence,
    DroppedSource,
    collect_evidence,
)
from finance.correlation.converter import (
    ContextRef,
    ConvertedEvidence,
    context_to_evidence,
    evidence_id_for,
    fact_to_evidence,
    truncate_content,
    trust_class_for,
)
from finance.correlation.package import (
    EvidencePackage,
    MissingLeg,
    assemble_package,
    check_summary,
    to_store_dict,
)

__all__ = [
    "ChainEdge",
    "CollectedEvidence",
    "ConflictMarker",
    "ContextRef",
    "ConvertedEvidence",
    "DroppedSource",
    "EvidenceChain",
    "EvidencePackage",
    "MissingLeg",
    "SCOPE_REFUSED_MESSAGE",
    "assemble_package",
    "build_chain",
    "check_summary",
    "collect_evidence",
    "context_to_evidence",
    "detect_conflicts",
    "evidence_id_for",
    "fact_to_evidence",
    "make_edge",
    "to_store_dict",
    "truncate_content",
    "trust_class_for",
]
