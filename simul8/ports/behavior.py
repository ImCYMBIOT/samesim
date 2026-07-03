"""
BehaviorPort — the contract for agent decision-making.

Purpose:
    Defines how an agent decides its next state and what messages to send.

Contracts:
    - MUST NOT import from simul8.core or simul8.app
    - initialize() is called once per agent at simulation start
    - step() is called once per agent per tick
    - step() MUST be deterministic given the same RNG state and inputs
    - The only permitted internal state is the per-agent RNG
      (stored in initialize(), used in step())

Extension:
    Implement this port to add any behavior to agents:
    random walks, FSMs, RL policies, LLM planning, NCA updates, etc.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from random import Random
from typing import Any

from ..domain.ids import AgentId, VirtualTime
from ..domain.message import Message
from ..domain.state import AgentState


@dataclass
class BehaviorResult:
    """The output of one BehaviorPort.step() call for one agent.

    Attributes:
        next_state:        The agent's new state after this step.
        outbound_messages: Messages to be routed and delivered to other agents.
    """

    next_state: AgentState
    outbound_messages: list[Message] = field(default_factory=list)


class BehaviorPort(ABC):
    """Abstract contract for agent behavior.

    Implement this to define what agents do each tick.
    One instance is shared across all agents in the simulation.
    Per-agent state lives in AgentState; per-agent randomness lives in the
    RNG stored during initialize().
    """

    @abstractmethod
    def initialize(
        self,
        agent_id: AgentId,
        config: dict[str, Any],
        rng: Random,
    ) -> AgentState:
        """Create and return the initial AgentState for this agent.

        Called once per agent during experiment setup, in agent_id order.
        The rng is pre-seeded by RandomnessManager for this agent.

        Args:
            agent_id: The ID of the agent being initialized.
            config:   Plugin-specific config from plugin_configs[ClassName].
            rng:      Seeded random generator for this agent.

        Returns:
            The initial AgentState for this agent.
        """
        ...

    @abstractmethod
    def step(
        self,
        agent_id: AgentId,
        current_state: AgentState,
        inbox: list[Message],
        neighbors: frozenset[AgentId],
        virtual_time: VirtualTime,
    ) -> BehaviorResult:
        """Compute the agent's next state and outbound messages.

        Called once per agent per tick. Inbox contains all messages
        delivered to this agent since the last tick.

        Args:
            agent_id:     The agent being stepped.
            current_state: The agent's state at the start of this tick.
            inbox:        Messages received since the last tick (may be empty).
            neighbors:    The agent's current neighbor set from the topology.
            virtual_time: Current simulation time.

        Returns:
            BehaviorResult with the new state and any outbound messages.
        """
        ...
