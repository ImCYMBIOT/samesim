"""
QueueMetric — waits, sojourn times and the number in system for QueueBehavior.

Two kinds of row, told apart by the `kind` tag:

    kind=departure  one per served customer, at its departure time:
                    value = time spent waiting in the queue (Wq sample),
                    sojourn = time in system (W sample)
    kind=area       one per tick: value = the integral of the number in
                    system N(t) from 0 to now

The integral lets an analysis compute the time-average number in system
over ANY window [a, b] -- after a warm-up, say -- as
(area(b) - area(a)) / (b - a), which a per-tick average could not.

N(t) is the server's queue length (the customer in service is at its head).
Reads the "role", "queue", "served", "last_wait" and "last_sojourn" keys of
agent state, as produced by QueueBehavior.

Config keys: none.
"""
from __future__ import annotations

from ...domain.event import AgentStateChangedEvent, Event, TickEvent
from ...domain.ids import MetricName, VirtualTime
from ...domain.metric import MetricSeries
from ...ports.metric_collector import MetricCollectorPort

_NAME = MetricName("queue")


class QueueMetric(MetricCollectorPort):
    """Per-customer waits and the integral of the number in system."""

    def __init__(self) -> None:
        self._series = MetricSeries(name=_NAME)
        self._served = 0
        self._in_system = 0
        self._area = 0.0
        self._last_t = 0.0

    def subscribed_events(self) -> frozenset[type[Event]]:
        return frozenset({AgentStateChangedEvent, TickEvent})

    def _advance(self, t: float) -> None:
        # N(t) is piecewise constant; accumulate in event order, which is
        # deterministic, so the sum is reproducible without fsum.
        self._area += self._in_system * (t - self._last_t)
        self._last_t = t

    def on_event(self, event: Event, virtual_time: VirtualTime) -> None:
        if isinstance(event, AgentStateChangedEvent):
            s = event.state_snapshot
            if s.get("role") != "server":
                return
            self._advance(float(virtual_time))
            self._in_system = len(s.get("queue") or ())
            served = s.get("served") or 0
            if served > self._served:
                self._served = served
                self._series.append(virtual_time, float(s.get("last_wait")),
                                    kind="departure", sojourn=repr(float(s.get("last_sojourn"))))
        elif isinstance(event, TickEvent):
            self._advance(float(virtual_time))
            self._series.append(virtual_time, self._area, kind="area", sojourn="")

    def get_series(self) -> MetricSeries:
        return self._series

    def reset(self) -> None:
        self.__init__()
