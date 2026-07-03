"""
AgentRegistry — the registry of all agents in the simulation.

This is a lookup table, not a manager. Its only responsibilities are:
    - Create agents and assign unique IDs
    - Retrieve agents by ID
    - Iterate all agents
    - Update an agent's state

It does NOT: route messages, apply behaviors, collect metrics,
query the topology, or know what agents represent.

Naming: "Registry" is intentional. The word "Manager" would imply
behavior responsibility. This module has none.
"""
from __future__ import annotations

from typing import Iterator

from ..domain.agent import Agent
from ..domain.ids import AgentId
from ..domain.state import AgentState


class AgentRegistry:
    """Registry of all agents in the simulation.

    Purpose:
        Single source of truth for agent existence and current state.

    Responsibilities:
        Create, retrieve, iterate agents. Update agent state. Nothing else.

    Dependencies:
        None. Depends only on domain types.

    Lifecycle:
        Created once by ExperimentRunner. clear() is called between runs
        in multi-run experiments (future feature).
    """

    def __init__(self) -> None:
        self._agents: dict[AgentId, Agent] = {}
        self._next_id: int = 0

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------

    def create_agent(
        self,
        initial_state: AgentState | None = None,
        metadata: dict | None = None,
    ) -> AgentId:
        """Create a new agent and return its ID.

        Agent IDs are assigned sequentially starting from 0.

        Args:
            initial_state: The agent's initial state. Defaults to empty AgentState.
            metadata:      Arbitrary metadata dict (not read by the engine).

        Returns:
            The newly assigned AgentId.
        """
        agent_id = AgentId(self._next_id)
        self._next_id += 1
        self._agents[agent_id] = Agent(
            agent_id=agent_id,
            state=initial_state if initial_state is not None else AgentState(),
            metadata=metadata or {},
        )
        return agent_id

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get(self, agent_id: AgentId) -> Agent:
        """Return the Agent for the given ID.

        Args:
            agent_id: The ID to look up.

        Raises:
            KeyError: If agent_id does not exist in the registry.
        """
        try:
            return self._agents[agent_id]
        except KeyError:
            raise KeyError(f"Agent {agent_id} does not exist in the registry.")

    def iter_agents(self) -> Iterator[Agent]:
        """Iterate all agents in creation order."""
        return iter(self._agents.values())

    def all_agent_ids(self) -> list[AgentId]:
        """Return all agent IDs in creation order."""
        return list(self._agents.keys())

    # ------------------------------------------------------------------
    # State update
    # ------------------------------------------------------------------

    def update_state(self, agent_id: AgentId, new_state: AgentState) -> None:
        """Replace the state of an agent.

        Called by SimulationEngine after BehaviorPort.step() returns.

        Args:
            agent_id:  The agent to update.
            new_state: The new AgentState returned by the behavior.

        Raises:
            KeyError: If agent_id does not exist.
        """
        self._agents[agent_id].state = new_state

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Return the total number of registered agents."""
        return len(self._agents)

    def clear(self) -> None:
        """Remove all agents and reset the ID counter."""
        self._agents.clear()
        self._next_id = 0
