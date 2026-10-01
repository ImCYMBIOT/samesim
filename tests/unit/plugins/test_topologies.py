"""Unit tests for topology plugins: RingTopology and ErdosRenyiTopology."""
import random
import pytest
from samesim.domain.ids import AgentId
from samesim.plugins.topologies.ring import RingTopology
from samesim.plugins.topologies.random_graph import ErdosRenyiTopology


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

    def test_zero_probability_produces_no_edges(self):
        """edge_probability=0.0 is a boundary case for the direct-edge-sampling
        algorithm (log(1-p) would divide by zero) and must be special-cased."""
        agents = make_ids(50)
        g = ErdosRenyiTopology().generate(agents, {"edge_probability": 0.0}, random.Random(1))
        assert all(g.degree(a) == 0 for a in agents)

    def test_full_probability_produces_complete_graph(self):
        """edge_probability=1.0 is the other boundary case (log(1-p) undefined)."""
        n = 20
        agents = make_ids(n)
        g = ErdosRenyiTopology().generate(agents, {"edge_probability": 1.0}, random.Random(1))
        assert all(g.degree(a) == n - 1 for a in agents)

    def test_single_agent_no_neighbors(self):
        g = ErdosRenyiTopology().generate(make_ids(1), {"edge_probability": 0.5}, random.Random(1))
        assert g.degree(AgentId(0)) == 0

    def test_matches_expected_edge_count_at_scale(self):
        """Regression guard for the O(n+m) direct-edge-sampling algorithm:
        edge count should track p*n*(n-1)/2 closely, not just the degree average."""
        n = 5000
        p = 8.0 / (n - 1)
        agents = make_ids(n)
        g = ErdosRenyiTopology().generate(agents, {"edge_probability": p}, random.Random(42))
        actual_edges = sum(g.degree(a) for a in agents) // 2
        expected_edges = p * n * (n - 1) / 2
        assert 0.85 * expected_edges < actual_edges < 1.15 * expected_edges, (
            f"actual={actual_edges} expected~={expected_edges:.0f}"
        )
