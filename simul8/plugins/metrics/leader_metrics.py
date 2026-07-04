"""
LeaderConsensusMetric — tracks progress of leader election consensus.

Calculates the percentage of agents that have adopted the true maximum leader ID.

Uses the registry two-phase initialization (`configure()`) to inspect the initial
states of all agents and discover the true maximum leader ID before the simulation starts.
"""
from __future__ import annotations

from ...core.agent_registry import AgentRegistry
from ...domain.event import AgentStateChangedEvent, Event, TickEvent
from ...domain.ids import AgentId, MetricName, VirtualTime
from ...domain.metric import MetricSeries
from ...ports.metric_collector import MetricCollectorPort


class LeaderConsensusMetric(MetricCollectorPort):
    """Tracks percentage of agents aligned on the true leader ID."""

    def __init__(self) -> None:
        self._series = MetricSeries(name=MetricName("leader_consensus_fraction"))
        self._registry: AgentRegistry | None = None
        self._true_leader_id: int | None = None
        # Track the last known leader ID for each agent
        self._agent_leaders: dict[AgentId, int] = {}

    def configure(self, agent_registry: AgentRegistry, **kwargs: Any) -> None:
        """Scan registry to discover the true maximum leader ID."""
        self._registry = agent_registry
        uids = []
        for agent in agent_registry.iter_agents():
            uid = agent.state.get("uid")
            if uid is not None:
                uids.append(uid)
                self._agent_leaders[agent.agent_id] = uid

        if uids:
            self._true_leader_id = max(uids)

    def subscribed_events(self) -> frozenset[type[Event]]:
        return frozenset({AgentStateChangedEvent, TickEvent})

    def on_event(self, event: Event, virtual_time: VirtualTime) -> None:
        if isinstance(event, AgentStateChangedEvent):
            leader = event.state_snapshot.get("leader_id")
            if leader is not None:
                self._agent_leaders[event.agent_id] = leader

        elif isinstance(event, TickEvent):
            if self._true_leader_id is not None and self._agent_leaders:
                correct_count = sum(
                    1 for val in self._agent_leaders.values()
                    if val == self._true_leader_id
                )
                fraction = correct_count / len(self._agent_leaders)
                self._series.append(virtual_time, fraction)

    def get_series(self) -> MetricSeries:
        return self._series

    def reset(self) -> None:
        self._series = MetricSeries(name=MetricName("leader_consensus_fraction"))
        self._true_leader_id = None
        self._agent_leaders.clear()
