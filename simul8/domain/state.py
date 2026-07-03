"""
AgentState — the mutable state container for a single agent.

The core engine treats state as an opaque object. The schema (keys and
value types) is entirely defined by the active BehaviorPort plugin.

Design decision: AgentState is NOT frozen. The engine replaces an agent's
state slot with a new AgentState returned from BehaviorPort.step(). This
avoids the cost of copying 1,000 frozen objects per tick while keeping
state transitions explicit and traceable.

Usage:
    # Create initial state
    state = AgentState(data={"value": 0.5})

    # Read a value
    v = state.get("value")

    # Produce an updated copy (preferred pattern in behavior.step())
    new_state = state.with_value("value", 0.7)
    new_state = state.with_values(value=0.7, round=3)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentState:
    """Mutable container for agent-specific state.

    The engine never reads or interprets the 'data' dict.
    Only the active BehaviorPort plugin knows the schema.
    """

    data: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for key, or default if not present."""
        return self.data.get(key, default)

    def to_dict(self) -> dict[str, Any]:
        """Return a shallow copy of the internal data dict."""
        return dict(self.data)

    # ------------------------------------------------------------------
    # Immutable update API (returns new AgentState, never mutates self)
    # ------------------------------------------------------------------

    def with_value(self, key: str, value: Any) -> "AgentState":
        """Return a new AgentState with one field updated."""
        return AgentState(data={**self.data, key: value})

    def with_values(self, **kwargs: Any) -> "AgentState":
        """Return a new AgentState with multiple fields updated."""
        return AgentState(data={**self.data, **kwargs})

    def __repr__(self) -> str:
        return f"AgentState({self.data!r})"
