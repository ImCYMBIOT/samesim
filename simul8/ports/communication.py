"""
CommunicationProtocolPort — the contract for message routing.

Purpose:
    Defines HOW messages travel through the network.
    The behavior plugin decides WHAT to send and WHO it is addressed to
    (via Message.recipient_id and Message.broadcast).
    This protocol decides delivery semantics: loss, latency, duplication.

Addressing contract (the rule that makes every behavior safe with every
protocol -- see Message.broadcast):

        broadcast=False  ->  recipients MUST be a subset of {recipient_id}
        broadcast=True   ->  recipients MUST be a subset of neighbors(sender_id)

    A protocol decides whether and when a message arrives. It MUST NOT
    invent recipients the addressing mode did not authorise. Concretely: a
    protocol may drop a message, delay it, or deliver it -- it may not turn
    one addressed message into a copy for every neighbor. Violating this
    multiplies deliveries by the sender's degree whenever it is paired with
    a behavior that already enumerates its own neighbors, which is a silent
    correctness bug rather than a crash (it inflates effective rates).

    tests/unit/plugins/test_addressing_contract.py sweeps every
    behavior x protocol pair and enforces exactly this.

Contracts:
    - MUST NOT import from simul8.core or simul8.app
    - MUST NOT access agent state directly
    - route() MUST be deterministic given the same inputs and RNG state
    - route() MUST honour the addressing contract above

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
            - addressed message (broadcast=False): return
              [(message.recipient_id, message)] -- or [] to drop it
            - broadcast message (broadcast=True): return one pair per
              neighbor of sender_id -- or a subset, to drop some

        Args:
            message:   The outbound message produced by the behavior.
            sender_id: The agent that sent the message.
            topology:  Current topology (may be queried for neighbor info).

        Returns:
            List of (recipient_id, message) delivery pairs.
        """
        ...
