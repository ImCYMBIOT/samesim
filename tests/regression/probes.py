"""
Probe plugins for the golden-trace guard. Test-only; never shipped.

The golden traces pin what plugins *observe*. That makes the guard only as
sensitive as the plugins that happen to exist -- and we found the limit
directly: reversing the order in which the engine builds each inbox changed
no golden trace, because on CPython >= 3.12 sum() of floats is compensated
and effectively order-independent, max() is order-free, and SIR only
counts. A future order-sensitive plugin (or the same plugins on Python
3.11) would have seen a different run, and the guard would not have
noticed.

InboxProbeBehavior closes that gap by being maximally sensitive to
everything the engine controls: it writes the exact inbox -- sender,
message id, send time, addressing mode, in the order delivered -- plus the
time it was stepped, into its state, which TraceDigestMetric folds. Any
change to delivery order, delivery time, batching, or recipient selection
changes its trace.

It alternates addressing modes so both paths of the addressing contract are
pinned: even ticks send one broadcast=True message, odd ticks send
addressed messages to two neighbors chosen by its per-agent RNG.
"""
from __future__ import annotations

import random
from typing import Any

from simul8.domain.ids import AgentId, MessageId, VirtualTime
from simul8.domain.message import Message
from simul8.domain.state import AgentState
from simul8.ports.behavior import BehaviorPort, BehaviorResult


class InboxProbeBehavior(BehaviorPort):
    def __init__(self) -> None:
        self._rngs: dict[AgentId, random.Random] = {}
        self._msg_counter = 0

    def initialize(self, agent_id: AgentId, config: dict[str, Any], rng: random.Random) -> AgentState:
        self._rngs[agent_id] = rng
        return AgentState(data={"steps": 0, "seen": [], "stepped_at": None})

    def step(
        self,
        agent_id: AgentId,
        current_state: AgentState,
        inbox: list[Message],
        neighbors: frozenset[AgentId],
        virtual_time: VirtualTime,
    ) -> BehaviorResult:
        steps = current_state.get("steps", 0)
        seen = [
            [int(m.sender_id), int(m.message_id), m.get("sent_at"), m.broadcast]
            for m in inbox
        ]
        next_state = current_state.with_values(
            steps=steps + 1, seen=seen, stepped_at=float(virtual_time)
        )

        outbound: list[Message] = []
        if neighbors:
            if steps % 2 == 0:
                outbound.append(self._message(agent_id, agent_id, virtual_time, broadcast=True))
            else:
                ordered = sorted(neighbors)
                for target in self._rngs[agent_id].sample(ordered, min(2, len(ordered))):
                    outbound.append(self._message(agent_id, target, virtual_time, broadcast=False))
        return BehaviorResult(next_state=next_state, outbound_messages=outbound)

    def _message(self, sender, recipient, t, broadcast) -> Message:
        self._msg_counter += 1
        return Message(
            message_id=MessageId(self._msg_counter),
            sender_id=sender,
            recipient_id=recipient,
            payload={"sent_at": float(t)},
            broadcast=broadcast,
        )
