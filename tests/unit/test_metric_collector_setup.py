"""
register_metric_collectors(): the only way a collector sees the starting picture.

Guards the replacement for the old duck-typed configure() back door, which
handed plugins the live AgentRegistry and TopologyManager.
"""
from __future__ import annotations

import pytest

from samesim.app.experiment_runner import register_metric_collectors
from samesim.core.agent_registry import AgentRegistry
from samesim.domain.event import Event
from samesim.domain.ids import MetricName
from samesim.domain.metric import MetricSeries
from samesim.domain.state import AgentState
from samesim.domain.topology import TopologyGraph
from samesim.ports.metric_collector import MetricCollectorPort


class _Recorder(MetricCollectorPort):
    def __init__(self) -> None:
        self.seen = None

    def on_setup(self, topology, initial_states) -> None:
        self.seen = (topology, initial_states)

    def subscribed_events(self) -> frozenset[type[Event]]:
        return frozenset()

    def on_event(self, event, virtual_time) -> None: ...

    def get_series(self) -> MetricSeries:
        return MetricSeries(name=MetricName("recorder"))

    def reset(self) -> None: ...


def _registry_and_graph():
    registry = AgentRegistry()
    ids = [registry.create_agent(initial_state=AgentState(data={"x": i})) for i in range(3)]
    graph = TopologyGraph(agent_ids=frozenset(ids), adjacency={a: frozenset() for a in ids})
    return registry, graph, ids


def test_collector_receives_topology_and_initial_states_in_id_order():
    registry, graph, ids = _registry_and_graph()
    recorder = _Recorder()
    register_metric_collectors([recorder], registry, graph)

    topology, states = recorder.seen
    assert topology is graph
    assert list(states) == ids
    assert [states[a]["x"] for a in ids] == [0, 1, 2]


def test_initial_states_are_read_only():
    """A metric must not be able to reach back and alter the simulation."""
    registry, graph, ids = _registry_and_graph()
    recorder = _Recorder()
    register_metric_collectors([recorder], registry, graph)
    _, states = recorder.seen

    with pytest.raises(TypeError):
        states[ids[0]] = {}
    with pytest.raises(TypeError):
        states[ids[0]]["x"] = 99
    assert registry.get(ids[0]).state.get("x") == 0


def test_leftover_configure_hook_fails_loudly():
    """A collector written against the removed hook must not silently run.

    Otherwise configure() would simply never be called and the metric would
    quietly report nothing -- the plausible-but-wrong failure mode.
    """
    class _Legacy(_Recorder):
        def configure(self, agent_registry, **kwargs) -> None: ...

    registry, graph, _ = _registry_and_graph()
    with pytest.raises(TypeError, match="on_setup"):
        register_metric_collectors([_Legacy()], registry, graph)
