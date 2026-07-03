"""
TopologyGeneratorPort — the contract for generating the agent network graph.

Purpose:
    Produces the initial TopologyGraph from a list of agent IDs.

Contracts:
    - MUST NOT import from simul8.core or simul8.app
    - generate() MUST be a pure function: same inputs → same output
    - generate() MUST return a valid graph (every agent ID in adjacency)

Extension:
    Implement to add new topologies: Ring, Grid, Mesh, Scale-Free,
    Small-World, Custom Graph, SDN fabric, etc.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from random import Random
from typing import Any

from ..domain.ids import AgentId
from ..domain.topology import TopologyGraph


class TopologyGeneratorPort(ABC):
    """Abstract contract for generating the initial agent network.

    Called once during experiment initialization. The returned graph
    is immutable for the duration of the simulation.
    """

    @abstractmethod
    def generate(
        self,
        agent_ids: list[AgentId],
        config: dict[str, Any],
        rng: Random,
    ) -> TopologyGraph:
        """Generate and return an immutable topology graph.

        Args:
            agent_ids: Ordered list of all agent IDs in the simulation.
            config:    Plugin-specific config from plugin_configs[ClassName].
            rng:       Seeded RNG for any random graph construction.

        Returns:
            A TopologyGraph where every agent_id appears in adjacency.
        """
        ...
