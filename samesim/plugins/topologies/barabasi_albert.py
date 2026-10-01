"""
BarabasiAlbertTopology — Barabási-Albert preferential attachment scale-free network generator.

Generates a scale-free graph. A new node is added one by one and connected to m existing
nodes with probability proportional to their degree.

Configuration:
    m: int — number of edges to attach from a new node to existing nodes (default 2)
"""
from __future__ import annotations

import random
from typing import Any

from ...domain.ids import AgentId
from ...domain.topology import TopologyGraph
from ...ports.topology_generator import TopologyGeneratorPort


class BarabasiAlbertTopology(TopologyGeneratorPort):
    """Barabási-Albert scale-free model."""

    def generate(
        self,
        agent_ids: list[AgentId],
        config: dict[str, Any],
        rng: random.Random,
    ) -> TopologyGraph:
        n = len(agent_ids)
        m = int(config.get("m", 2))

        # Handle edge cases where number of agents is too small
        if n <= m:
            # Connect all nodes as a clique
            adjacency: dict[AgentId, set[AgentId]] = {aid: set() for aid in agent_ids}
            for i in range(n):
                for j in range(i + 1, n):
                    u, v = agent_ids[i], agent_ids[j]
                    adjacency[u].add(v)
                    adjacency[v].add(u)
            return TopologyGraph(
                agent_ids=frozenset(agent_ids),
                adjacency={k: frozenset(v) for k, v in adjacency.items()},
            )

        adjacency = {aid: set() for aid in agent_ids}

        # 1. Start with a clique of size m + 1
        m0 = m + 1
        for i in range(m0):
            for j in range(i + 1, m0):
                u, v = agent_ids[i], agent_ids[j]
                adjacency[u].add(v)
                adjacency[v].add(u)

        # Build the preferential attachment pool.
        # Repeating each node ID in the pool according to its degree.
        pool: list[AgentId] = []
        for i in range(m0):
            # Each node has degree m0 - 1 initially
            pool.extend([agent_ids[i]] * (m0 - 1))

        # 2. Add remaining nodes one by one
        for i in range(m0, n):
            new_node = agent_ids[i]
            targets: set[AgentId] = set()

            # We need to pick m distinct targets from the pool
            # Preferential attachment: probability is proportional to degree
            # (which matches frequency in pool)
            attempts = 0
            while len(targets) < m and attempts < 100:
                target = rng.choice(pool)
                if target != new_node and target not in targets:
                    targets.add(target)
                attempts += 1

            # Fallback if choice pool gets stuck (highly unlikely with large N)
            if len(targets) < m:
                remaining_candidates = [
                    t for t in agent_ids[:i] if t not in targets
                ]
                needed = m - len(targets)
                if remaining_candidates:
                    targets.update(rng.sample(remaining_candidates, min(needed, len(remaining_candidates))))

            # Establish connections
            for target in targets:
                adjacency[new_node].add(target)
                adjacency[target].add(new_node)
                # Update preferential attachment pool
                pool.append(new_node)
                pool.append(target)

        return TopologyGraph(
            agent_ids=frozenset(agent_ids),
            adjacency={k: frozenset(v) for k, v in adjacency.items()},
        )
