"""
Test-only plugins for tests/integration/test_event_activation.py.

ScriptedBehavior runs a per-agent script from its config and logs every call
the engine makes into it. A script maps a trigger to a list of actions:

    triggers:  "boot"            -- the t=0 bootstrap step
               "message"         -- any step with a non-empty inbox
               "timer:<tag>"     -- on_timer(tag)
    actions:   {"send": to, "delay": d}     -- delay None = default latency
               {"set": tag, "delay": d}
               {"cancel": tag}

Each trigger's actions run on every occurrence unless the action has
"once": true. The log is a class attribute because the runner constructs
plugins itself; tests reset it.
"""
from __future__ import annotations

import random
from typing import Any

from samesim.domain.delivery import Delivery
from samesim.domain.ids import AgentId, MessageId
from samesim.domain.message import Message
from samesim.domain.state import AgentState
from samesim.domain.timer import Timer
from samesim.ports.behavior import BehaviorPort, BehaviorResult
from samesim.domain.event import (AgentStateChangedEvent, MessageDeliveredEvent,
                                 MessageLostEvent, TopologyChangeEvent)
from samesim.domain.ids import MetricName
from samesim.domain.metric import MetricSeries
from samesim.ports.communication import CommunicationProtocolPort
from samesim.ports.metric_collector import MetricCollectorPort


class ScriptedBehavior(BehaviorPort):
    activation_modes = frozenset({"synchronous", "event"})
    log: list[dict[str, Any]] = []

    def __init__(self) -> None:
        self._script: dict[int, dict[str, list[dict]]] = {}
        self._counter = 0
        self._done_once: set[tuple] = set()

    def initialize(self, agent_id, config, rng: random.Random) -> AgentState:
        self._script = {int(k): v for k, v in config.get("script", {}).items()}
        return AgentState(data={"calls": 0})

    def step(self, agent_id, current_state, inbox, neighbors, virtual_time) -> BehaviorResult:
        calls = current_state.get("calls")
        trigger = "boot" if calls == 0 and not inbox else ("message" if inbox else "step")
        ScriptedBehavior.log.append({
            "t": float(virtual_time), "agent": int(agent_id), "call": "step",
            "trigger": trigger, "inbox": [(int(m.sender_id), m.get("n")) for m in inbox],
            "neighbors": sorted(int(n) for n in neighbors), "calls": calls,
        })
        return self._run(agent_id, current_state, trigger)

    def on_timer(self, agent_id, current_state, tag, neighbors, virtual_time) -> BehaviorResult:
        ScriptedBehavior.log.append({
            "t": float(virtual_time), "agent": int(agent_id), "call": "timer", "tag": tag,
        })
        return self._run(agent_id, current_state, f"timer:{tag}")

    def _run(self, agent_id, state, trigger) -> BehaviorResult:
        out, timers, cancels = [], [], set()
        for i, action in enumerate(self._script.get(int(agent_id), {}).get(trigger, [])):
            key = (int(agent_id), trigger, i)
            if action.get("once") and key in self._done_once:
                continue
            self._done_once.add(key)
            if "send" in action:
                self._counter += 1
                out.append(Message(
                    message_id=MessageId(self._counter), sender_id=agent_id,
                    recipient_id=AgentId(action["send"]),
                    payload={"n": self._counter, "delay": action.get("delay")},
                ))
            elif "set" in action:
                timers.append(Timer(tag=action["set"], delay=action["delay"]))
            elif "cancel" in action:
                cancels.add(action["cancel"])
        return BehaviorResult(
            next_state=state.with_value("calls", state.get("calls") + 1),
            outbound_messages=out, set_timers=timers, cancel_timers=frozenset(cancels),
        )


class TickOnlyBehavior(BehaviorPort):
    """Declares nothing: synchronous only, like every pre-Phase-2 behavior."""

    def initialize(self, agent_id, config, rng):
        return AgentState(data={})

    def step(self, agent_id, current_state, inbox, neighbors, virtual_time):
        return BehaviorResult(next_state=current_state)


class EventOnlyBehavior(TickOnlyBehavior):
    activation_modes = frozenset({"event"})


class TimerWithoutHandlerBehavior(TickOnlyBehavior):
    """Sets a timer but never implements on_timer()."""

    activation_modes = frozenset({"event"})

    def step(self, agent_id, current_state, inbox, neighbors, virtual_time):
        return BehaviorResult(next_state=current_state, set_timers=[Timer("t", 1.0)])


class PayloadDelayProtocol(CommunicationProtocolPort):
    """Delivers each message after the delay its payload names; records
    every on_topology_changed() call."""

    topology_changes: list = []

    def initialize(self, topology, config, rng): ...

    def on_topology_changed(self, topology):
        PayloadDelayProtocol.topology_changes.append(
            {a: sorted(int(n) for n in topology.neighbors(a)) for a in sorted(topology.agent_ids)})

    def route(self, message, sender_id, topology):
        return [Delivery(message.recipient_id, message, message.get("delay"))]


class EventLogMetric(MetricCollectorPort):
    """Records deliveries, losses, churn changes and state changes (which the
    engine emits for every behavior call) -- enough to check churn
    invariants for ANY behavior without instrumenting it."""

    log: list[tuple] = []

    def subscribed_events(self):
        return frozenset({MessageDeliveredEvent, MessageLostEvent, TopologyChangeEvent,
                          AgentStateChangedEvent})

    def on_event(self, event, virtual_time):
        t = float(virtual_time)
        if isinstance(event, MessageDeliveredEvent):
            EventLogMetric.log.append(("delivered", t, int(event.recipient_id)))
        elif isinstance(event, MessageLostEvent):
            EventLogMetric.log.append(("lost", t, int(event.recipient_id), event.reason))
        elif isinstance(event, TopologyChangeEvent):
            c = event.change
            EventLogMetric.log.append(("change", t, sorted(map(int, c.fail)),
                                       sorted(map(int, c.recover)), sorted(map(int, c.join))))
        elif isinstance(event, AgentStateChangedEvent):
            EventLogMetric.log.append(("ran", t, int(event.agent_id)))

    def get_series(self):
        return MetricSeries(name=MetricName("event_log"))

    def reset(self): ...
