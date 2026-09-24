"""
LossyProtocol — unreliable channel: delivery with random message loss.

Loss is applied per delivery, on top of whatever the message's addressing
mode asks for (see Message.broadcast): an addressed message is delivered
or dropped; a broadcast message reaches each neighbor independently, so
some neighbors may receive it while others do not -- which is what an
unreliable shared medium actually looks like.

Configuration:
    loss_probability: float — probability a given delivery is dropped (default 0.1)

Note: a "mode" key used to select recipients here (gossip vs broadcast).
That duplicated the addressing decision the message already carries and
could multiply deliveries by the sender's degree; recipient selection now
comes solely from the message. The key is accepted and ignored so existing
configs keep loading.
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
        self._rng: random.Random | None = None
        self._msg_counter: int = 0

    def initialize(
        self,
        topology: TopologyGraph,
        config: dict[str, Any],
        rng: random.Random,
    ) -> None:
        self._loss_prob = float(config.get("loss_probability", 0.1))
        self._rng = rng

    def route(
        self,
        message: Message,
        sender_id: AgentId,
        topology: TopologyGraph,
    ) -> list[tuple[AgentId, Message]]:
        """Deliver per the message's addressing mode, dropping independently."""
        rng = self._rng or random.Random()
        deliveries: list[tuple[AgentId, Message]] = []

        if not message.broadcast:
            if rng.random() >= self._loss_prob:
                deliveries.append((message.recipient_id, message))
            return deliveries

        for neighbor_id in sorted(topology.neighbors(sender_id)):
            if rng.random() >= self._loss_prob:
                self._msg_counter += 1
                deliveries.append((neighbor_id, Message(
                    message_id=MessageId(self._msg_counter),
                    sender_id=sender_id,
                    recipient_id=neighbor_id,
                    payload=message.payload,
                )))
        return deliveries
