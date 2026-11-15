"""
EventTraceMetric — every event of a run, in dispatch order, as plain records.

Where TraceDigestMetric reduces a run to a fingerprint, this keeps the run
itself: what was sent, delivered and lost, every state change, timer, churn
change and tick. Enough to replay or animate a run after the fact, to debug
one event at a time, or to compute a measure nobody wrote a metric for.

One record per event. Its value is the event's sequence number; its tags
are `kind` and `event`, the event as canonical JSON (see
samesim.domain.canonical). trace_events(series) decodes them back to dicts:

    {"kind": "start",   "seq", "t"}
    {"kind": "send",    "seq", "t", "from", "to", "id", "broadcast", "payload", "arrive"}
    {"kind": "deliver", "seq", "t", "from", "to", "id", "broadcast", "payload"}
    {"kind": "lost",    "seq", "t", "from", "to", "id", "reason"}
    {"kind": "state",   "seq", "t", "agent", "state"}
    {"kind": "timer",   "seq", "t", "agent", "tag"}
    {"kind": "change",  "seq", "t", "fail", "recover", "join", "add_edges", "remove_edges"}
    {"kind": "tick",    "seq", "t"}
    {"kind": "end",     "seq", "t"}

"send" is the moment a message leaves (t) and when it is due (arrive, or
null if after the run ends); "deliver" or "lost" is what became of it.
"from" is the sender and "to" the agent this copy travels to. "id" is the
message id the behavior assigned; a broadcast is one message, so its copies
share an id.

The series metadata holds the starting picture: `schema`, `topology` (each
agent with its sorted neighbors), `positions` (if the topology has them)
and `initial_states`.

Recording changes nothing about the run: the digest is the same with or
without it. Cost: one JSON serialization per event, and memory for every
event -- leave it out of large runs and benchmarks.

Pair it with persistence.jsonl_trace.JsonlTraceExporter to write the trace
to a file.

Config keys: none.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ...domain.canonical import canonical, canonical_json
from ...domain.event import (
    AgentStateChangedEvent,
    Event,
    MessageDeliveredEvent,
    MessageLostEvent,
    MessageSentEvent,
    SimulationEndedEvent,
    SimulationStartedEvent,
    TickEvent,
    TimerFiredEvent,
    TopologyChangeEvent,
)
from ...domain.ids import AgentId, MetricName, VirtualTime
from ...domain.metric import MetricSeries
from ...domain.topology import TopologyGraph
from ...ports.metric_collector import MetricCollectorPort

SERIES_NAME = "event_trace"
TRACE_SCHEMA = "samesim.trace/1"


def trace_events(series: MetricSeries) -> list[dict[str, Any]]:
    """The recorded events as dicts, in dispatch order."""
    return [json.loads(dict(r.tags)["event"]) for r in series.records]


class EventTraceMetric(MetricCollectorPort):
    """Records every event of the run, in dispatch order."""

    def __init__(self) -> None:
        self._series = MetricSeries(name=MetricName(SERIES_NAME))

    def on_setup(
        self,
        topology: TopologyGraph,
        initial_states: Mapping[AgentId, Mapping[str, Any]],
    ) -> None:
        ids = sorted(topology.all_agent_ids())
        positions = None
        if topology.positions is not None:
            positions = {str(int(a)): list(topology.positions[a]) for a in ids if a in topology.positions}
        self._series.metadata.update({
            "schema": TRACE_SCHEMA,
            "topology": [[int(a), sorted(int(b) for b in topology.neighbors(a))] for a in ids],
            "positions": positions,
            "initial_states": {str(int(a)): canonical(s) for a, s in initial_states.items()},
        })

    def subscribed_events(self) -> frozenset[type[Event]]:
        return frozenset({
            SimulationStartedEvent,
            TickEvent,
            MessageSentEvent,
            MessageDeliveredEvent,
            MessageLostEvent,
            AgentStateChangedEvent,
            TimerFiredEvent,
            TopologyChangeEvent,
            SimulationEndedEvent,
        })

    def on_event(self, event: Event, virtual_time: VirtualTime) -> None:
        t = float(virtual_time)
        if isinstance(event, MessageSentEvent):
            m = event.message
            self._add("send", t, {
                "from": int(m.sender_id), "to": int(event.recipient_id), "id": int(m.message_id),
                "broadcast": m.broadcast, "payload": m.payload,
                "arrive": None if event.arrival_time is None else float(event.arrival_time)})
        elif isinstance(event, MessageDeliveredEvent):
            m = event.message
            self._add("deliver", t, {
                "from": int(m.sender_id), "to": int(event.recipient_id), "id": int(m.message_id),
                "broadcast": m.broadcast, "payload": m.payload})
        elif isinstance(event, MessageLostEvent):
            m = event.message
            self._add("lost", t, {
                "from": int(m.sender_id), "to": int(event.recipient_id), "id": int(m.message_id),
                "reason": event.reason})
        elif isinstance(event, AgentStateChangedEvent):
            self._add("state", t, {"agent": int(event.agent_id), "state": event.state_snapshot})
        elif isinstance(event, TimerFiredEvent):
            self._add("timer", t, {"agent": int(event.agent_id), "tag": event.tag})
        elif isinstance(event, TopologyChangeEvent):
            c = event.change
            self._add("change", t, {
                "fail": sorted(int(a) for a in c.fail), "recover": sorted(int(a) for a in c.recover),
                "join": sorted(int(a) for a in c.join),
                "add_edges": sorted([int(a), int(b)] for a, b in c.add_edges),
                "remove_edges": sorted([int(a), int(b)] for a, b in c.remove_edges)})
        elif isinstance(event, SimulationStartedEvent):
            self._add("start", t, {})
        elif isinstance(event, TickEvent):
            self._add("tick", t, {})
        elif isinstance(event, SimulationEndedEvent):
            self._add("end", t, {})

    def _add(self, kind: str, t: float, fields: dict[str, Any]) -> None:
        seq = len(self._series.records)
        record = {"kind": kind, "seq": seq, "t": t, **fields}
        self._series.append(virtual_time=VirtualTime(t), value=float(seq),
                            kind=kind, event=canonical_json(record))

    def get_series(self) -> MetricSeries:
        return self._series

    def reset(self) -> None:
        metadata = dict(self._series.metadata)
        self._series = MetricSeries(name=MetricName(SERIES_NAME), metadata=metadata)
