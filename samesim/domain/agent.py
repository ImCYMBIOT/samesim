"""
Agent — the generic participant in a simulation.

An Agent is a pure data container. It has no behavior of its own.
Behavior is applied by the SimulationEngine via the active BehaviorPort.

An agent may represent: a network router, a drone, an IoT sensor,
an LLM assistant, a biological cell, a federated learning node,
or any other participant in a distributed system.

The engine never cares what the agent represents.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .ids import AgentId
from .state import AgentState


@dataclass
class Agent:
    """Generic distributed system participant.

    Attributes:
        agent_id:  Globally unique integer identifier.
        state:     Current agent state. Replaced (not mutated) each tick.
                   Schema defined by the active BehaviorPort plugin.
        metadata:  Arbitrary key-value data for introspection/debugging.
                   The engine never reads metadata.
    """

    agent_id: AgentId
    state: AgentState
    metadata: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"Agent(id={self.agent_id}, state={self.state!r})"
