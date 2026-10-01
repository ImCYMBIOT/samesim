"""
AsyncGossipBehavior — randomized pairwise averaging on Poisson clocks.

The asynchronous gossip model analysed by Boyd, Ghosh, Prabhakar and Shah
("Randomized Gossip Algorithms", IEEE Trans. Inf. Theory, 2006): every agent
has an independent clock that ticks at the times of a Poisson process; when
agent i's clock ticks, it picks a neighbor j uniformly at random and the
two replace their values with their average.

Requires simulation.activation: event.

Over messages, the exchange is a pull/push pair:

    i's clock ticks  ->  i sends PULL(x_i) to j
    j receives PULL  ->  j replies PUSH(x_j), then x_j := (x_j + x_i) / 2
    i receives PUSH  ->  x_i := (x_i + x_j) / 2

When message latency is small relative to the clock period (so exchanges
rarely overlap), this is Boyd et al.'s model. With latency comparable to the
clock period, an agent may take part in another exchange while one is in
flight; values stay bounded and still reach consensus, but the sum of values
is no longer exactly conserved. Keep latency well below 1/clock_rate when
comparing against the analytical results.

Contrast with GossipBehavior (synchronous push to fan_out neighbors every
tick), which is a different protocol with different scaling: on a ring,
synchronous push converges in O(n) ticks, whereas Boyd et al.'s asynchronous
pairwise model needs O(n^2) time.

Schedules (when each agent starts an exchange):
    poisson  (default) Boyd et al.'s model: a Poisson clock at clock_rate.
             Over a unit of time an agent starts 0, 1, 2, ... exchanges.
    cycle    PeerSim's cycle-driven model, analysed by Jelasity, Montresor
             and Babaoglu (2005): every agent starts exactly one exchange
             per unit of time, at an independent uniformly random point in
             it, which visits the agents in a uniformly random order each
             cycle. On a complete graph, with latency far below the gap
             between agents (1/n), the expected variance shrinks by a factor
             1/(2*sqrt(e)) ~ 0.303 per cycle.

Configuration (plugin_configs.AsyncGossipBehavior):
    schedule:            "poisson" or "cycle" (default "poisson")
    clock_rate:          poisson only: exchanges per unit time per agent (default 1.0)
    initial_value_range: [low, high] for uniform initial values (default [0, 1])

State: {"value": float}
"""
from __future__ import annotations

import math
import random
from typing import Any

from ...domain import portable_math
from ...domain.ids import AgentId, MessageId, VirtualTime
from ...domain.message import Message
from ...domain.state import AgentState
from ...domain.timer import Timer
from ...ports.behavior import BehaviorPort, BehaviorResult

CLOCK = "clock"


class AsyncGossipBehavior(BehaviorPort):
    """Randomized pairwise averaging driven by per-agent Poisson clocks."""

    activation_modes = frozenset({"event"})

    def __init__(self) -> None:
        self._rate: float = 1.0
        self._schedule: str = "poisson"
        self._agent_rngs: dict[AgentId, random.Random] = {}
        self._cycle: dict[AgentId, int] = {}  # cycle schedule: the cycle of the next exchange
        self._msg_counter: int = 0

    def initialize(self, agent_id: AgentId, config: dict[str, Any], rng: random.Random) -> AgentState:
        self._schedule = str(config.get("schedule", "poisson"))
        if self._schedule not in ("poisson", "cycle"):
            raise ValueError(f"AsyncGossipBehavior: schedule must be 'poisson' or 'cycle', "
                             f"got {self._schedule!r}")
        if self._schedule == "poisson":
            self._rate = float(config.get("clock_rate", 1.0))
            if not self._rate > 0:
                raise ValueError(f"AsyncGossipBehavior: clock_rate must be > 0, got {self._rate}")
        low, high = config.get("initial_value_range", [0.0, 1.0])
        self._agent_rngs[agent_id] = rng
        return AgentState(data={"value": rng.uniform(float(low), float(high))})

    def step(
        self,
        agent_id: AgentId,
        current_state: AgentState,
        inbox: list[Message],
        neighbors: frozenset[AgentId],
        virtual_time: VirtualTime,
    ) -> BehaviorResult:
        if not inbox:  # bootstrap (or recovery): start this agent's clock
            if self._schedule == "cycle":
                # At t=0 the first exchange is in cycle 0; after a recovery,
                # skip the rest of the current cycle.
                self._cycle[agent_id] = 0 if virtual_time == 0 else math.floor(virtual_time) + 1
            return BehaviorResult(next_state=current_state,
                                  set_timers=[self._next_tick(agent_id, virtual_time)])

        value = current_state.get("value")
        replies: list[Message] = []
        for m in inbox:
            if m.get("kind") == "pull":
                replies.append(self._message(agent_id, m.sender_id, "push", value))
            value = (value + m.get("value")) / 2
        return BehaviorResult(next_state=current_state.with_value("value", value),
                              outbound_messages=replies)

    def on_timer(
        self,
        agent_id: AgentId,
        current_state: AgentState,
        tag: str,
        neighbors: frozenset[AgentId],
        virtual_time: VirtualTime,
    ) -> BehaviorResult:
        out: list[Message] = []
        if neighbors:
            target = self._agent_rngs[agent_id].choice(sorted(neighbors))
            out.append(self._message(agent_id, target, "pull", current_state.get("value")))
        if self._schedule == "cycle":
            self._cycle[agent_id] += 1
        return BehaviorResult(next_state=current_state, outbound_messages=out,
                              set_timers=[self._next_tick(agent_id, virtual_time)])

    def _next_tick(self, agent_id: AgentId, now: float) -> Timer:
        rng = self._agent_rngs[agent_id]
        if self._schedule == "cycle":
            # A uniformly random point in this agent's next cycle.
            at = self._cycle[agent_id] + rng.random()
            if at <= now:  # only possible at t=0 with random() == 0.0
                at = math.nextafter(now, math.inf)
            return Timer(CLOCK, at - now)
        # portable_math, not rng.expovariate: clock times are exact event
        # times, and libm's log differs across platforms in the last bit.
        while True:  # zero only when random() is 0.0 -- not a legal delay
            delay = portable_math.expovariate(rng, self._rate)
            if delay > 0.0:
                return Timer(CLOCK, delay)

    def _message(self, sender: AgentId, recipient: AgentId, kind: str, value: float) -> Message:
        self._msg_counter += 1
        return Message(message_id=MessageId(self._msg_counter), sender_id=sender,
                       recipient_id=recipient, payload={"kind": kind, "value": value})
