"""
GossipProtocol — lossless pass-through routing.

Delivers every message exactly as addressed, with no transport effects.
Honours both addressing modes (see Message.broadcast): an addressed
message goes to its recipient; a broadcast message reaches every neighbor
of the sender. That makes this protocol safe to pair with any behavior.

Config keys: none.
"""
from __future__ import annotations

import random
from typing import Any

from ...domain.ids import AgentId, MessageId
from ...domain.message import Message
from ...domain.topology import TopologyGraph
from ...ports.communication import CommunicationProtocolPort


class GossipProtocol(CommunicationProtocolPort):
    """Lossless delivery honouring the message's addressing mode."""

    def __init__(self) -> None:
        self._msg_counter: int = 0

    def initialize(
        self,
        topology: TopologyGraph,
        config: dict[str, Any],
        rng: random.Random,
    ) -> None:
        """No protocol-level state needed for lossless delivery."""
        pass

    def route(
        self,
        message: Message,
        sender_id: AgentId,
        topology: TopologyGraph,
    ) -> list[tuple[AgentId, Message]]:
        """Deliver per the message's addressing mode."""
        if not message.broadcast:
            return [(message.recipient_id, message)]

        deliveries: list[tuple[AgentId, Message]] = []
        for neighbor_id in sorted(topology.neighbors(sender_id)):
            self._msg_counter += 1
            deliveries.append((neighbor_id, Message(
                message_id=MessageId(self._msg_counter),
                sender_id=sender_id,
                recipient_id=neighbor_id,
                payload=message.payload,
            )))
        return deliveries
