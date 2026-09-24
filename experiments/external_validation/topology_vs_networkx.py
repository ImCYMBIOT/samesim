"""
External validation 3/5: topology structural properties vs. NetworkX.

NetworkX is the standard reference graph library -- its generators and
statistics (degree distribution, clustering coefficient, diameter,
average shortest path length) are the field's baseline. Each of Simul8's
five topology generators is checked against NetworkX's equivalent
generator with matched parameters: not seed-for-seed identical graphs
(different RNG consumption), but statistically equivalent structural
properties over repeated draws.
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

import networkx as nx

# Repo root, derived from this file so the script runs from any checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from simul8.domain.ids import AgentId  # noqa: E402
from simul8.plugins.topologies.barabasi_albert import BarabasiAlbertTopology  # noqa: E402
from simul8.plugins.topologies.grid import GridTopology  # noqa: E402
from simul8.plugins.topologies.random_graph import ErdosRenyiTopology  # noqa: E402
from simul8.plugins.topologies.ring import RingTopology  # noqa: E402
from simul8.plugins.topologies.watts_strogatz import WattsStrogatzTopology  # noqa: E402

import random  # noqa: E402


def simul8_to_networkx(topology_graph, n):
    g = nx.Graph()
    g.add_nodes_from(range(n))
    for aid in topology_graph.agent_ids:
        for nbr in topology_graph.neighbors(aid):
            g.add_edge(int(aid), int(nbr))
    return g


def stats(g) -> dict:
    degrees = [d for _, d in g.degree()]
    result = {
        "avg_degree": statistics.mean(degrees),
        "clustering": nx.average_clustering(g),
    }
    if nx.is_connected(g):
        result["diameter"] = nx.diameter(g)
        result["avg_shortest_path"] = nx.average_shortest_path_length(g)
    else:
        largest_cc = g.subgraph(max(nx.connected_components(g), key=len))
        result["diameter"] = nx.diameter(largest_cc)
        result["avg_shortest_path"] = nx.average_shortest_path_length(largest_cc)
        result["note"] = f"disconnected, {nx.number_connected_components(g)} components -- stats on largest"
    return result


def report(name: str, simul8_g, nx_g):
    s1 = stats(simul8_g)
    s2 = stats(nx_g)
    print(f"--- {name} ---")
    for key in ("avg_degree", "clustering", "diameter", "avg_shortest_path"):
        v1, v2 = s1.get(key), s2.get(key)
        print(f"  {key:<20} simul8={v1:<10.4f} networkx={v2:<10.4f}")
    if "note" in s1:
        print("  simul8 note:", s1["note"])
    if "note" in s2:
        print("  networkx note:", s2["note"])
    print()


if __name__ == "__main__":
    n = 500
    seed = 42

    # Ring vs cycle_graph
    ring = RingTopology().generate([AgentId(i) for i in range(n)], {}, random.Random(seed))
    report("Ring vs. cycle_graph", simul8_to_networkx(ring, n), nx.cycle_graph(n))

    # Erdos-Renyi vs gnp_random_graph, avg degree 8
    p = 8.0 / (n - 1)
    er = ErdosRenyiTopology().generate([AgentId(i) for i in range(n)], {"edge_probability": p}, random.Random(seed))
    report("Erdos-Renyi vs. gnp_random_graph (avg deg 8)", simul8_to_networkx(er, n), nx.gnp_random_graph(n, p, seed=seed))

    # Watts-Strogatz vs watts_strogatz_graph
    ws = WattsStrogatzTopology().generate([AgentId(i) for i in range(n)], {"k": 8, "rewire_probability": 0.15}, random.Random(seed))
    report("Watts-Strogatz vs. watts_strogatz_graph (k=8, p=0.15)", simul8_to_networkx(ws, n), nx.watts_strogatz_graph(n, 8, 0.15, seed=seed))

    # Barabasi-Albert vs barabasi_albert_graph
    ba = BarabasiAlbertTopology().generate([AgentId(i) for i in range(n)], {"m": 4}, random.Random(seed))
    report("Barabasi-Albert vs. barabasi_albert_graph (m=4)", simul8_to_networkx(ba, n), nx.barabasi_albert_graph(n, 4, seed=seed))

    # Grid vs grid_2d_graph -- use a perfect square n for a clean comparison
    n_grid = 400  # 20x20
    grid = GridTopology().generate([AgentId(i) for i in range(n_grid)], {"wrap": True}, random.Random(seed))
    nx_grid_2d = nx.grid_2d_graph(20, 20, periodic=True)
    nx_grid = nx.convert_node_labels_to_integers(nx_grid_2d)
    report("Grid (20x20, wrap) vs. grid_2d_graph (periodic)", simul8_to_networkx(grid, n_grid), nx_grid)
