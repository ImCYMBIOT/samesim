"""
External validation 4/5: leader election consensus time vs. graph diameter.

Not a comparison against another simulator -- against a graph-theoretic
invariant, computed with NetworkX for an independent, trusted reference.
LeaderElectionBehavior is max-ID flooding: each agent adopts the highest
candidate ID it has seen and rebroadcasts it every tick. This is a BFS-like
flood, so it has an exact theoretical bound: full consensus MUST be reached
by tick = diameter (the longest shortest-path distance between any two
nodes) -- the max ID needs at most `diameter` hops to reach the
farthest node, and with 1-tick delivery latency, `diameter` ticks to fully
propagate. Consensus reached strictly *before* diameter is expected and
fine (a node isn't always the eccentric-most distance away); consensus
reached *after* diameter would indicate a bug in the flooding logic itself.
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

import networkx as nx

sys.path.insert(0, str(Path(__file__).parent))
from samesim_harness import networkx_to_topology_graph, run_samesim  # noqa: E402

# Repo root, derived from this file so the script runs from any checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from samesim.domain.ids import AgentId  # noqa: E402
from samesim.plugins.behaviors.leader_election import LeaderElectionBehavior  # noqa: E402
from samesim.plugins.communication.gossip import GossipProtocol  # noqa: E402
from samesim.plugins.metrics.leader_metrics import LeaderConsensusMetric  # noqa: E402


def run_case(n: int, p: float, seed: int) -> dict:
    g_nx = nx.gnp_random_graph(n, p, seed=seed)
    if not nx.is_connected(g_nx):
        g_nx = g_nx.subgraph(max(nx.connected_components(g_nx), key=len)).copy()
        g_nx = nx.convert_node_labels_to_integers(g_nx)
    diameter = nx.diameter(g_nx)
    n_actual = g_nx.number_of_nodes()

    agent_ids = [AgentId(i) for i in range(n_actual)]
    graph = networkx_to_topology_graph(g_nx, agent_ids)

    series = run_samesim(
        graph=graph,
        behavior=LeaderElectionBehavior(),
        behavior_config={},
        comm_protocol=GossipProtocol(),
        comm_config={},
        metric_collectors=[LeaderConsensusMetric()],
        seed=seed,
        max_virtual_time=diameter + 10,  # generous margin past the theoretical bound
        name=f"leader_vs_diameter_n{n}_s{seed}",
    )
    consensus = series[0].records
    consensus_tick = next((r.virtual_time for r in consensus if r.value >= 0.999), None)

    return {
        "n": n_actual,
        "diameter": diameter,
        "consensus_tick": consensus_tick,
        "within_bound": consensus_tick is not None and consensus_tick <= diameter,
    }


if __name__ == "__main__":
    cases = [(50, 0.15), (100, 0.08), (200, 0.05), (500, 0.02), (1000, 0.012)]
    all_ok = True
    for n, p in cases:
        for seed in (1, 2, 3):
            r = run_case(n, p, seed)
            all_ok &= r["within_bound"]
            status = "PASS" if r["within_bound"] else "FAIL"
            print(f"[{status}] n={r['n']:>5} diameter={r['diameter']:>3} "
                  f"consensus_tick={r['consensus_tick']} seed={seed}")

    print()
    print("ALL WITHIN THEORETICAL BOUND (consensus_tick <= diameter)" if all_ok else "SOME EXCEEDED BOUND")
