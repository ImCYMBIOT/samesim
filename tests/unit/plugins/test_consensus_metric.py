"""ConsensusMetric: running-agent agreement, all-agent agreement, and drift."""
from __future__ import annotations

from simul8.domain.event import AgentStateChangedEvent, TickEvent, TopologyChangeEvent
from simul8.domain.ids import AgentId, EventId, VirtualTime
from simul8.domain.topology import TopologyGraph
from simul8.domain.topology_change import TopologyChange
from simul8.plugins.metrics.consensus import ConsensusMetric

A, B, C = AgentId(0), AgentId(1), AgentId(2)
GRAPH = TopologyGraph(agent_ids=frozenset({A, B, C}),
                      adjacency={A: frozenset({B}), B: frozenset({A, C}), C: frozenset({B})})


def _metric(values=(0.0, 3.0, 6.0)) -> ConsensusMetric:
    m = ConsensusMetric()
    m.on_setup(GRAPH, {A: {"value": values[0]}, B: {"value": values[1]}, C: {"value": values[2]}})
    return m


def _tick(m, t):
    m.on_event(TickEvent(event_id=EventId(0), virtual_time=VirtualTime(t), source_id=None), t)
    rec = m.get_series().records[-1]
    return rec.value, {k: v for k, v in rec.tags}


def _set(m, agent, value, t):
    m.on_event(AgentStateChangedEvent(event_id=EventId(0), virtual_time=VirtualTime(t), source_id=agent,
                                      agent_id=agent, state_snapshot={"value": value}), t)


def _churn(m, t, **change):
    m.on_event(TopologyChangeEvent(event_id=EventId(0), virtual_time=VirtualTime(t), source_id=None,
                                   change=TopologyChange(**change)), t)


def test_without_churn_both_variances_agree_and_drift_is_zero():
    m = _metric()
    var, tags = _tick(m, 0.0)
    assert var == 6.0 and float(tags["all_variance"]) == 6.0
    assert float(tags["mean"]) == 3.0 and float(tags["drift"]) == 0.0
    assert tags["running"] == "3"


def test_a_failed_agents_stale_value_counts_only_in_all_variance():
    m = _metric()
    _churn(m, 1.0, fail=frozenset({C}))
    _set(m, A, 1.5, 1.0)
    _set(m, B, 1.5, 1.0)
    var, tags = _tick(m, 1.0)
    assert var == 0.0, "the running agents agree"
    assert float(tags["all_variance"]) == 4.5, "C still holds 6.0"
    assert float(tags["drift"]) == -1.5 and tags["running"] == "2"

    _churn(m, 2.0, recover=frozenset({C}))
    var, tags = _tick(m, 2.0)
    assert var == 4.5 and tags["running"] == "3", "a recovered agent counts again"


def test_state_without_a_numeric_value_is_ignored():
    m = _metric()
    _set(m, A, "not a number", 1.0)
    var, _ = _tick(m, 1.0)
    assert var == 6.0
