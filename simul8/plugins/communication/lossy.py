"""
LossyProtocol — communication protocol with random message loss.

Drops messages with a configurable packet loss probability.

Configuration:
    loss_probability: float — probability that a message is dropped (default 0.1)
    mode: str               — routing mode: "gossip" (deliver to message.recipient_id)
                              or "broadcast" (fan out to all neighbors) (default "gossip")
"""
from __future__ import annotations

import random
from typing import Any

from ...domain.ids import AgentId, MessageId
from ...domain.message import Message
from ...domain.topology import TopologyGraph
from ...ports.communication import CommunicationProtocolPort


class LossyProtocol(CommunicationProtocolPort):
    """Lossy communication protocol with configurable random drop rate."""

    def __init__(self) -> None:
        self._loss_prob: float = 0.1
        self._mode: str = "gossip"
        self._rng: random.Random | None = None
        self._msg_counter: int = 0

    def initialize(
        self,
        topology: TopologyGraph,
        config: dict[str, Any],
        rng: random.Random,
    ) -> None:
        self._loss_prob = float(config.get("loss_probability", 0.1))
        self._mode = str(config.get("mode", "gossip"))
        self._rng = rng

    def route(
        self,
        message: Message,
        sender_id: AgentId,
        topology: TopologyGraph,
    ) -> list[tuple[AgentId, Message]]:
        rng = self._rng or random.Random()
        deliveries: list[tuple[AgentId, Message]] = []

        if self._mode == "broadcast":
            # Broadcast to all neighbors
            neighbors = sorted(topology.neighbors(sender_id))
            for neighbor_id in neighbors:
                if rng.random() >= self._loss_prob:
                    self._msg_counter += 1
                    copy = Message(
                        message_id=MessageId(self._msg_counter),
                        sender_id=sender_id,
                        recipient_id=neighbor_id,
                        payload=message.payload,
                    )
                    deliveries.append((neighbor_id, copy))
        else:
            # Gossip (pass-through targeted delivery)
            if rng.random() >= self._loss_prob:
                deliveries.append((message.recipient_id, message))

        return deliveries
