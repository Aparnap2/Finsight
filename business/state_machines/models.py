"""State machine models for workflow entity lifecycle management.

Provides the base StateMachine class with transition validation,
guard condition support, and a registry for looking up state
machines by entity name.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TransitionError(Exception):
    """Raised when an illegal state transition is attempted.

    Attributes:
        entity: The entity type name.
        from_status: The current status value.
        to_status: The attempted (illegal) status value.
        reason: Optional human-readable explanation.
    """

    def __init__(self, entity: str, from_status: str, to_status: str, reason: str = "") -> None:
        self.entity = entity
        self.from_status = from_status
        self.to_status = to_status
        self.reason = reason
        msg = f"Illegal transition: {entity} from {from_status} -> {to_status}"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)


# ---------------------------------------------------------------------------
# Guard conditions
# ---------------------------------------------------------------------------


class GuardCondition(BaseModel):
    """A precondition that must hold for a state transition to be legal.

    Guard conditions encode business rules that gate transitions beyond
    the structural legality defined by STATES and TRANSITIONS. Each
    condition applies to one or more (from_status, to_status) pairs and
    carries a Python expression string for runtime evaluation.
    """

    name: str = Field(..., description="Unique name for this guard condition")
    description: str = Field(..., description="Human-readable description of the condition")
    applies_to: list[tuple[str, str]] = Field(
        default_factory=list,
        description="List of (from_status, to_status) pairs this guard applies to",
    )
    condition_fn: str = Field(
        ...,
        description="Python expression string, evaluated with 'context' dict in scope",
    )


# ---------------------------------------------------------------------------
# State machine base
# ---------------------------------------------------------------------------


class StateMachine(BaseModel):
    """Base model for all state machines.

    Defines the set of legal states, legal transitions between them,
    and optional guard conditions that gate specific transitions.
    Provides validation methods for checking and asserting legal
    transitions.
    """

    name: str = Field(..., description="Unique name for this state machine")
    states: set[str] = Field(default_factory=set, description="All legal states")
    transitions: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Mapping: from_state -> list of legal to_state values",
    )
    guard_conditions: list[GuardCondition] = Field(
        default_factory=list,
        description="Guard conditions that gate specific transitions",
    )
    business_context: str = Field(
        default="",
        description="Business description of what this state machine governs",
    )

    model_config = {"frozen": True}

    @property
    def initial_states(self) -> set[str]:
        """Return states not reachable from any other state.

        These are the natural starting points for an entity's lifecycle.
        """
        all_targets: set[str] = set()
        for targets in self.transitions.values():
            all_targets.update(targets)
        return self.states - all_targets - self.terminal_states

    @property
    def terminal_states(self) -> set[str]:
        """Return states from which no further transitions are defined.

        Once an entity reaches a terminal state, no further state changes
        are permitted by this state machine.
        """
        non_terminal: set[str] = set()
        for from_state, targets in self.transitions.items():
            if targets:
                non_terminal.add(from_state)
        return self.states - non_terminal

    def is_legal(self, from_state: str, to_state: str) -> bool:
        """Check whether a transition is structurally permitted.

        Args:
            from_state: The current state.
            to_state: The desired next state.

        Returns:
            True if the transition is defined in the transition map.
        """
        allowed = self.transitions.get(from_state, [])
        return to_state in allowed

    def assert_legal(self, from_state: str, to_state: str, entity: str = "") -> None:
        """Validate that a transition is legal; raise TransitionError otherwise.

        Args:
            from_state: The current state.
            to_state: The desired next state.
            entity: Optional entity identifier for error messages.

        Raises:
            TransitionError: If the transition is not defined.
        """
        if not self.is_legal(from_state, to_state):
            name = entity or self.name
            raise TransitionError(name, from_state, to_state)

    def get_guards(self, from_state: str, to_state: str) -> list[GuardCondition]:
        """Return all guard conditions that apply to a specific transition.

        Args:
            from_state: The current state.
            to_state: The desired next state.

        Returns:
            List of GuardCondition instances that gate this transition.
        """
        return [g for g in self.guard_conditions if (from_state, to_state) in g.applies_to]


# ---------------------------------------------------------------------------
# State machine registry
# ---------------------------------------------------------------------------


class StateMachineRegistry(BaseModel):
    """Central registry of all state machines in the platform.

    Provides lookup by entity name and iteration over all registered
    state machines.
    """

    machines: dict[str, StateMachine] = Field(
        default_factory=dict,
        description="State machines keyed by entity/state machine name",
    )

    def register(self, machine: StateMachine) -> None:
        """Register a state machine.

        Args:
            machine: The StateMachine instance to register.
        """
        self.machines[machine.name] = machine

    def get(self, name: str) -> StateMachine | None:
        """Look up a state machine by name.

        Args:
            name: The name of the state machine (e.g. 'PipelineRun').

        Returns:
            The StateMachine if found, None otherwise.
        """
        return self.machines.get(name)

    @property
    def count(self) -> int:
        """Total number of registered state machines."""
        return len(self.machines)

    def list_names(self) -> list[str]:
        """Return the names of all registered state machines."""
        return list(self.machines.keys())
