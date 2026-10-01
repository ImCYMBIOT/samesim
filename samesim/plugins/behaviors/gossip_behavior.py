"""
GossipBehavior — push gossip protocol behavior for agents.

Each tick:
    1. Average own value with any received messages (update state)
    2. Select k random neighbors and send current value to each

This implements synchronous push gossip. Convergence occurs as agents
repeatedly average their values with neighbors' values.

Configuration (plugin_configs.GossipBehavior):
    initial_value_range: [lo, hi]  — uniform random initial value (default [0.0, 1.0])
    fan_out: int                   — number of neighbors to push to per tick (default 3)
"""
from __future__ import annotations

import math
import random
from typing import Any

from ...domain.ids import AgentId, MessageId, VirtualTime
from ...domain.message import Message
from ...domain.state import AgentState
from ...ports.behavior import BehaviorPort, BehaviorResult


class GossipBehavior(BehaviorPort):
    """Push gossip: hold a float value, average with received values, push to k neighbors.

    One instance shared across all agents. Per-agent RNGs stored in initialize().
    """

    def __init__(self) -> None:
        # Shared config (same for all agents)
        self._fan_out: int = 3
        self._value_lo: float = 0.0
        self._value_hi: float = 1.0

        # Per-agent RNG storage (seeded deterministically by RandomnessManager)
        self._agent_rngs: dict[AgentId, random.Random] = {}

        # Monotonic counter for unique message IDs within this behavior instance
        self._msg_counter: int = 0

    # ------------------------------------------------------------------
    # BehaviorPort
    # ------------------------------------------------------------------

    def initialize(
        self,
        agent_id: AgentId,
        config: dict[str, Any],
        rng: random.Random,
    ) -> AgentState:
        """Set config from first call; assign per-agent RNG; draw initial value."""
        # Config is the same for all agents — re-setting is idempotent
        value_range = config.get("initial_value_range", [0.0, 1.0])
        self._value_lo = float(value_range[0])
        self._value_hi = float(value_range[1])
        self._fan_out = int(config.get("fan_out", 3))

        # Store this agent's seeded RNG for use in step()
        self._agent_rngs[agent_id] = rng

        initial_value = rng.uniform(self._value_lo, self._value_hi)
        return AgentState(data={"value": initial_value})

    def step(
        self,
        agent_id: AgentId,
        current_state: AgentState,
        inbox: list[Message],
        neighbors: frozenset[AgentId],
        virtual_time: VirtualTime,
    ) -> BehaviorResult:
        """Compute next state and outbound gossip messages."""
        my_value: float = current_state.get("value", 0.0)

        # Average own value with all received values
        if inbox:
            received_values = [msg.get("value", my_value) for msg in inbox]
            all_values = [my_value] + received_values
            # math.fsum, not sum(): fsum is correctly rounded, so the mean is
            # identical for any inbox order on every Python version. Builtin
            # sum() of floats changed algorithm in CPython 3.12, and with it
            # every gossip run -- same seed, different result on 3.11.
            my_value = math.fsum(all_values) / len(all_values)

        next_state = current_state.with_value("value", my_value)

        # Select k random neighbors to push current value to
        outbound: list[Message] = []
        if neighbors:
            rng = self._agent_rngs.get(agent_id)
            k = min(self._fan_out, len(neighbors))
            # Sort neighbors for determinism before sampling
            sorted_neighbors = sorted(neighbors)
            targets = rng.sample(sorted_neighbors, k) if rng else sorted_neighbors[:k]

            for target_id in targets:
                self._msg_counter += 1
                outbound.append(Message(
                    message_id=MessageId(self._msg_counter),
                    sender_id=agent_id,
                    recipient_id=target_id,
                    payload={"value": my_value},
                ))

        return BehaviorResult(next_state=next_state, outbound_messages=outbound)
