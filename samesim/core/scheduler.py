"""
Scheduler — manages event scheduling in virtual time.

Wraps EventQueue and TimeManager to provide a clean scheduling API:
    - schedule(event) → EventId
    - next_event() → Event | None
    - cancel(event_id)

Invariant: no event may be scheduled at a time earlier than the current
virtual time. Violations raise ValueError immediately (fail-fast).
"""
from __future__ import annotations

from ..domain.event import Event
from ..domain.ids import EventId, VirtualTime
from .event_queue import EventQueue
from .time_manager import TimeManager


class Scheduler:
    """Provides the event scheduling API to the SimulationEngine.

    Purpose:
        Thin wrapper that enforces the "no past scheduling" invariant
        and delegates storage to EventQueue.

    Dependencies:
        EventQueue — the underlying heap storage.
        TimeManager — read-only access to current virtual time.

    Lifecycle:
        Created once per experiment. Shared between the engine and any
        module that needs to schedule events (currently only the engine).
    """

    def __init__(self, event_queue: EventQueue, time_manager: TimeManager) -> None:
        self._queue = event_queue
        self._time = time_manager

    def schedule(self, event: Event) -> EventId:
        """Add an event to the queue for future dispatch.

        Args:
            event: The event to schedule. Its virtual_time must be >= current time.

        Returns:
            The event's ID (for use with cancel()).

        Raises:
            ValueError: If event.virtual_time < current virtual time.
        """
        if event.virtual_time < self._time.current_time:
            raise ValueError(
                f"Cannot schedule event at t={event.virtual_time} — "
                f"current time is t={self._time.current_time}. "
                f"Event type: {type(event).__name__}"
            )
        self._queue.enqueue(event)
        return event.event_id

    def next_event(self) -> Event | None:
        """Remove and return the earliest non-cancelled event, or None if empty."""
        return self._queue.dequeue()

    def cancel(self, event_id: EventId) -> None:
        """Cancel a scheduled event by ID. No-op if already dispatched.

        Args:
            event_id: The ID returned by a prior schedule() call.
        """
        self._queue.cancel(event_id)

    def has_events(self) -> bool:
        """Return True if any non-cancelled events remain."""
        return not self._queue.is_empty()

    def peek_next_time(self) -> VirtualTime | None:
        """Return the virtual time of the next event without removing it."""
        event = self._queue.peek()
        return event.virtual_time if event else None
