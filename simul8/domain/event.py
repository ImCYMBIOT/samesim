"""
Event hierarchy for the simulation engine.

All events are frozen dataclasses ordered by (virtual_time, priority, event_id).
The engine dispatches events in this order; ties are broken deterministically by event_id.

Events are the sole communication channel between the scheduler and all handlers.
The core engine never inspects event payloads — only their type.

Subclasses add kw_only fields (Python ≥ 3.10) to avoid MRO ordering conflicts
with the base class's optional fields.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from .ids import AgentId, EventId, VirtualTime

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Base event
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Event:
    """Immutable record of something that has happened or will happen at a virtual time.

    Sort key: (virtual_time, priority, event_id)
        - Lower virtual_time fires first.
        - Lower priority number fires first (0 = highest priority).
        - Lower event_id breaks ties deterministically (FIFO within same tick).
    """

    event_id: EventId
    virtual_time: VirtualTime
    source_id: Optional[AgentId] = None
    priority: int = 0

    # Custom comparison based on sort key so heapq works correctly.
    # frozen=True + order=False (default for manually defined __lt__) lets us
    # define our own ordering without dataclass generating conflicting ones.
    def __lt__(self, other: "Event") -> bool:
        return (self.virtual_time, self.priority, self.event_id) < (
            other.virtual_time,
            other.priority,
            other.event_id,
        )

    def __le__(self, other: "Event") -> bool:
        return (self.virtual_time, self.priority, self.event_id) <= (
            other.virtual_time,
            other.priority,
            other.event_id,
        )


# ---------------------------------------------------------------------------
# Core engine events
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SimulationStartedEvent(Event):
    """Fired once at virtual_time=0 before any ticks are processed."""


@dataclass(frozen=True)
class SimulationEndedEvent(Event):
    """Fired once after the final event is processed."""


@dataclass(frozen=True)
class TickEvent(Event):
    """Periodic heartbeat. Drives per-agent behavior steps.

    The engine re-schedules this event at (current_time + tick_interval)
    after each dispatch, making ticks self-sustaining without a separate loop.
    """


@dataclass(frozen=True)
class MessageDeliveredEvent(Event):
    """A message has arrived in a recipient agent's inbox.

    Scheduled by the engine after routing outbound messages.
    Delivery latency is 1 virtual tick by default.
    """

    recipient_id: AgentId = field(kw_only=True)
    # Message is stored directly to avoid a secondary lookup.
    # The payload dict is mutable inside the frozen container; do NOT mutate it.
    message: "Message" = field(kw_only=True)  # type: ignore[name-defined]  # noqa: F821


@dataclass(frozen=True)
class AgentStateChangedEvent(Event):
    """An agent's state was updated this tick.

    Emitted synchronously inside the engine's tick handler (not via the scheduler)
    so that metric collectors always see fresh values before the tick completes.

    state_snapshot is a shallow copy of the agent's state dict at the moment of
    emission. Do NOT mutate it.
    """

    agent_id: AgentId = field(kw_only=True)
    state_snapshot: dict[str, Any] = field(kw_only=True, hash=False, compare=False)


# Avoid circular import: Message is defined in domain/message.py which imports
# from domain/ids.py only. We reference it via string annotation above.
from .message import Message  # noqa: E402 — must be after class definitions

# Patch the forward reference so isinstance checks work at runtime.
MessageDeliveredEvent.__dataclass_fields__["message"].type = Message
