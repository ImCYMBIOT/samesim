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
"""
from __future__ import annotations

import random
from typing import Any

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

        # Build adjacency sets (mutable during construction)
        adjacency: dict[AgentId, set[AgentId]] = {aid: set() for aid in agent_ids}

        for i in range(n):
            for j in range(i + 1, n):
                if rng.random() < edge_probability:
                    adjacency[agent_ids[i]].add(agent_ids[j])
                    adjacency[agent_ids[j]].add(agent_ids[i])

        return TopologyGraph(
            agent_ids=frozenset(agent_ids),
            adjacency={k: frozenset(v) for k, v in adjacency.items()},
        )
