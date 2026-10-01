"""
ChurnMetric — how many agents are running, and how many messages churn has cost.

Samples at every tick: value = agents running (not failed), with tags
lost = messages lost so far (to failed recipients, or discarded from the
inbox of an agent that failed) and failed = agents currently down.

Config keys: none.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...domain.event import Event, MessageLostEvent, TickEvent, TopologyChangeEvent
from ...domain.ids import AgentId, MetricName, VirtualTime
from ...domain.metric import MetricSeries
from ...domain.topology import TopologyGraph
from ...ports.metric_collector import MetricCollectorPort

_NAME = MetricName("churn")


class ChurnMetric(MetricCollectorPort):
    """Running agents and cumulative lost messages, per tick."""

    def __init__(self) -> None:
        self._series = MetricSeries(name=_NAME)
        self._agents: set[AgentId] = set()
        self._failed: set[AgentId] = set()
        self._lost = 0

    def on_setup(self, topology: TopologyGraph, initial_states: Mapping[AgentId, Mapping[str, Any]]) -> None:
        self._agents = set(initial_states)

    def subscribed_events(self) -> frozenset[type[Event]]:
        return frozenset({TickEvent, TopologyChangeEvent, MessageLostEvent})

    def on_event(self, event: Event, virtual_time: VirtualTime) -> None:
        if isinstance(event, TopologyChangeEvent):
            c = event.change
            self._agents |= set(c.join)
            self._failed = (self._failed | set(c.fail)) - set(c.recover)
        elif isinstance(event, MessageLostEvent):
            self._lost += 1
        elif isinstance(event, TickEvent):
            self._series.append(virtual_time, float(len(self._agents) - len(self._failed)),
                                lost=str(self._lost), failed=str(len(self._failed)))

    def get_series(self) -> MetricSeries:
        return self._series

    def reset(self) -> None:
        self.__init__()
