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
from simul8.domain.timer import Timer
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


class EventProbeBehavior(BehaviorPort):
    """Event-activation probe: exercises every engine mechanism of Phase 2
    and records exactly what it observes, so the golden traces pin it.

    - Bootstrap: sets a "ping" timer (random 0.5-2.0) and a "quiet" timer (3.0).
    - on_timer("ping"): broadcasts (hops=0) and re-arms "ping" -- periodic
      timers and broadcast fan-out with per-copy delays.
    - on_timer("quiet"): only records that it fired.
    - step(inbox): records the batch (sender, message id, hops, send time,
      addressing mode, in delivery order); forwards ONE addressed message
      to a random neighbor if any message has hops < 2 (bounded traffic);
      re-arms "ping" if a lower-id agent is in the batch (timer
      replacement); cancels "quiet" if an even-id agent is (cancellation).
    """

    activation_modes = frozenset({"event"})

    def __init__(self) -> None:
        self._rngs: dict[AgentId, random.Random] = {}
        self._msg_counter = 0

    def initialize(self, agent_id, config, rng):
        self._rngs[agent_id] = rng
        return AgentState(data={"batch": [], "at": None, "fired": []})

    def step(self, agent_id, current_state, inbox, neighbors, virtual_time):
        rng = self._rngs[agent_id]
        state = current_state.with_values(
            batch=[[int(m.sender_id), int(m.message_id), m.get("hops"), m.get("sent_at"), m.broadcast]
                   for m in inbox],
            at=float(virtual_time),
        )
        if not inbox:  # bootstrap
            return BehaviorResult(next_state=state, set_timers=[
                Timer("ping", rng.uniform(0.5, 2.0)), Timer("quiet", 3.0)])

        out, timers, cancels = [], [], set()
        if neighbors and any(m.get("hops") < 2 for m in inbox):
            hops = min(m.get("hops") for m in inbox) + 1
            target = rng.choice(sorted(neighbors))
            out.append(self._message(agent_id, target, virtual_time, hops, broadcast=False))
        if any(m.sender_id < agent_id for m in inbox):
            timers.append(Timer("ping", rng.uniform(0.5, 2.0)))
        if any(int(m.sender_id) % 2 == 0 for m in inbox):
            cancels.add("quiet")
        return BehaviorResult(next_state=state, outbound_messages=out,
                              set_timers=timers, cancel_timers=frozenset(cancels))

    def on_timer(self, agent_id, current_state, tag, neighbors, virtual_time):
        state = current_state.with_values(
            fired=[tag, float(virtual_time)], at=float(virtual_time), batch=[])
        if tag == "quiet":
            return BehaviorResult(next_state=state)
        out = [self._message(agent_id, agent_id, virtual_time, 0, broadcast=True)] if neighbors else []
        return BehaviorResult(next_state=state, outbound_messages=out,
                              set_timers=[Timer("ping", self._rngs[agent_id].uniform(0.5, 2.0))])

    def _message(self, sender, recipient, t, hops, broadcast) -> Message:
        self._msg_counter += 1
        return Message(message_id=MessageId(self._msg_counter), sender_id=sender,
                       recipient_id=recipient, payload={"hops": hops, "sent_at": float(t)},
                       broadcast=broadcast)
