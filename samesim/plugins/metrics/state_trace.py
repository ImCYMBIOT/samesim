"""
StateTraceMetric and TopologyMetric.

Used to collect node-level state traces and network topology structure.
This data is used by the visualizer to animate graph states over time.

Config keys: none.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...domain.event import AgentStateChangedEvent, Event, SimulationStartedEvent
from ...domain.ids import AgentId, MetricName, VirtualTime
from ...domain.metric import MetricSeries
from ...domain.topology import TopologyGraph
from ...ports.metric_collector import MetricCollectorPort


class TopologyMetric(MetricCollectorPort):
    """Logs the network topology edges at simulation start."""

    def __init__(self) -> None:
        self._series = MetricSeries(name=MetricName("topology"))
        self._topology: TopologyGraph | None = None

    def on_setup(
        self,
        topology: TopologyGraph,
        initial_states: Mapping[AgentId, Mapping[str, Any]],
    ) -> None:
        self._topology = topology

    def subscribed_events(self) -> frozenset[type[Event]]:
        return frozenset({SimulationStartedEvent})

    def on_event(self, event: Event, virtual_time: VirtualTime) -> None:
        if isinstance(event, SimulationStartedEvent) and self._topology is not None:
            topology = self._topology
            # Iterate through all agents and their neighbors to log edges
            seen_edges = set()
            for u in sorted(topology.all_agent_ids()):
                for v in sorted(topology.neighbors(u)):
                    # Undirected graph edge dedup
                    edge = tuple(sorted((int(u), int(v))))
                    if edge not in seen_edges:
                        seen_edges.add(edge)
                        self._series.append(
                            virtual_time=VirtualTime(0.0),
                            value=1.0,
                            source=str(edge[0]),
                            target=str(edge[1]),
                        )

    def get_series(self) -> MetricSeries:
        return self._series

    def reset(self) -> None:
        self._series = MetricSeries(name=MetricName("topology"))
        self._topology = None


class StateTraceMetric(MetricCollectorPort):
    """Tracks tick-by-tick state of every agent for network animation."""

    def __init__(self) -> None:
        self._series = MetricSeries(name=MetricName("state_trace"))

    def subscribed_events(self) -> frozenset[type[Event]]:
        return frozenset({AgentStateChangedEvent})

    def on_event(self, event: Event, virtual_time: VirtualTime) -> None:
        if isinstance(event, AgentStateChangedEvent):
            # Extract state representation based on active plugin
            snapshot = event.state_snapshot
            state_val = (
                snapshot.get("status")
                or snapshot.get("leader_id")
                or snapshot.get("value")
            )
            if state_val is not None:
                self._series.append(
                    virtual_time=virtual_time,
                    value=0.0,
                    agent_id=str(event.agent_id),
                    state=str(state_val),
                )

    def get_series(self) -> MetricSeries:
        return self._series

    def reset(self) -> None:
        self._series = MetricSeries(name=MetricName("state_trace"))
