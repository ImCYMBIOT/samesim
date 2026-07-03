"""Unit tests for EventQueue."""
import pytest
from simul8.core.event_queue import EventQueue
from simul8.domain.event import Event, TickEvent, SimulationStartedEvent
from simul8.domain.ids import EventId, VirtualTime


def tick(eid: int, vt: float) -> TickEvent:
    return TickEvent(event_id=EventId(eid), virtual_time=VirtualTime(vt))


class TestEventQueueEmpty:
    def test_starts_empty(self):
        q = EventQueue()
        assert q.is_empty()

    def test_dequeue_empty_returns_none(self):
        assert EventQueue().dequeue() is None

    def test_peek_empty_returns_none(self):
        assert EventQueue().peek() is None

    def test_len_empty_is_zero(self):
        assert len(EventQueue()) == 0


class TestEventQueueOrdering:
    def test_dequeues_by_virtual_time(self):
        q = EventQueue()
        q.enqueue(tick(2, 2.0))
        q.enqueue(tick(0, 0.0))
        q.enqueue(tick(1, 1.0))

        assert q.dequeue().virtual_time == VirtualTime(0.0)
        assert q.dequeue().virtual_time == VirtualTime(1.0)
        assert q.dequeue().virtual_time == VirtualTime(2.0)
        assert q.dequeue() is None

    def test_tie_broken_by_event_id(self):
        """Same virtual_time → lower event_id fires first (FIFO)."""
        q = EventQueue()
        q.enqueue(tick(5, 0.0))
        q.enqueue(tick(1, 0.0))
        q.enqueue(tick(3, 0.0))

        assert q.dequeue().event_id == EventId(1)
        assert q.dequeue().event_id == EventId(3)
        assert q.dequeue().event_id == EventId(5)

    def test_tie_broken_by_priority(self):
        """Same virtual_time, lower priority number fires first."""
        q = EventQueue()
        e_low = TickEvent(event_id=EventId(10), virtual_time=VirtualTime(0.0), priority=5)
        e_high = TickEvent(event_id=EventId(11), virtual_time=VirtualTime(0.0), priority=0)
        q.enqueue(e_low)
        q.enqueue(e_high)
        assert q.dequeue().priority == 0
        assert q.dequeue().priority == 5


class TestEventQueueCancellation:
    def test_cancelled_event_skipped(self):
        q = EventQueue()
        e1 = tick(0, 0.0)
        e2 = tick(1, 1.0)
        q.enqueue(e1)
        q.enqueue(e2)
        q.cancel(e1.event_id)

        result = q.dequeue()
        assert result is not None
        assert result.event_id == EventId(1)

    def test_cancel_all_leaves_empty(self):
        q = EventQueue()
        e = tick(0, 0.0)
        q.enqueue(e)
        q.cancel(e.event_id)
        assert q.is_empty()
        assert q.dequeue() is None

    def test_cancel_nonexistent_is_noop(self):
        q = EventQueue()
        q.cancel(EventId(999))  # should not raise


class TestEventQueuePeek:
    def test_peek_does_not_remove(self):
        q = EventQueue()
        q.enqueue(tick(0, 0.0))
        first = q.peek()
        second = q.peek()
        assert first is second
        assert q.dequeue() is first

    def test_peek_returns_earliest(self):
        q = EventQueue()
        q.enqueue(tick(1, 5.0))
        q.enqueue(tick(0, 1.0))
        assert q.peek().virtual_time == VirtualTime(1.0)


class TestEventQueueClear:
    def test_clear_empties_queue(self):
        q = EventQueue()
        for i in range(5):
            q.enqueue(tick(i, float(i)))
        q.clear()
        assert q.is_empty()
        assert q.dequeue() is None
