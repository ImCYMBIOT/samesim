"""
MetricCollectorPort — the contract for collecting a single simulation metric.

Purpose:
    Subscribes to specific event types and accumulates a MetricSeries.

Design:
    Collectors declare which events they care about via subscribed_events().
    MetricsEngine only delivers matching events, keeping fan-out cost
    proportional to actual subscriptions rather than total event volume.

Contracts:
    - MUST NOT import from simul8.core or simul8.app
      (Exception: collectors needing agent state may accept an AgentRegistry
       reference via a configure() method, which the ExperimentRunner calls
       before registering the collector with MetricsEngine.)
    - subscribed_events() MUST return a stable frozenset (same value every call)
    - on_event() MUST NOT raise exceptions (log and continue instead)
    - get_series() MUST be callable at any time during or after the simulation

Extension:
    Implement to track: message count, convergence rate, state entropy,
    bandwidth, latency, network diameter, energy, packet loss, etc.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..domain.event import Event
from ..domain.ids import VirtualTime
from ..domain.metric import MetricSeries


class MetricCollectorPort(ABC):
    """Abstract contract for accumulating a single simulation metric."""

    @abstractmethod
    def subscribed_events(self) -> frozenset[type[Event]]:
        """Return the event types this collector wants to receive.

        MetricsEngine calls on_event() only for these types.
        Must return the same value on every call.
        """
        ...

    @abstractmethod
    def on_event(self, event: Event, virtual_time: VirtualTime) -> None:
        """Process an incoming event and update internal metric state.

        Called synchronously during event dispatch. Must not raise.
        """
        ...

    @abstractmethod
    def get_series(self) -> MetricSeries:
        """Return the accumulated time-series metric data.

        Callable at any time. Returns an empty series before any events arrive.
        """
        ...

    @abstractmethod
    def reset(self) -> None:
        """Clear accumulated data.

        Called between runs in multi-run experiments (future feature).
        """
        ...
