"""
ErdosRenyiTopology — Erdős–Rényi G(n, p) random graph.

Each pair of agents is connected independently with probability p.
The resulting graph is undirected and may be disconnected for small p.

Configuration (plugin_configs.ErdosRenyiTopology):
    edge_probability: float  — probability of an edge between any pair (default 0.01)

Notes:
    - For N=1000, p=0.01 gives ~5 neighbors per agent (sparse but well-connected)
    - Expected degree: (N-1) * p
    - Graph is guaranteed connected only for p > ln(N)/N ≈ 0.0069 at N=1000

Generation algorithm (Batagelj & Brandes, "Efficient generation of large
random networks", 2005):
    A naive generator checks every one of the n*(n-1)/2 possible pairs --
    O(n^2) regardless of p, which dominates runtime at scale even for very
    sparse graphs (benchmarked in experiments/scaling_benchmark/). Instead,
    this jumps directly from one edge to the next: since each pair is an
    independent Bernoulli(p) trial, the number of non-edges between
    consecutive edges follows a geometric distribution, so the next edge's
    offset can be drawn in O(1) rather than rejection-sampled pair by pair.
    Expected running time is O(n + m) where m is the number of edges
    actually created -- for the same n and p this produces a different
    graph than the previous pair-by-pair version (it consumes the RNG
    stream differently), but an equally valid draw from G(n,p): determinism
    (same seed -> same graph, always) is preserved going forward, it is
    only cross-version bit-for-bit reproducibility that changes. See the
    experiments/scaling_benchmark/ write-up for the before/after numbers.
"""
from __future__ import annotations

import random
from typing import Any

from ...domain import portable_math
from ...domain.ids import AgentId
from ...domain.topology import TopologyGraph
from ...ports.topology_generator import TopologyGeneratorPort


class ErdosRenyiTopology(TopologyGeneratorPort):
    """Erdős–Rényi G(n,p) random graph topology generator."""

    def generate(
        self,
        agent_ids: list[AgentId],
        config: dict[str, Any],
        rng: random.Random,
    ) -> TopologyGraph:
        edge_probability = float(config.get("edge_probability", 0.01))
        n = len(agent_ids)

        adjacency: dict[AgentId, set[AgentId]] = {aid: set() for aid in agent_ids}

        if n < 2:
            return TopologyGraph(
                agent_ids=frozenset(agent_ids),
                adjacency={k: frozenset(v) for k, v in adjacency.items()},
            )

        if edge_probability <= 0.0:
            pass  # no edges
        elif edge_probability >= 1.0:
            for i in range(n):
                for j in range(i + 1, n):
                    adjacency[agent_ids[i]].add(agent_ids[j])
                    adjacency[agent_ids[j]].add(agent_ids[i])
        else:
            log_not_p = portable_math.log(1.0 - edge_probability)
            v = 1
            w = -1
            while v < n:
                w = w + 1 + int(portable_math.log(1.0 - rng.random()) / log_not_p)
                while w >= v and v < n:
                    w -= v
                    v += 1
                if v < n:
                    adjacency[agent_ids[v]].add(agent_ids[w])
                    adjacency[agent_ids[w]].add(agent_ids[v])

        return TopologyGraph(
            agent_ids=frozenset(agent_ids),
            adjacency={k: frozenset(v) for k, v in adjacency.items()},
        )
