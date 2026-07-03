"""
GossipProtocol — pass-through message routing for push gossip.

In push gossip, the behavior (GossipBehavior) selects which neighbors to
send to and addresses each Message with a specific recipient_id.
This protocol simply delivers the message to the specified recipient.

Future protocols may add: delivery latency, probabilistic loss,
channel capacity limits, or message transformation.
"""
from __future__ import annotations

import random
from typing import Any

from ...domain.ids import AgentId
from ...domain.message import Message
from ...domain.topology import TopologyGraph
from ...ports.communication import CommunicationProtocolPort


class GossipProtocol(CommunicationProtocolPort):
    """Pass-through delivery: routes a message to its addressed recipient.

    For push gossip, the behavior already selected the target neighbor.
    This protocol's job is simply to deliver the message as addressed.
    """

    def initialize(
        self,
        topology: TopologyGraph,
        config: dict[str, Any],
        rng: random.Random,
    ) -> None:
        """No protocol-level state needed for pass-through gossip."""
        pass

    def route(
        self,
        message: Message,
        sender_id: AgentId,
        topology: TopologyGraph,
    ) -> list[tuple[AgentId, Message]]:
        """Deliver the message to its addressed recipient.

        Returns a single (recipient_id, message) pair.
        """
        return [(message.recipient_id, message)]
