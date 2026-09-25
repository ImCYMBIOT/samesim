"""
Delivery — one routed copy of a message: who gets it, and after how long.

A CommunicationProtocolPort.route() call returns a list of these. It may
also return bare (recipient_id, message) tuples, which mean "deliver after
the default latency" -- that is how every protocol written before latency
existed keeps working unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from .ids import AgentId
from .message import Message


@dataclass(frozen=True)
class Delivery:
    """A single routed copy of a message.

    Attributes:
        recipient_id: Who receives it. Must respect the addressing contract
                      (see Message): the message's recipient_id when
                      broadcast=False, a neighbor of the sender otherwise.
        message:      The message delivered.
        delay:        Virtual time from send to arrival, or None for the
                      engine's default (one tick_interval). When given, it
                      must be finite and strictly positive -- a message
                      cannot arrive at the instant it was sent, which rules
                      out zero-time livelock between agents replying to
                      each other.

    Synchronous activation (the only mode today) makes a message visible at
    the first tick at or after its arrival, so delays are effectively
    rounded UP to whole ticks: 2.5 ticks arrives at the third tick after
    sending; anything at or below one tick arrives at the next.
    """

    recipient_id: AgentId
    message: Message
    delay: float | None = None


RouteResult = Union[Delivery, "tuple[AgentId, Message]"]


def as_delivery(item: RouteResult) -> Delivery:
    """Normalize a route() result item to a Delivery."""
    if isinstance(item, Delivery):
        return item
    recipient_id, message = item
    return Delivery(recipient_id=recipient_id, message=message)
