"""
BehaviorPort — the contract for agent decision-making.

Purpose:
    Defines how an agent decides its next state and what messages to send.

Contracts:
    - MUST NOT import from samesim.core or samesim.app
    - initialize() is called once per agent at simulation start
    - step() is called once per agent per tick under synchronous activation;
      under event activation, once at t=0 (empty inbox) and then whenever
      messages reach the agent
    - activation_modes declares which modes the behavior supports; an
      experiment requesting any other mode is rejected when it loads
    - Timers (BehaviorResult.set_timers) exist only under event activation;
      returning one under synchronous activation raises ValueError
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
from ..domain.timer import Timer


@dataclass
class BehaviorResult:
    """The output of one BehaviorPort.step() call for one agent.

    Attributes:
        next_state:        The agent's new state after this step.
        outbound_messages: Messages to be routed and delivered to other agents.
        set_timers:        Event activation only. Timers to start; a tag
                           already pending is replaced (its old expiry is
                           discarded). Applied after cancel_timers, so
                           cancelling and setting one tag restarts it.
        cancel_timers:     Event activation only. Tags whose pending timer
                           should be discarded. Cancelling a tag that is not
                           pending is a no-op.
    """

    next_state: AgentState
    outbound_messages: list[Message] = field(default_factory=list)
    set_timers: list[Timer] = field(default_factory=list)
    cancel_timers: frozenset[str] = frozenset()


class BehaviorPort(ABC):
    """Abstract contract for agent behavior.

    Implement this to define what agents do each tick.
    One instance is shared across all agents in the simulation.
    Per-agent state lives in AgentState; per-agent randomness lives in the
    RNG stored during initialize().
    """

    #: Activation modes this behavior is written for. The default is
    #: synchronous only, because a behavior that expects to run every tick
    #: would, under event activation, never run again after t=0 unless a
    #: message woke it -- and would then quietly report "no progress"
    #: instead of failing. Declare "event" only if the behavior drives
    #: itself with timers or messages.
    activation_modes: frozenset[str] = frozenset({"synchronous"})

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

        Synchronous activation: called once per agent per tick, with every
        message delivered since the last tick. Event activation: called once
        per agent at t=0 with an empty inbox (bootstrap), then whenever
        messages reach it, with all messages arriving at that instant.

        Args:
            agent_id:     The agent being stepped.
            current_state: The agent's current state.
            inbox:        Messages received, in delivery order (may be empty).
            neighbors:    The agent's current neighbor set from the topology.
            virtual_time: Current simulation time.

        Returns:
            BehaviorResult with the new state and any outbound messages.
        """
        ...

    def on_timer(
        self,
        agent_id: AgentId,
        current_state: AgentState,
        tag: str,
        neighbors: frozenset[AgentId],
        virtual_time: VirtualTime,
    ) -> BehaviorResult:
        """Handle an expired timer (event activation only).

        Called when a timer this agent set via BehaviorResult.set_timers
        fires and was not cancelled or replaced in the meantime. Messages
        that arrive at the same instant are processed first (via step()),
        so a message can still cancel a timer due at that exact instant.

        Override this if the behavior sets timers; the default raises,
        since it can only be reached by a behavior that set one.
        """
        raise NotImplementedError(
            f"{type(self).__name__} set timer {tag!r} but does not implement on_timer()"
        )

    def on_recover(
        self,
        agent_id: AgentId,
        current_state: AgentState,
        neighbors: frozenset[AgentId],
        virtual_time: VirtualTime,
    ) -> BehaviorResult:
        """A failed agent comes back (event activation only).

        current_state is the state the agent had when it failed: recovery
        models a restart with durable state. Its inbox and timers were lost
        in the failure. Override this to reset whatever a real restart would
        lose (a Raft node comes back as a follower, but must keep its term
        and vote -- forgetting its vote could elect two leaders in one term).

        The default is a bootstrap step: step() with an empty inbox, which is
        what lets an event-driven behavior re-arm its timers. Under
        synchronous activation this is not called; the agent simply resumes
        at the next tick.
        """
        return self.step(agent_id, current_state, [], neighbors, virtual_time)
