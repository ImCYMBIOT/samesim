"""
TopologyDynamicsPort — the contract for churn: agents failing, recovering,
joining, and links appearing or disappearing during a run.

Optional. Without a dynamics plugin the topology and the set of running
agents are fixed for the whole run.

The engine asks in two steps: next_time() says when the plugin next wants
to act; at that moment the engine calls change() and applies the result.
Deciding the change only when it happens is what makes targeted faults
possible -- "crash whoever is leader at t=1000" can't be decided at t=0,
before there is a leader.

Contracts:
    - MUST NOT import from samesim.core or samesim.app
    - next_time() and change() MUST be deterministic given their inputs and
      the plugin's RNG. The
      RNG passed to initialize() is a dedicated stream, so a dynamics
      plugin's draws never shift the protocol's or the topology generator's.
    - next_time()'s delay MUST be finite and > 0 (validated by the engine)
    - the change MUST be valid against the current state (only running
      agents can fail, only failed agents can recover, only unused ids can
      join, edges must join known agents); the engine raises ValueError
      naming the plugin otherwise
    - states is a read-only snapshot. Seeing agent state is what allows
      targeted faults ("crash whoever is leader"); a plugin must never try
      to change it.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from random import Random
from typing import Any

from ..domain.ids import AgentId, VirtualTime
from ..domain.topology import TopologyGraph
from ..domain.topology_change import TopologyChange


class TopologyDynamicsPort(ABC):
    """Abstract contract for changing the agent network during a run."""

    @abstractmethod
    def initialize(self, topology: TopologyGraph, config: dict[str, Any], rng: Random) -> None:
        """Called once after the initial topology is built."""
        ...

    @abstractmethod
    def next_time(
        self,
        topology: TopologyGraph,
        virtual_time: VirtualTime,
        failed: frozenset[AgentId],
    ) -> float | None:
        """How long after virtual_time the plugin next wants to act.

        Called once at setup (virtual_time 0) and after every change.
        Returns None if nothing further will ever happen.
        """
        ...

    @abstractmethod
    def change(
        self,
        topology: TopologyGraph,
        virtual_time: VirtualTime,
        states: Mapping[AgentId, Mapping[str, Any]],
        failed: frozenset[AgentId],
    ) -> TopologyChange:
        """The change to apply now. May be empty.

        Args:
            topology:     The current graph.
            virtual_time: Now.
            states:       Read-only snapshot of every agent's current state.
            failed:       Agents currently failed.
        """
        ...
