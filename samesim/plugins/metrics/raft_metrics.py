"""
RaftElectionMetric — when leaders are elected, and whether Raft stays safe.

Records one row per election, at the exact virtual time an agent becomes
leader (value = the term it won). Raft's Election Safety property is that
at most one leader is elected in a given term; if a second, different agent
becomes leader in a term that already has one, a row tagged
event=SAFETY_VIOLATION is recorded as well.

Reads the "role" and "term" keys of agent state, as produced by
RaftElectionBehavior.

Config keys: none.
"""
from __future__ import annotations

from ...domain.event import AgentStateChangedEvent, Event
from ...domain.ids import AgentId, MetricName, VirtualTime
from ...domain.metric import MetricSeries
from ...ports.metric_collector import MetricCollectorPort

_NAME = MetricName("raft_elections")


class RaftElectionMetric(MetricCollectorPort):
    """One row per election; flags two leaders in one term."""

    def __init__(self) -> None:
        self._series = MetricSeries(name=_NAME)
        self._roles: dict[AgentId, str] = {}
        self._leader_of_term: dict[int, AgentId] = {}

    def subscribed_events(self) -> frozenset[type[Event]]:
        return frozenset({AgentStateChangedEvent})

    def on_event(self, event: Event, virtual_time: VirtualTime) -> None:
        if not isinstance(event, AgentStateChangedEvent):
            return
        role = event.state_snapshot.get("role")
        previous = self._roles.get(event.agent_id)
        self._roles[event.agent_id] = role
        if role != "leader" or previous == "leader":
            return

        term = int(event.state_snapshot.get("term", -1))
        self._series.append(virtual_time, float(term), agent=str(int(event.agent_id)), event="elected")
        holder = self._leader_of_term.setdefault(term, event.agent_id)
        if holder != event.agent_id:
            self._series.append(virtual_time, float(term), agent=str(int(event.agent_id)),
                                event="SAFETY_VIOLATION")

    @property
    def violations(self) -> int:
        return sum(1 for r in self._series.records if dict(r.tags).get("event") == "SAFETY_VIOLATION")

    def get_series(self) -> MetricSeries:
        return self._series

    def reset(self) -> None:
        self._series = MetricSeries(name=_NAME)
        self._roles.clear()
        self._leader_of_term.clear()
