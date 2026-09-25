"""Churn building blocks: TopologyChange, copy-on-write graphs, RNG streams,
ScheduledChurn and RandomChurn."""
from __future__ import annotations

import random
from types import MappingProxyType

import pytest

from simul8.core.randomness_manager import RandomnessManager
from simul8.core.topology_manager import TopologyManager
from simul8.domain.ids import AgentId
from simul8.domain.topology import TopologyGraph
from simul8.domain.topology_change import TopologyChange
from simul8.plugins.dynamics.random_churn import RandomChurn
from simul8.plugins.dynamics.scheduled import ScheduledChurn
from simul8.plugins.topologies.ring import RingTopology

IDS = [AgentId(i) for i in range(6)]


def _ring() -> TopologyGraph:
    return RingTopology().generate(IDS, {}, random.Random(1))


# --- TopologyChange ---------------------------------------------------------

def test_edges_are_undirected_and_normalized():
    c = TopologyChange(add_edges={(3, 1), (1, 3)})
    assert c.add_edges == frozenset({(AgentId(1), AgentId(3))})


@pytest.mark.parametrize("kwargs,match", [
    ({"fail": {1}, "recover": {1}}, "more than one of"),
    ({"fail": {2}, "join": {2}}, "more than one of"),
    ({"add_edges": {(1, 1)}}, "self-loop"),
    ({"add_edges": {(1, 2)}, "remove_edges": {(2, 1)}}, "both added and removed"),
])
def test_contradictory_changes_are_rejected(kwargs, match):
    with pytest.raises(ValueError, match=match):
        TopologyChange(**kwargs)


def test_structural_vs_liveness():
    assert TopologyChange().is_empty()
    assert not TopologyChange(fail={1}).is_structural
    assert TopologyChange(join={9}).is_structural


# --- TopologyManager.apply --------------------------------------------------

def test_apply_is_copy_on_write():
    tm = TopologyManager()
    tm.build(RingTopology(), IDS, {}, random.Random(1))
    before = tm.topology
    after = tm.apply(TopologyChange(join={6}, add_edges={(6, 0)}, remove_edges={(0, 1)}))
    assert before.neighbors(AgentId(0)) == frozenset({AgentId(1), AgentId(5)}), "old graph untouched"
    assert after.neighbors(AgentId(0)) == frozenset({AgentId(5), AgentId(6)})
    assert after.neighbors(AgentId(6)) == frozenset({AgentId(0)})
    assert after.neighbors(AgentId(1)) == frozenset({AgentId(2)})
    assert after.adjacency[AgentId(3)] is before.adjacency[AgentId(3)], "untouched sets are shared"


# --- RNG streams ------------------------------------------------------------

def test_named_streams_are_independent_of_everything_else():
    a, b = RandomnessManager(), RandomnessManager()
    a.initialize(42); b.initialize(42)
    s = a.stream("dynamics")
    for _ in range(1000):
        s.random()
    assert a.global_rng.random() == b.global_rng.random()
    assert a.get_agent_rng(AgentId(3)).random() == b.get_agent_rng(AgentId(3)).random()
    assert a.stream("dynamics").random() == b.stream("dynamics").random()
    assert a.stream("dynamics").random() != a.stream("other").random()


# --- ScheduledChurn ---------------------------------------------------------

def _states(**by_agent):
    return MappingProxyType({AgentId(int(k[1:])): MappingProxyType(v) for k, v in by_agent.items()})


def test_scheduled_timing_and_selectors():
    s = ScheduledChurn()
    s.initialize(_ring(), {"events": [
        {"at": 5.0, "fail": {"where": {"role": "leader"}}},
        {"at": 7.0, "recover": "all"},
        {"at": 9.0, "fail": {"where": {"role": "nobody"}}},
    ]}, random.Random(1))
    g = _ring()
    assert s.next_time(g, 0.0, frozenset()) == 5.0
    c = s.change(g, 5.0, _states(a0={"role": "follower"}, a1={"role": "leader"}), frozenset())
    assert c.fail == frozenset({AgentId(1)})
    assert s.next_time(g, 5.0, frozenset({AgentId(1)})) == 2.0
    c = s.change(g, 7.0, _states(a0={}, a1={}), frozenset({AgentId(1)}))
    assert c.recover == frozenset({AgentId(1)})
    c = s.change(g, 9.0, _states(a0={"role": "leader"}), frozenset())
    assert c.is_empty() and s.unmatched == [(9.0, "fail")]
    assert s.next_time(g, 9.0, frozenset()) is None


def test_failed_agents_cannot_be_selected_to_fail_again():
    s = ScheduledChurn()
    s.initialize(_ring(), {"events": [{"at": 1.0, "fail": {"where": {"role": "leader"}}}]}, random.Random(1))
    c = s.change(_ring(), 1.0, _states(a0={"role": "leader"}, a1={"role": "leader"}), frozenset({AgentId(0)}))
    assert c.fail == frozenset({AgentId(1)})


# --- RandomChurn ------------------------------------------------------------

def _simulate(churn, n, horizon):
    """Drive a RandomChurn by hand; return time-weighted mean fraction down."""
    g = RingTopology().generate([AgentId(i) for i in range(n)], {}, random.Random(1))
    failed, t, down_area = set(), 0.0, 0.0
    while True:
        d = churn.next_time(g, t, frozenset(failed))
        if d is None or t + d > horizon:
            down_area += len(failed) * (horizon - t)
            return down_area / (horizon * n)
        down_area += len(failed) * d
        t += d
        c = churn.change(g, t, {}, frozenset(failed))
        failed = (failed | set(c.fail)) - set(c.recover)


def test_random_churn_reaches_the_stationary_down_fraction():
    """Each agent alternates up (rate lambda to fail) and down (rate mu to
    recover): long-run fraction down = lambda / (lambda + mu) = 0.2."""
    rc = RandomChurn()
    rc.initialize(None, {"failure_rate": 0.05, "recovery_rate": 0.2}, random.Random(9))
    assert abs(_simulate(rc, n=50, horizon=20_000) - 0.2) < 0.01


def test_random_churn_respects_max_failed_and_start_after():
    rc = RandomChurn()
    rc.initialize(None, {"failure_rate": 1.0, "recovery_rate": 0.0, "max_failed": 3,
                         "start_after": 10.0}, random.Random(2))
    g = _ring()
    assert rc.next_time(g, 0.0, frozenset()) == 10.0
    failed, t = set(), 10.0
    for _ in range(3):
        t += rc.next_time(g, t, frozenset(failed))
        failed |= set(rc.change(g, t, {}, frozenset(failed)).fail)
    assert len(failed) == 3
    assert rc.next_time(g, t, frozenset(failed)) is None, "at the cap with no recovery: done"


@pytest.mark.parametrize("config,match", [
    ({"failure_rate": -1}, "rates must be >= 0"),
    ({"max_failed": -1}, "max_failed must be >= 0"),
    ({"start_after": -1}, "start_after must be >= 0"),
])
def test_random_churn_rejects_bad_config(config, match):
    with pytest.raises(ValueError, match=match):
        RandomChurn().initialize(None, config, random.Random(1))
