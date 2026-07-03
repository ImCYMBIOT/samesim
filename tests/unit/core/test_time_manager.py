"""Unit tests for TimeManager."""
import pytest
from simul8.core.time_manager import TimeManager
from simul8.domain.ids import VirtualTime


class TestTimeManagerInitial:
    def test_starts_at_zero(self):
        assert TimeManager().current_time == VirtualTime(0.0)


class TestTimeManagerAdvance:
    def test_advance_forward(self):
        tm = TimeManager()
        tm.advance(VirtualTime(5.0))
        assert tm.current_time == VirtualTime(5.0)

    def test_advance_multiple_times(self):
        tm = TimeManager()
        tm.advance(VirtualTime(1.0))
        tm.advance(VirtualTime(2.0))
        tm.advance(VirtualTime(10.0))
        assert tm.current_time == VirtualTime(10.0)

    def test_advance_to_same_time_is_allowed(self):
        """Advancing to the same time is not a violation."""
        tm = TimeManager()
        tm.advance(VirtualTime(5.0))
        tm.advance(VirtualTime(5.0))  # same time OK
        assert tm.current_time == VirtualTime(5.0)

    def test_advance_backward_raises(self):
        tm = TimeManager()
        tm.advance(VirtualTime(10.0))
        with pytest.raises(ValueError, match="Time violation"):
            tm.advance(VirtualTime(9.9))

    def test_advance_from_zero_backward_raises(self):
        with pytest.raises(ValueError):
            TimeManager().advance(VirtualTime(-1.0))


class TestTimeManagerReset:
    def test_reset_returns_to_zero(self):
        tm = TimeManager()
        tm.advance(VirtualTime(100.0))
        tm.reset()
        assert tm.current_time == VirtualTime(0.0)

    def test_can_advance_after_reset(self):
        tm = TimeManager()
        tm.advance(VirtualTime(50.0))
        tm.reset()
        tm.advance(VirtualTime(1.0))
        assert tm.current_time == VirtualTime(1.0)
