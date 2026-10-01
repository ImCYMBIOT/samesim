"""
Message — the unit of communication between agents.

Messages are immutable after creation. The payload dict is technically
mutable inside the frozen container, but must never be mutated after dispatch.
Callers should treat payload as read-only.

The engine never inspects message contents. Only the behavior plugin reads
and produces payloads.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .ids import AgentId, MessageId


@dataclass(frozen=True)
class Message:
    """An immutable unit of communication sent from one agent to another.

    The core engine is payload-agnostic: it routes messages by recipient_id
    without ever reading the payload contents.

    Attributes:
        message_id:   Globally unique identifier assigned by the engine.
        sender_id:    The agent that originated this message.
        recipient_id: The intended recipient agent. Ignored when broadcast
                      is True (set it to sender_id by convention then).
        payload:      Arbitrary key-value data. Schema defined by the active
                      BehaviorPort plugin. Do NOT mutate after creation.
        broadcast:    Addressing mode. False (default) means "deliver to
                      recipient_id". True means "deliver to every neighbor
                      of sender_id" -- the behavior is asking to reach its
                      whole neighborhood without enumerating it.

    Addressing contract:
        This flag is what makes any behavior safe to pair with any protocol.
        A protocol decides how a message *travels* (drop it, delay it), never
        who it reaches beyond what the addressing mode already specifies:

            broadcast=False  ->  recipients must be a subset of {recipient_id}
            broadcast=True   ->  recipients must be a subset of neighbors(sender_id)

        A behavior that enumerates neighbors itself emits one addressed
        message each (broadcast=False); a behavior that wants its whole
        neighborhood emits ONE message with broadcast=True. Doing both --
        enumerating neighbors AND letting the protocol fan out -- is what
        used to multiply deliveries by the sender's degree.
    """

    message_id: MessageId
    sender_id: AgentId
    recipient_id: AgentId
    # hash=False: dict is unhashable; exclude from auto-generated __hash__.
    # compare=False: payload equality is not checked when comparing messages.
    payload: dict[str, Any] = field(hash=False, compare=False)
    broadcast: bool = False

    def get(self, key: str, default: Any = None) -> Any:
        """Convenience accessor — mirrors dict.get()."""
        return self.payload.get(key, default)
