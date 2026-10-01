"""
VoterMetric — the voter model's opinion share and its martingale.

Samples at every tick: value = fraction of agents holding opinion 1, tagged
with weighted = the degree-weighted fraction sum_i d_i x_i / sum_i d_i,
the martingale whose initial value is the probability that opinion 1 wins
(see VoterBehavior). Degrees are those of the initial topology.

Reads the "opinion" key of agent state, as produced by VoterBehavior.

Config keys: none.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...domain.event import AgentStateChangedEvent, Event, TickEvent
from ...domain.ids import AgentId, MetricName, VirtualTime
from ...domain.metric import MetricSeries
from ...domain.topology import TopologyGraph
from ...ports.metric_collector import MetricCollectorPort

_NAME = MetricName("voter")


class VoterMetric(MetricCollectorPort):
    """Fraction holding opinion 1, plain and degree-weighted."""

    def __init__(self) -> None:
        self._series = MetricSeries(name=_NAME)
        self._degree: dict[AgentId, int] = {}
        self._opinion: dict[AgentId, int] = {}

    def on_setup(self, topology: TopologyGraph, initial_states: Mapping[AgentId, Mapping[str, Any]]) -> None:
        self._degree = {a: topology.degree(a) for a in topology.agent_ids}
        self._opinion = {a: s.get("opinion") for a, s in initial_states.items() if "opinion" in s}

    def subscribed_events(self) -> frozenset[type[Event]]:
        return frozenset({AgentStateChangedEvent, TickEvent})

    def on_event(self, event: Event, virtual_time: VirtualTime) -> None:
        if isinstance(event, AgentStateChangedEvent):
            if "opinion" in event.state_snapshot:
                self._opinion[event.agent_id] = event.state_snapshot["opinion"]
        elif isinstance(event, TickEvent) and self._opinion:
            ones = sum(1 for v in self._opinion.values() if v == 1)
            total_degree = sum(self._degree.get(a, 0) for a in self._opinion)
            weighted = (sum(self._degree.get(a, 0) for a, v in self._opinion.items() if v == 1)
                        / total_degree) if total_degree else 0.0
            self._series.append(virtual_time, ones / len(self._opinion), weighted=repr(weighted))

    def get_series(self) -> MetricSeries:
        return self._series

    def reset(self) -> None:
        self.__init__()
