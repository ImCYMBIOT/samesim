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
        recipient_id: The intended recipient agent.
        payload:      Arbitrary key-value data. Schema defined by the active
                      BehaviorPort plugin. Do NOT mutate after creation.
    """

    message_id: MessageId
    sender_id: AgentId
    recipient_id: AgentId
    # hash=False: dict is unhashable; exclude from auto-generated __hash__.
    # compare=False: payload equality is not checked when comparing messages.
    payload: dict[str, Any] = field(hash=False, compare=False)

    def get(self, key: str, default: Any = None) -> Any:
        """Convenience accessor — mirrors dict.get()."""
        return self.payload.get(key, default)
