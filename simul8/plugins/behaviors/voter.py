"""
VoterBehavior — the (synchronous) voter model.

Each agent holds an opinion, 0 or 1. At every tick, every agent picks a
neighbor uniformly at random and adopts the opinion that neighbor held at
the previous tick. Run long enough on a connected, non-bipartite graph, all
agents end up agreeing.

What makes it a good validation target is an exact result: the
degree-weighted fraction holding opinion 1,

    M(t) = sum_i d_i x_i(t) / sum_i d_i,

is a martingale (each agent's expected next opinion is the average of its
neighbors', and summing d_i times that over all agents gives M again), so
the probability that opinion 1 wins equals its degree-weighted initial
fraction M(0) -- not its plain initial fraction. VoterMetric records M.

Messages: agents tell their neighbors their opinion at t=0 (an announcement
round: nobody changes opinion then, since nobody knows a neighbor's yet),
and afterwards only when it changes. Each agent keeps the last opinion it
heard from each neighbor. Once everyone agrees, nobody sends anything.

A neighbor an agent has never heard from (one added by churn, say) is
skipped when choosing; with no known neighbor the agent keeps its opinion.

Synchronous activation only. (On a bipartite graph the synchronous model
can oscillate forever instead of reaching consensus.)

Configuration (plugin_configs.VoterBehavior), one of:
    initial_ones:      agents 0 .. initial_ones-1 start with opinion 1, the
                       rest with 0. On a Barabasi-Albert graph the low ids
                       are the oldest, best-connected nodes, which makes
                       M(0) very different from the plain fraction.
    initial_fraction:  each agent starts with opinion 1 independently with
                       this probability (default 0.5)

State: {"opinion": 0 | 1, "known": {neighbor id: opinion}}
"""
from __future__ import annotations

import random
from typing import Any

from ...domain.ids import AgentId, MessageId, VirtualTime
from ...domain.message import Message
from ...domain.state import AgentState
from ...ports.behavior import BehaviorPort, BehaviorResult


class VoterBehavior(BehaviorPort):
    """Synchronous voter model: copy a random neighbor's previous opinion."""

    def __init__(self) -> None:
        self._rngs: dict[AgentId, random.Random] = {}
        self._msg_counter = 0

    def initialize(self, agent_id: AgentId, config: dict[str, Any], rng: random.Random) -> AgentState:
        self._rngs[agent_id] = rng
        if "initial_ones" in config:
            opinion = 1 if int(agent_id) < int(config["initial_ones"]) else 0
        else:
            p = float(config.get("initial_fraction", 0.5))
            if not 0.0 <= p <= 1.0:
                raise ValueError(f"VoterBehavior: initial_fraction must be in [0, 1], got {p}")
            opinion = 1 if rng.random() < p else 0
        return AgentState(data={"opinion": opinion, "known": {}})

    def step(
        self,
        agent_id: AgentId,
        current_state: AgentState,
        inbox: list[Message],
        neighbors: frozenset[AgentId],
        virtual_time: VirtualTime,
    ) -> BehaviorResult:
        opinion = current_state.get("opinion")
        if virtual_time == 0:  # announcement round
            return BehaviorResult(next_state=current_state,
                                  outbound_messages=self._announce(agent_id, opinion, neighbors))

        known = dict(current_state.get("known"))
        for m in inbox:  # opinions as of the end of the previous tick
            known[int(m.sender_id)] = m.get("opinion")
        candidates = [n for n in sorted(neighbors) if int(n) in known]
        new = opinion
        if candidates:
            new = known[int(self._rngs[agent_id].choice(candidates))]
        state = current_state.with_value("known", known).with_value("opinion", new)
        out = self._announce(agent_id, new, neighbors) if new != opinion else []
        return BehaviorResult(next_state=state, outbound_messages=out)

    def _announce(self, agent_id, opinion, neighbors) -> list[Message]:
        if not neighbors:
            return []
        self._msg_counter += 1
        return [Message(message_id=MessageId(self._msg_counter), sender_id=agent_id,
                        recipient_id=agent_id, payload={"opinion": opinion}, broadcast=True)]
