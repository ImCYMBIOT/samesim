"""
GeometricTopology — agents placed in a rectangle, linked when close enough.

A random geometric graph: every agent gets a position, and two agents are
neighbors when the distance between them is at most `radius`. The usual
model of a wireless or sensor network, where a link exists because two
nodes are in range of each other. The graph is undirected and may be
disconnected for a small radius.

The positions are kept on the graph (TopologyGraph.positions), so a
communication protocol or a metric can use distances -- for example a
delay proportional to distance.

Configuration (plugin_configs.GeometricTopology):
    radius: float     — link range, > 0 (required)
    width: float      — extent in x, > 0 (default 1.0)
    height: float     — extent in y, > 0 (default 1.0)
    positions: list   — one [x, y] per agent, in agent order, to place the
                        agents yourself instead of uniformly at random
                        (default: random; width and height are then unused)

Notes:
    - Expected degree for random placement, away from the border:
      (N-1) * pi * radius^2 / (width * height).
    - Distances are compared squared (dx*dx + dy*dy <= radius*radius), which
      uses only IEEE-754 multiply and add, so the same seed gives the same
      graph on every platform.
    - Generation buckets agents into radius-sized cells, so it costs
      O(N + links), not a check of every pair.
"""
from __future__ import annotations

import math
import random
from typing import Any

from ...domain.ids import AgentId
from ...domain.topology import TopologyGraph
from ...ports.topology_generator import TopologyGeneratorPort


def _positive(config: dict[str, Any], key: str, default: float | None) -> float:
    value = config.get(key, default)
    if value is None:
        raise ValueError(f"GeometricTopology: '{key}' is required")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"GeometricTopology: '{key}' must be a finite number > 0, got {value!r}")
    return float(value)


class GeometricTopology(TopologyGeneratorPort):
    """Random geometric graph: neighbors are the agents within `radius`."""

    def generate(
        self,
        agent_ids: list[AgentId],
        config: dict[str, Any],
        rng: random.Random,
    ) -> TopologyGraph:
        radius = _positive(config, "radius", None)
        given = config.get("positions")
        if given is None:
            width = _positive(config, "width", 1.0)
            height = _positive(config, "height", 1.0)
            points = [(rng.random() * width, rng.random() * height) for _ in agent_ids]
        else:
            if not isinstance(given, (list, tuple)) or len(given) != len(agent_ids):
                raise ValueError(
                    f"GeometricTopology: 'positions' must list one [x, y] per agent "
                    f"({len(agent_ids)}), got {len(given) if isinstance(given, (list, tuple)) else given!r}"
                )
            points = []
            for i, xy in enumerate(given):
                ok = (isinstance(xy, (list, tuple)) and len(xy) == 2 and all(
                    isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(c) for c in xy))
                if not ok:
                    raise ValueError(f"GeometricTopology: positions[{i}] must be [x, y] numbers, got {xy!r}")
                points.append((float(xy[0]), float(xy[1])))

        # Bucket the points into square cells one radius wide: an agent's
        # neighbors can only be in its own cell or the eight around it, so
        # the cost is O(N + links) instead of a check of every pair.
        limit = radius * radius
        cells: dict[tuple[int, int], list[int]] = {}
        for i, (x, y) in enumerate(points):
            cells.setdefault((math.floor(x / radius), math.floor(y / radius)), []).append(i)
        neighbors: dict[AgentId, set[AgentId]] = {a: set() for a in agent_ids}
        for (cx, cy), members in cells.items():
            for ox in (-1, 0, 1):
                for oy in (-1, 0, 1):
                    others = cells.get((cx + ox, cy + oy))
                    if others is None:
                        continue
                    for i in members:
                        ax, ay = points[i]
                        for j in others:
                            if j <= i:
                                continue  # each pair once, from its lower index
                            dx, dy = points[j][0] - ax, points[j][1] - ay
                            if dx * dx + dy * dy <= limit:
                                neighbors[agent_ids[i]].add(agent_ids[j])
                                neighbors[agent_ids[j]].add(agent_ids[i])
        return TopologyGraph(
            agent_ids=frozenset(agent_ids),
            adjacency={a: frozenset(s) for a, s in neighbors.items()},
            positions=dict(zip(agent_ids, points)),
        )
