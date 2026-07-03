"""Unit tests for topology plugins: RingTopology and ErdosRenyiTopology."""
import random
import pytest
from simul8.domain.ids import AgentId
from simul8.plugins.topologies.ring import RingTopology
from simul8.plugins.topologies.random_graph import ErdosRenyiTopology


def make_ids(n: int) -> list[AgentId]:
    return [AgentId(i) for i in range(n)]


class TestRingTopology:
    def test_all_agents_present(self):
        g = RingTopology().generate(make_ids(10), {}, random.Random(0))
        assert g.agent_ids == frozenset(make_ids(10))

    def test_every_agent_has_two_neighbors(self):
        g = RingTopology().generate(make_ids(10), {}, random.Random(0))
        for aid in make_ids(10):
            assert g.degree(aid) == 2, f"Agent {aid} has degree {g.degree(aid)}"

    def test_ring_is_symmetric(self):
        g = RingTopology().generate(make_ids(10), {}, random.Random(0))
        for aid in make_ids(10):
            for nbr in g.neighbors(aid):
                assert aid in g.neighbors(nbr), "Ring must be symmetric"

    def test_single_agent_no_neighbors(self):
        g = RingTopology().generate(make_ids(1), {}, random.Random(0))
        assert g.degree(AgentId(0)) == 0

    def test_two_agents_connected(self):
        g = RingTopology().generate(make_ids(2), {}, random.Random(0))
        assert g.degree(AgentId(0)) == 2 or g.degree(AgentId(0)) == 1


class TestErdosRenyiTopology:
    def test_all_agents_present(self):
        agents = make_ids(100)
        g = ErdosRenyiTopology().generate(agents, {"edge_probability": 0.1}, random.Random(42))
        assert g.agent_ids == frozenset(agents)

    def test_symmetric(self):
        agents = make_ids(50)
        g = ErdosRenyiTopology().generate(agents, {"edge_probability": 0.1}, random.Random(42))
        for aid in agents:
            for nbr in g.neighbors(aid):
                assert aid in g.neighbors(nbr)

    def test_deterministic(self):
        agents = make_ids(100)
        config = {"edge_probability": 0.05}
        g1 = ErdosRenyiTopology().generate(agents, config, random.Random(7))
        g2 = ErdosRenyiTopology().generate(agents, config, random.Random(7))
        assert g1.adjacency == g2.adjacency

    def test_no_self_loops(self):
        agents = make_ids(50)
        g = ErdosRenyiTopology().generate(agents, {"edge_probability": 0.5}, random.Random(1))
        for aid in agents:
            assert aid not in g.neighbors(aid)

    def test_expected_degree_roughly_correct(self):
        """For p=0.1, N=200: expected degree ≈ (200-1)*0.1 ≈ 20."""
        n = 200
        agents = make_ids(n)
        g = ErdosRenyiTopology().generate(agents, {"edge_probability": 0.1}, random.Random(0))
        avg_degree = sum(g.degree(a) for a in agents) / n
        # Allow ±5 from expected 19.9
        assert 14 < avg_degree < 26, f"Unexpected average degree: {avg_degree}"
