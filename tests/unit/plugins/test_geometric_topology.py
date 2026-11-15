"""GeometricTopology: positions, and links exactly between agents in range."""
from __future__ import annotations

import random

import pytest

from samesim.core.topology_manager import TopologyManager
from samesim.domain.ids import AgentId
from samesim.domain.topology_change import TopologyChange
from samesim.plugins.topologies.geometric import GeometricTopology

IDS = [AgentId(i) for i in range(60)]


def _graph(config, seed=7, ids=IDS):
    return GeometricTopology().generate(ids, config, random.Random(seed))


def test_links_are_exactly_the_pairs_within_radius():
    g = _graph({"radius": 0.2})
    for a in IDS:
        for b in IDS:
            if a == b:
                continue
            (ax, ay), (bx, by) = g.position(a), g.position(b)
            in_range = (ax - bx) ** 2 + (ay - by) ** 2 <= 0.2 * 0.2
            assert (b in g.neighbors(a)) == in_range
            assert (b in g.neighbors(a)) == (a in g.neighbors(b))
        assert a not in g.neighbors(a)


def test_same_seed_same_graph_and_positions_inside_the_rectangle():
    a, b = _graph({"radius": 0.2, "width": 4, "height": 2}), _graph({"radius": 0.2, "width": 4, "height": 2})
    assert a.adjacency == b.adjacency and a.positions == b.positions
    assert a.adjacency != _graph({"radius": 0.2, "width": 4, "height": 2}, seed=8).adjacency
    assert all(0 <= x <= 4 and 0 <= y <= 2 for x, y in a.positions.values())


def test_given_positions_are_used_as_they_are():
    ids = IDS[:4]
    g = _graph({"radius": 1.0, "positions": [[0, 0], [1, 0], [0, 3], [5, 5]]}, ids=ids)
    assert g.position(ids[2]) == (0.0, 3.0)
    assert g.neighbors(ids[0]) == {ids[1]}           # exactly at the radius: linked
    assert g.neighbors(ids[2]) == g.neighbors(ids[3]) == frozenset()


def test_no_agents_and_one_agent():
    assert len(_graph({"radius": 1}, ids=[])) == 0
    assert _graph({"radius": 1}, ids=IDS[:1]).neighbors(IDS[0]) == frozenset()


@pytest.mark.parametrize("config, message", [
    ({}, "'radius' is required"),
    ({"radius": 0}, "'radius' must be"),
    ({"radius": True}, "'radius' must be"),
    ({"radius": 1, "width": -1}, "'width' must be"),
    ({"radius": 1, "height": float("inf")}, "'height' must be"),
    ({"radius": 1, "positions": [[0, 0]]}, "one \\[x, y\\] per agent"),
    ({"radius": 1, "positions": [[0, 0]] * 59 + [[0, "a"]]}, "positions\\[59\\]"),
])
def test_bad_options_are_named(config, message):
    with pytest.raises(ValueError, match=message):
        _graph(config)


def test_positions_survive_churn_and_newcomers_have_none():
    manager = TopologyManager()
    manager.build(GeometricTopology(), IDS, {"radius": 0.2}, random.Random(7))
    before = manager.topology
    after = manager.apply(TopologyChange(join=frozenset({AgentId(99)}),
                                         add_edges=frozenset({(AgentId(0), AgentId(99))})))
    assert after.position(IDS[3]) == before.position(IDS[3])
    assert after.position(AgentId(99)) is None
