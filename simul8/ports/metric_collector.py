"""
MetricCollectorPort — the contract for collecting a single simulation metric.

Purpose:
    Subscribes to specific event types and accumulates a MetricSeries.

Design:
    Collectors declare which events they care about via subscribed_events().
    MetricsEngine only delivers matching events, keeping fan-out cost
    proportional to actual subscriptions rather than total event volume.

Contracts:
    - MUST NOT import from simul8.core or simul8.app -- no exceptions.
      A collector that needs the starting picture (the graph, or every
      agent's initial state) overrides on_setup(), which receives immutable
      domain data only. There used to be a duck-typed configure() hook that
      handed plugins the live AgentRegistry and TopologyManager -- core
      objects with mutating methods -- and the boundary test could not see
      it. The runner now rejects any collector that still defines one.
    - subscribed_events() MUST return a stable frozenset (same value every call)
    - on_event() MUST NOT raise exceptions (log and continue instead)
    - get_series() MUST be callable at any time during or after the simulation

Extension:
    Implement to track: message count, convergence rate, state entropy,
    bandwidth, latency, network diameter, energy, packet loss, etc.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from ..domain.event import Event
from ..domain.ids import AgentId, VirtualTime
from ..domain.metric import MetricSeries
from ..domain.topology import TopologyGraph


class MetricCollectorPort(ABC):
    """Abstract contract for accumulating a single simulation metric."""

    def on_setup(
        self,
        topology: TopologyGraph,
        initial_states: Mapping[AgentId, Mapping[str, Any]],
    ) -> None:
        """Receive the starting picture, once, before the first event.

        Optional -- the default does nothing. Override it when a metric
        needs something no event carries: the graph structure, or a value
        computable only from every agent's initial state (e.g. the true
        maximum id a leader election should converge to).

        Args:
            topology:       The agent network (immutable).
            initial_states: Each agent's state at t=0, in agent-id order,
                            as read-only mappings -- the same form
                            AgentStateChangedEvent.state_snapshot takes.
        """

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
