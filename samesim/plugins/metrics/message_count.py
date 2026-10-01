"""
MessageCountMetric — counts total messages delivered over the simulation.

Subscribes to: MessageDeliveredEvent

Records a running total at each delivery event. The resulting series
gives cumulative message volume over virtual time.

Config keys: none.
"""
from __future__ import annotations

from ...domain.event import Event, MessageDeliveredEvent
from ...domain.ids import MetricName, VirtualTime
from ...domain.metric import MetricSeries
from ...ports.metric_collector import MetricCollectorPort


class MessageCountMetric(MetricCollectorPort):
    """Cumulative count of delivered messages over virtual time."""

    def __init__(self) -> None:
        self._series = MetricSeries(name=MetricName("message_count"))
        self._count: int = 0

    def subscribed_events(self) -> frozenset[type[Event]]:
        return frozenset({MessageDeliveredEvent})

    def on_event(self, event: Event, virtual_time: VirtualTime) -> None:
        if isinstance(event, MessageDeliveredEvent):
            self._count += 1
            self._series.append(virtual_time, float(self._count))

    def get_series(self) -> MetricSeries:
        return self._series

    def reset(self) -> None:
        self._series = MetricSeries(name=MetricName("message_count"))
        self._count = 0
