"""
BroadcastProtocol — lossless delivery, retained for config compatibility.

Fan-out is driven by the message's addressing mode (Message.broadcast),
not by the choice of protocol: a behavior that wants its whole
neighborhood says so on the message, and every protocol honours it.
This class therefore behaves identically to GossipProtocol and exists so
existing configs naming it keep working.

Historical note: this protocol used to fan out EVERY message to all
neighbors regardless of how it was addressed. Paired with a behavior that
already enumerated its own neighbors (which all three shipped behaviors
do), that multiplied deliveries by the sender's degree -- silently
inflating effective transmission rates rather than failing loudly. The
addressing contract in ports/communication.py and the matrix test in
tests/unit/plugins/test_addressing_contract.py exist to prevent that class
of bug from returning.
"""
from __future__ import annotations

import random
from typing import Any

from ...domain.ids import AgentId, MessageId
from ...domain.message import Message
from ...domain.topology import TopologyGraph
from ...ports.communication import CommunicationProtocolPort


class BroadcastProtocol(CommunicationProtocolPort):
    """Lossless delivery honouring the message's addressing mode."""

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
        """Deliver per the message's addressing mode.

        Broadcast messages reach every neighbor (each getting a distinct
        Message object with the same payload, in sorted order for
        determinism); addressed messages go to their recipient only.
        """
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
