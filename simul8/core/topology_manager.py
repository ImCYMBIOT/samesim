"""
TopologyManager — builds and provides access to the agent network graph.

Owns the current TopologyGraph. Churn replaces it with a new graph via
apply() (copy-on-write); graphs themselves are never mutated.
All neighbor queries go through this module; no other module holds
a direct reference to the adjacency dict.
"""
from __future__ import annotations

import random

from ..domain.ids import AgentId
from ..domain.topology import TopologyGraph
from ..domain.topology_change import TopologyChange
from ..ports.topology_generator import TopologyGeneratorPort


class TopologyManager:
    """Builds and owns the agent network topology.

    Purpose:
        Single owner of the TopologyGraph. Provides the neighbor query API.

    Responsibilities:
        Build topology from a generator plugin. Answer neighbor queries.
        Nothing else.

    Dependencies:
        TopologyGeneratorPort (injected at build time via build()).

    Lifecycle:
        build() is called once during experiment initialization.
        After that, topology is read-only.
    """

    def __init__(self) -> None:
        self._topology: TopologyGraph | None = None

    def build(
        self,
        generator: TopologyGeneratorPort,
        agent_ids: list[AgentId],
        config: dict,
        rng: random.Random,
    ) -> None:
        """Generate and store the topology graph.

        Args:
            generator: The active topology generator plugin.
            agent_ids: All agent IDs (must match the registry).
            config:    Plugin-specific config for the generator.
            rng:       Seeded RNG from RandomnessManager.global_rng.
        """
        self._topology = generator.generate(agent_ids, config, rng)

    @property
    def topology(self) -> TopologyGraph:
        """The current topology graph.

        Raises:
            RuntimeError: If build() has not been called.
        """
        if self._topology is None:
            raise RuntimeError(
                "TopologyManager: topology not built. Call build() first."
            )
        return self._topology

    def apply(self, change: TopologyChange) -> TopologyGraph:
        """Apply joins and edge changes; return the new (immutable) graph.

        Copy-on-write: the previous TopologyGraph is untouched (anyone holding
        it keeps a consistent snapshot); only adjacency sets that change are
        rebuilt. Liveness (fail / recover) is not part of the graph.

        Raises:
            ValueError: for edges between unknown agents, adding an existing
                edge, or removing a missing one.
        """
        old = self.topology
        agent_ids = old.agent_ids | change.join
        adjacency = dict(old.adjacency)
        for a in change.join:
            adjacency.setdefault(a, frozenset())
        touched: dict[AgentId, set[AgentId]] = {}

        def nbrs(a: AgentId) -> set[AgentId]:
            if a not in touched:
                touched[a] = set(adjacency.get(a, frozenset()))
            return touched[a]

        for a, b in sorted(change.add_edges):
            if a not in agent_ids or b not in agent_ids:
                raise ValueError(f"add_edges: ({a}, {b}) names an unknown agent")
            if b in nbrs(a):
                raise ValueError(f"add_edges: ({a}, {b}) already exists")
            nbrs(a).add(b)
            nbrs(b).add(a)
        for a, b in sorted(change.remove_edges):
            if a not in agent_ids or b not in agent_ids or b not in nbrs(a):
                raise ValueError(f"remove_edges: ({a}, {b}) does not exist")
            nbrs(a).discard(b)
            nbrs(b).discard(a)
        for a, s in touched.items():
            adjacency[a] = frozenset(s)
        self._topology = TopologyGraph(agent_ids=agent_ids, adjacency=adjacency)
        return self._topology

    def neighbors(self, agent_id: AgentId) -> frozenset[AgentId]:
        """Return the neighbor set of an agent."""
        return self.topology.neighbors(agent_id)

    def agent_count(self) -> int:
        """Return the number of agents in the topology."""
        return len(self.topology)
