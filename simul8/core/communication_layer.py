"""
CommunicationLayer — routes outbound agent messages through the active protocol.

Acts as the bridge between the engine's message dispatch and the pluggable
CommunicationProtocolPort. Tracks send/deliver counters for metrics.

The behavior decides WHAT to send and to WHOM (Message.recipient_id and
Message.broadcast). The protocol decides whether and when each copy arrives
(loss, latency). This layer normalizes the protocol's output to Delivery
objects and enforces the latency contract, so a bad delay fails loudly here,
naming the protocol, instead of corrupting the schedule.
"""
from __future__ import annotations

import math

from ..domain.delivery import Delivery, as_delivery
from ..domain.ids import AgentId
from ..domain.message import Message
from ..domain.topology import TopologyGraph
from ..ports.communication import CommunicationProtocolPort


class CommunicationLayer:
    """Bridges engine message dispatch with the pluggable protocol.

    Purpose:
        Accept outbound messages from the engine, route them through the
        protocol, and return (recipient_id, message) delivery pairs.

    Dependencies:
        CommunicationProtocolPort (injected at construction).

    Does NOT:
        Know what messages contain. Does not schedule events.
        The engine schedules MessageDeliveredEvents from the returned pairs.
    """

    def __init__(self, protocol: CommunicationProtocolPort) -> None:
        self._protocol = protocol
        self._messages_sent: int = 0
        self._messages_delivered: int = 0

    def route(
        self,
        message: Message,
        sender_id: AgentId,
        topology: TopologyGraph,
    ) -> list[Delivery]:
        """Route a message through the protocol.

        Args:
            message:   The outbound message from an agent's behavior step.
            sender_id: The agent that produced the message.
            topology:  The current topology (passed to the protocol for neighbor queries).

        Returns:
            One Delivery per routed copy. The engine schedules one
            MessageDeliveredEvent per Delivery.

        Raises:
            ValueError: If the protocol returned a delay that is not None
                and not a finite number > 0.
        """
        deliveries = [
            as_delivery(item)
            for item in self._protocol.route(message, sender_id, topology)
        ]
        for delivery in deliveries:
            if delivery.delay is not None:
                self._check_delay(delivery.delay)
        self._messages_sent += 1
        return deliveries

    def _check_delay(self, delay: object) -> None:
        valid = (
            isinstance(delay, (int, float))
            and not isinstance(delay, bool)
            and math.isfinite(delay)
            and delay > 0
        )
        if not valid:
            raise ValueError(
                f"{type(self._protocol).__name__}.route() returned delay={delay!r}. "
                f"A delay must be None (one tick) or a finite number > 0: a message "
                f"cannot arrive at the instant it was sent."
            )

    def record_delivery(self) -> None:
        """Increment the delivered message counter.

        Called by the engine when a MessageDeliveredEvent is processed.
        """
        self._messages_delivered += 1

    def reset_counters(self) -> None:
        """Reset send/deliver counters. Used between multi-run resets."""
        self._messages_sent = 0
        self._messages_delivered = 0

    @property
    def messages_sent(self) -> int:
        return self._messages_sent

    @property
    def messages_delivered(self) -> int:
        return self._messages_delivered
