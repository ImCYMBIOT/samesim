"""
TopologyGraph — the immutable adjacency-list graph of agent connections.

The graph is generated at simulation start by a TopologyGeneratorPort plugin.
A graph is never modified in place: when churn changes the edges
(TopologyDynamicsPort), TopologyManager builds a new graph (copy-on-write),
so a reference a plugin holds stays a consistent snapshot.

The engine never knows what the topology *means* — that is the domain plugin's concern.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .ids import AgentId


@dataclass(frozen=True)
class TopologyGraph:
    """Immutable adjacency-list representation of the agent network.

    Attributes:
        agent_ids:  The complete set of agent IDs in the simulation.
        adjacency:  Maps each AgentId to the frozenset of its neighbors.
                    Excluded from __hash__ and __eq__ because dicts are
                    unhashable; identity is determined by agent_ids alone.
        positions:  Optional coordinates per agent (a tuple of floats), set
                    by spatial generators such as GeometricTopology. The
                    engine never reads them; protocols and metrics may.

    Access API:
        Use neighbors() and degree() rather than reading adjacency directly.
        This keeps the internal structure replaceable without API changes.
    """

    agent_ids: frozenset[AgentId]
    # Excluded from hash/compare: dict is unhashable and we never need to
    # put TopologyGraph in a set or use it as a dict key.
    adjacency: dict[AgentId, frozenset[AgentId]] = field(
        repr=False, hash=False, compare=False
    )
    # Where each agent is, for topologies that live in space. None for a
    # purely abstract graph. Agents that join later have no entry.
    positions: Mapping[AgentId, tuple[float, ...]] | None = field(
        default=None, repr=False, hash=False, compare=False
    )

    def position(self, agent_id: AgentId) -> tuple[float, ...] | None:
        """The agent's coordinates, or None if this graph has none for it."""
        return None if self.positions is None else self.positions.get(agent_id)

    def neighbors(self, agent_id: AgentId) -> frozenset[AgentId]:
        """Return the frozenset of agents connected to agent_id."""
        return self.adjacency.get(agent_id, frozenset())

    def degree(self, agent_id: AgentId) -> int:
        """Return the number of neighbors of agent_id."""
        return len(self.neighbors(agent_id))

    def all_agent_ids(self) -> frozenset[AgentId]:
        """Return all agent IDs in the graph."""
        return self.agent_ids

    def __len__(self) -> int:
        return len(self.agent_ids)
