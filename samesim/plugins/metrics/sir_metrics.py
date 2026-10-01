"""
SIR Epidemic Metric Collectors.

Defines three separate metric collectors, one for each state:
    - SirSusceptibleMetric
    - SirInfectedMetric
    - SirRecoveredMetric

Each collector subscribes to AgentStateChangedEvent and TickEvent,
tracks agent states, and exports a single MetricSeries.

Config keys: none.
"""
from __future__ import annotations

from ...domain.event import AgentStateChangedEvent, Event, TickEvent
from ...domain.ids import AgentId, MetricName, VirtualTime
from ...domain.metric import MetricSeries
from ...ports.metric_collector import MetricCollectorPort


class SirSusceptibleMetric(MetricCollectorPort):
    """Tracks count of Susceptible (S) agents over virtual time."""

    def __init__(self) -> None:
        self._series = MetricSeries(name=MetricName("sir_susceptible"))
        self._agent_states: dict[AgentId, str] = {}

    def subscribed_events(self) -> frozenset[type[Event]]:
        return frozenset({AgentStateChangedEvent, TickEvent})

    def on_event(self, event: Event, virtual_time: VirtualTime) -> None:
        if isinstance(event, AgentStateChangedEvent):
            status = event.state_snapshot.get("status")
            if status is not None:
                self._agent_states[event.agent_id] = status

        elif isinstance(event, TickEvent):
            count = sum(1 for s in self._agent_states.values() if s == "S")
            self._series.append(virtual_time, float(count))

    def get_series(self) -> MetricSeries:
        return self._series

    def reset(self) -> None:
        self._series = MetricSeries(name=MetricName("sir_susceptible"))
        self._agent_states.clear()


class SirInfectedMetric(MetricCollectorPort):
    """Tracks count of Infected (I) agents over virtual time."""

    def __init__(self) -> None:
        self._series = MetricSeries(name=MetricName("sir_infected"))
        self._agent_states: dict[AgentId, str] = {}

    def subscribed_events(self) -> frozenset[type[Event]]:
        return frozenset({AgentStateChangedEvent, TickEvent})

    def on_event(self, event: Event, virtual_time: VirtualTime) -> None:
        if isinstance(event, AgentStateChangedEvent):
            status = event.state_snapshot.get("status")
            if status is not None:
                self._agent_states[event.agent_id] = status

        elif isinstance(event, TickEvent):
            count = sum(1 for s in self._agent_states.values() if s == "I")
            self._series.append(virtual_time, float(count))

    def get_series(self) -> MetricSeries:
        return self._series

    def reset(self) -> None:
        self._series = MetricSeries(name=MetricName("sir_infected"))
        self._agent_states.clear()


class SirRecoveredMetric(MetricCollectorPort):
    """Tracks count of Recovered (R) agents over virtual time."""

    def __init__(self) -> None:
        self._series = MetricSeries(name=MetricName("sir_recovered"))
        self._agent_states: dict[AgentId, str] = {}

    def subscribed_events(self) -> frozenset[type[Event]]:
        return frozenset({AgentStateChangedEvent, TickEvent})

    def on_event(self, event: Event, virtual_time: VirtualTime) -> None:
        if isinstance(event, AgentStateChangedEvent):
            status = event.state_snapshot.get("status")
            if status is not None:
                self._agent_states[event.agent_id] = status

        elif isinstance(event, TickEvent):
            count = sum(1 for s in self._agent_states.values() if s == "R")
            self._series.append(virtual_time, float(count))

    def get_series(self) -> MetricSeries:
        return self._series

    def reset(self) -> None:
        self._series = MetricSeries(name=MetricName("sir_recovered"))
        self._agent_states.clear()
