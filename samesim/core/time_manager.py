"""
TimeManager — authoritative source of virtual simulation time.

Only the SimulationEngine advances time (by calling advance()).
All other modules read the current time via the current_time property.

Invariant: time is monotonically non-decreasing. Advancing backward raises
a ValueError immediately, ensuring the engine fails fast on logic errors.
"""
from __future__ import annotations

from ..domain.ids import VirtualTime


class TimeManager:
    """Tracks and advances virtual simulation time.

    Purpose:
        Single source of truth for current simulation time.

    Dependencies:
        None. Depends only on the VirtualTime type alias.

    Lifecycle:
        Created once by ExperimentRunner. reset() is called between runs
        in multi-run experiments (future feature).
    """

    def __init__(self) -> None:
        self._current: VirtualTime = VirtualTime(0.0)

    @property
    def current_time(self) -> VirtualTime:
        """The current virtual simulation time."""
        return self._current

    def advance(self, new_time: VirtualTime) -> None:
        """Advance the clock to new_time.

        Args:
            new_time: The new virtual time. Must be >= current_time.

        Raises:
            ValueError: If new_time < current_time (time travel).
        """
        if new_time < self._current:
            raise ValueError(
                f"Time violation: cannot advance clock from "
                f"t={self._current} to t={new_time}"
            )
        self._current = new_time

    def reset(self) -> None:
        """Reset clock to zero. Used between runs in multi-run experiments."""
        self._current = VirtualTime(0.0)
