"""
EventQueue — priority queue of simulation events ordered by virtual time.

This is a pure data structure with no behavior, no I/O, and no dependencies
on any other SameSim module. Only the Scheduler writes to it; only the
SimulationEngine (via the Scheduler) reads from it.

Ordering key: (virtual_time, priority, event_id)
    - Lower virtual_time fires first.
    - Lower priority number fires first (0 = highest priority).
    - Lower event_id breaks ties — guarantees deterministic FIFO within a tick.

Cancellation is lazy: cancelled event IDs are stored in a set and silently
skipped on dequeue/peek. This avoids O(n) heap removal.

Complexity:
    enqueue:  O(log n)
    dequeue:  O(log n) amortized
    peek:     O(1) amortized
    cancel:   O(1)
    is_empty: O(1) amortized
"""
from __future__ import annotations

import heapq

from ..domain.event import Event
from ..domain.ids import EventId


class EventQueue:
    """Min-heap priority queue of Events, ordered by virtual time."""

    def __init__(self) -> None:
        self._heap: list[Event] = []
        self._cancelled: set[EventId] = set()

    # ------------------------------------------------------------------
    # Write API (only Scheduler should call these)
    # ------------------------------------------------------------------

    def enqueue(self, event: Event) -> None:
        """Add an event to the queue. O(log n)."""
        heapq.heappush(self._heap, event)

    def cancel(self, event_id: EventId) -> None:
        """Mark an event as cancelled. It will be skipped on next dequeue/peek."""
        self._cancelled.add(event_id)

    # ------------------------------------------------------------------
    # Read API (only SimulationEngine/Scheduler should call these)
    # ------------------------------------------------------------------

    def dequeue(self) -> Event | None:
        """Remove and return the earliest non-cancelled event, or None if empty."""
        while self._heap:
            event = heapq.heappop(self._heap)
            if event.event_id not in self._cancelled:
                return event
            # Lazily clean up the cancelled event
            self._cancelled.discard(event.event_id)
        return None

    def peek(self) -> Event | None:
        """Return the earliest non-cancelled event without removing it."""
        while self._heap and self._heap[0].event_id in self._cancelled:
            self._cancelled.discard(self._heap[0].event_id)
            heapq.heappop(self._heap)
        return self._heap[0] if self._heap else None

    def is_empty(self) -> bool:
        """Return True if no non-cancelled events remain."""
        return self.peek() is None

    def clear(self) -> None:
        """Remove all events and cancellations. Used between multi-run resets."""
        self._heap.clear()
        self._cancelled.clear()

    def __len__(self) -> int:
        """Approximate count: heap size minus known cancellations."""
        return max(0, len(self._heap) - len(self._cancelled))
