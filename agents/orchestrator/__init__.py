"""P4.5 controlled orchestration package.

Re-exports the orchestration result and runner.
"""

from agents.orchestrator.orchestrator import InvestigateOrchestrator
from agents.orchestrator.types import OrchestrationResult, OrchestrationStatus

__all__ = ["InvestigateOrchestrator", "OrchestrationResult", "OrchestrationStatus"]
