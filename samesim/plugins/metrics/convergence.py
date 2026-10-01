"""
ConvergenceMetric — tracks gossip convergence as variance of agent values.

Subscribes to: AgentStateChangedEvent, TickEvent

Sampling strategy:
    - On AgentStateChangedEvent: update per-agent value tracker
    - On TickEvent: compute variance of all tracked values and record

Variance → 0 means all agents have converged to the same value.
This is the primary research signal for gossip convergence experiments.

The per-agent value tracker uses the state_snapshot["value"] key.
This coupling to the "value" key is intentional: it is the gossip protocol's
contract. Future behavior plugins may use different keys; a new metric
plugin would track those.

Config keys: none.
"""
from __future__ import annotations

import math

from ...domain.event import AgentStateChangedEvent, Event, TickEvent
from ...domain.ids import AgentId, MetricName, VirtualTime
from ...domain.metric import MetricSeries
from ...ports.metric_collector import MetricCollectorPort


class ConvergenceMetric(MetricCollectorPort):
    """Tracks gossip convergence as population variance of agent values.

    Samples once per tick (after all AgentStateChangedEvents for that tick).
    A value approaching 0 indicates full convergence.
    """

    def __init__(self) -> None:
        self._series = MetricSeries(name=MetricName("convergence_variance"))
        # Per-agent tracked values (updated on state change events)
        self._agent_values: dict[AgentId, float] = {}

    def subscribed_events(self) -> frozenset[type[Event]]:
        return frozenset({AgentStateChangedEvent, TickEvent})

    def on_event(self, event: Event, virtual_time: VirtualTime) -> None:
        if isinstance(event, AgentStateChangedEvent):
            value = event.state_snapshot.get("value")
            if value is not None:
                self._agent_values[event.agent_id] = float(value)

        elif isinstance(event, TickEvent):
            # Sample variance after all state changes for this tick
            if len(self._agent_values) > 1:
                variance = self._compute_variance(list(self._agent_values.values()))
                self._series.append(virtual_time, variance)

    def get_series(self) -> MetricSeries:
        return self._series

    def reset(self) -> None:
        self._series = MetricSeries(name=MetricName("convergence_variance"))
        self._agent_values.clear()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_variance(values: list[float]) -> float:
        """Population variance: E[(X - mean)^2]."""
        n = len(values)
        # fsum for version-independent, order-independent results (see
        # GossipBehavior.step for why builtin sum() is not enough).
        mean = math.fsum(values) / n
        # d * d, not d ** 2: float ** calls the platform's pow().
        return math.fsum((v - mean) * (v - mean) for v in values) / n
