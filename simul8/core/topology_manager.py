"""
TopologyManager — builds and provides access to the agent network graph.

Owns the single TopologyGraph instance for the simulation.
All neighbor queries go through this module; no other module holds
a direct reference to the adjacency dict.
"""
from __future__ import annotations

import random

from ..domain.ids import AgentId
from ..domain.topology import TopologyGraph
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

    def neighbors(self, agent_id: AgentId) -> frozenset[AgentId]:
        """Return the neighbor set of an agent."""
        return self.topology.neighbors(agent_id)

    def agent_count(self) -> int:
        """Return the number of agents in the topology."""
        return len(self.topology)
