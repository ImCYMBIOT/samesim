"""
CommunicationProtocolPort — the contract for message routing.

Purpose:
    Defines HOW messages travel through the network.
    The behavior plugin decides WHAT to send and to WHOM (by addressing Message).
    This protocol decides delivery semantics: fanout, latency, loss (future).

Contracts:
    - MUST NOT import from simul8.core or simul8.app
    - MUST NOT access agent state directly
    - route() MUST be deterministic given the same inputs and RNG state

Extension:
    Implement to add new communication mechanisms:
    Broadcast, Gossip (pass-through), Random Walk, Latent Communication,
    Attention-based routing, NCA local communication, etc.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from random import Random
from typing import Any

from ..domain.ids import AgentId
from ..domain.message import Message
from ..domain.topology import TopologyGraph


class CommunicationProtocolPort(ABC):
    """Abstract contract for message delivery between agents.

    The engine calls route() for every outbound message produced by a behavior.
    The return value is a list of (recipient_id, message) pairs that the engine
    will schedule as MessageDeliveredEvents.

    One instance per experiment. Initialized once after topology is built.
    """

    @abstractmethod
    def initialize(
        self,
        topology: TopologyGraph,
        config: dict[str, Any],
        rng: Random,
    ) -> None:
        """Called once after the topology is built.

        Use this to precompute any topology-derived data structures.

        Args:
            topology: The complete agent network graph (immutable).
            config:   Plugin-specific config from plugin_configs[ClassName].
            rng:      Seeded RNG for any protocol-level randomness.
        """
        ...

    @abstractmethod
    def route(
        self,
        message: Message,
        sender_id: AgentId,
        topology: TopologyGraph,
    ) -> list[tuple[AgentId, Message]]:
        """Given an outbound message, return (recipient_id, message) pairs.

        The engine schedules one MessageDeliveredEvent per returned pair.

        Examples:
            - GossipProtocol: returns [(message.recipient_id, message)]
              (the behavior already selected the target)
            - BroadcastProtocol: returns one pair per neighbor of sender_id

        Args:
            message:   The outbound message produced by the behavior.
            sender_id: The agent that sent the message.
            topology:  Current topology (may be queried for neighbor info).

        Returns:
            List of (recipient_id, message) delivery pairs.
        """
        ...
