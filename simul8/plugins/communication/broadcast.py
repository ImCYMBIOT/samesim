"""
BroadcastProtocol — fan-out delivery to all neighbors of the sender.

The behavior sends a message to a single recipient; this protocol
fans it out to every neighbor of the sender in the topology.

Useful for: flooding, epidemic broadcast, initial state dissemination.
"""
from __future__ import annotations

import random
from typing import Any

from ...domain.ids import AgentId, MessageId
from ...domain.message import Message
from ...domain.topology import TopologyGraph
from ...ports.communication import CommunicationProtocolPort


class BroadcastProtocol(CommunicationProtocolPort):
    """Fan-out delivery: one inbound message → one copy per sender neighbor."""

    def __init__(self) -> None:
        self._msg_counter: int = 0

    def initialize(
        self,
        topology: TopologyGraph,
        config: dict[str, Any],
        rng: random.Random,
    ) -> None:
        pass

    def route(
        self,
        message: Message,
        sender_id: AgentId,
        topology: TopologyGraph,
    ) -> list[tuple[AgentId, Message]]:
        """Fan out the message to all neighbors of the sender.

        Each neighbor receives a distinct Message object (same payload).
        Neighbors are returned in sorted order for determinism.
        """
        neighbors = sorted(topology.neighbors(sender_id))
        deliveries: list[tuple[AgentId, Message]] = []
        for neighbor_id in neighbors:
            self._msg_counter += 1
            copy = Message(
                message_id=MessageId(self._msg_counter),
                sender_id=sender_id,
                recipient_id=neighbor_id,
                payload=message.payload,
            )
            deliveries.append((neighbor_id, copy))
        return deliveries
