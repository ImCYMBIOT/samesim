"""
RingTopology — connects agents in a circular ring.

Each agent has exactly 2 neighbors: the agent immediately before and
after it in the agent_ids list. The last agent wraps to the first.

Properties:
    - Diameter: N/2 (for N agents)
    - Degree: 2 (uniform)
    - Connectivity: always connected

Configuration: none required.
"""
from __future__ import annotations

import random
from typing import Any

from ...domain.ids import AgentId
from ...domain.topology import TopologyGraph
from ...ports.topology_generator import TopologyGeneratorPort


class RingTopology(TopologyGeneratorPort):
    """Circular ring: each agent connected to its two immediate neighbors."""

    def generate(
        self,
        agent_ids: list[AgentId],
        config: dict[str, Any],
        rng: random.Random,
    ) -> TopologyGraph:
        n = len(agent_ids)
        if n < 2:
            # Degenerate: single agent with no neighbors
            return TopologyGraph(
                agent_ids=frozenset(agent_ids),
                adjacency={aid: frozenset() for aid in agent_ids},
            )

        adjacency: dict[AgentId, frozenset[AgentId]] = {}
        for i, agent_id in enumerate(agent_ids):
            left = agent_ids[(i - 1) % n]
            right = agent_ids[(i + 1) % n]
            adjacency[agent_id] = frozenset({left, right})

        return TopologyGraph(
            agent_ids=frozenset(agent_ids),
            adjacency=adjacency,
        )
