"""
GridTopology — connects agents in a 2D grid.

Supports optional toroidal wrapping (edges wrap around to form a torus).

Configuration:
    wrap: bool — if True, edges wrap around (default True)
"""
from __future__ import annotations

import math
import random
from typing import Any

from ...domain.ids import AgentId
from ...domain.topology import TopologyGraph
from ...ports.topology_generator import TopologyGeneratorPort


class GridTopology(TopologyGeneratorPort):
    """Grid topology: connects agents to their 4 cardinal neighbors."""

    def generate(
        self,
        agent_ids: list[AgentId],
        config: dict[str, Any],
        rng: random.Random,
    ) -> TopologyGraph:
        n = len(agent_ids)
        if n < 2:
            return TopologyGraph(
                agent_ids=frozenset(agent_ids),
                adjacency={aid: frozenset() for aid in agent_ids},
            )

        wrap = bool(config.get("wrap", True))

        # Determine grid dimensions
        cols = int(math.sqrt(n))
        if cols < 1:
            cols = 1
        rows = n // cols
        if rows * cols < n:
            rows += 1

        # Map agent ID to (row, col)
        coords: dict[AgentId, tuple[int, int]] = {}
        grid: dict[tuple[int, int], AgentId] = {}
        for idx, agent_id in enumerate(agent_ids):
            r = idx // cols
            c = idx % cols
            coords[agent_id] = (r, c)
            grid[(r, c)] = agent_id

        adjacency: dict[AgentId, set[AgentId]] = {aid: set() for aid in agent_ids}

        # Directions: Up, Down, Left, Right
        dirs = [(-1, 0), (1, 0), (0, -1), (0, 1)]

        for agent_id, (r, c) in coords.items():
            for dr, dc in dirs:
                nr = r + dr
                nc = c + dc

                if wrap:
                    nr = nr % rows
                    nc = nc % cols
                    neighbor_id = grid.get((nr, nc))
                    if neighbor_id is not None and neighbor_id != agent_id:
                        adjacency[agent_id].add(neighbor_id)
                else:
                    if 0 <= nr < rows and 0 <= nc < cols:
                        neighbor_id = grid.get((nr, nc))
                        if neighbor_id is not None and neighbor_id != agent_id:
                            adjacency[agent_id].add(neighbor_id)

        return TopologyGraph(
            agent_ids=frozenset(agent_ids),
            adjacency={k: frozenset(v) for k, v in adjacency.items()},
        )
