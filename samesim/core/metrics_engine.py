"""
MetricsEngine — routes simulation events to registered metric collectors.

Design:
    Collectors declare which event types they care about via subscribed_events().
    MetricsEngine maintains a subscription map and only calls on_event() for
    matching types. Fan-out cost is O(subscribers_for_event_type), not O(all_collectors).

    This means adding 50 metric collectors that care about different events
    costs nothing for events they don't subscribe to.
"""
from __future__ import annotations

from ..domain.event import Event
from ..domain.ids import VirtualTime
from ..domain.metric import MetricSeries
from ..ports.metric_collector import MetricCollectorPort


class MetricsEngine:
    """Subscription-based event fan-out to metric collectors.

    Purpose:
        Deliver events to exactly the collectors that subscribed to them.

    Responsibilities:
        Register collectors, build subscription index, fan out events.

    Dependencies:
        MetricCollectorPort (injected via register()).
        Event and VirtualTime (domain types).

    Does NOT:
        Access agent state directly. Collectors pull state from events.
    """

    def __init__(self) -> None:
        self._collectors: list[MetricCollectorPort] = []
        # subscription index: event_type -> list of interested collectors
        self._subscriptions: dict[type[Event], list[MetricCollectorPort]] = {}

    def register(self, collector: MetricCollectorPort) -> None:
        """Register a collector and index its event subscriptions.

        Args:
            collector: A MetricCollectorPort implementation to add.
        """
        self._collectors.append(collector)
        for event_type in collector.subscribed_events():
            self._subscriptions.setdefault(event_type, []).append(collector)

    def on_event(self, event: Event, virtual_time: VirtualTime) -> None:
        """Deliver an event to all collectors that subscribed to its type.

        Called by SimulationEngine for every event dispatched.

        Args:
            event:        The event to deliver.
            virtual_time: Current simulation time (convenience for collectors).
        """
        event_type = type(event)
        for collector in self._subscriptions.get(event_type, []):
            collector.on_event(event, virtual_time)

    def get_all_series(self) -> list[MetricSeries]:
        """Return the accumulated MetricSeries from all registered collectors."""
        return [c.get_series() for c in self._collectors]

    def reset_all(self) -> None:
        """Reset all collectors. Used between runs in multi-run experiments."""
        for c in self._collectors:
            c.reset()

    def collector_count(self) -> int:
        """Return the number of registered collectors."""
        return len(self._collectors)
