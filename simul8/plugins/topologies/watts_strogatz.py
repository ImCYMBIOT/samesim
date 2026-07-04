"""
WattsStrogatzTopology — Watts-Strogatz small-world network generator.

Generates a small-world graph starting from a ring lattice where each agent is
connected to its k nearest neighbors, then rewiring edges with probability p.

Configuration:
    k: int — degree of each node in the initial ring lattice (must be even, default 4)
    rewire_probability: float — probability of rewiring each edge (default 0.1)
"""
from __future__ import annotations

import random
from typing import Any

from ...domain.ids import AgentId
from ...domain.topology import TopologyGraph
from ...ports.topology_generator import TopologyGeneratorPort


class WattsStrogatzTopology(TopologyGeneratorPort):
    """Watts-Strogatz small-world model."""

    def generate(
        self,
        agent_ids: list[AgentId],
        config: dict[str, Any],
        rng: random.Random,
    ) -> TopologyGraph:
        n = len(agent_ids)
        if n < 3:
            # Not enough agents to build a Watts-Strogatz lattice
            return TopologyGraph(
                agent_ids=frozenset(agent_ids),
                adjacency={aid: frozenset() for aid in agent_ids},
            )

        k = int(config.get("k", 4))
        p = float(config.get("rewire_probability", 0.1))

        # k must be even and less than N
        if k % 2 != 0:
            k = max(2, k - 1)
        k = min(k, n - 1)

        adjacency: dict[AgentId, set[AgentId]] = {aid: set() for aid in agent_ids}

        # 1. Create a regular ring lattice: each node connected to k/2 neighbors on each side
        half_k = k // 2
        for i in range(n):
            for step in range(1, half_k + 1):
                j = (i + step) % n
                u, v = agent_ids[i], agent_ids[j]
                adjacency[u].add(v)
                adjacency[v].add(u)

        # 2. Rewire edges with probability p
        # To avoid double-rewiring, we only rewire "forward" edges (i to (i + step) % n)
        for step in range(1, half_k + 1):
            for i in range(n):
                if rng.random() < p:
                    u = agent_ids[i]
                    v = agent_ids[(i + step) % n]

                    # Find a new target that is not u, and not already connected to u
                    possible_targets = [
                        target for target in agent_ids
                        if target != u and target not in adjacency[u]
                    ]

                    if possible_targets:
                        new_v = rng.choice(possible_targets)
                        # Remove old edge
                        adjacency[u].discard(v)
                        adjacency[v].discard(u)
                        # Add new edge
                        adjacency[u].add(new_v)
                        adjacency[new_v].add(u)

        return TopologyGraph(
            agent_ids=frozenset(agent_ids),
            adjacency={k: frozenset(v) for k, v in adjacency.items()},
        )
