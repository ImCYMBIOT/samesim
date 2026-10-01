"""
ConsensusMetric — how far agents are from agreeing, with churn taken into account.

ConvergenceMetric measures the variance of every agent's "value", failed
agents included. Under churn that mixes two different things: a failed
agent keeps the value it had when it crashed, so the variance can stay high
because of one stale node even while every running agent agrees. This
metric separates them, and also tracks where the agreement is heading.

Samples at every tick:

    value         variance of "value" over RUNNING agents
    all_variance  variance over ALL agents, failed ones at their frozen value
    mean          mean over running agents
    drift         mean - (mean of every agent's initial value); how far the
                  consensus value has moved from the true average
    running       number of running agents with a value

Averaging protocols that conserve the sum keep drift at 0; push gossip does
not conserve it even without churn, and churn (lost messages, stale values
re-entering) can move it further. drift is the accuracy of the answer the
system converges to; value/all_variance are how close it is to converging.

Reads the "value" key of agent state (GossipBehavior, AsyncGossipBehavior).
Agents without a numeric "value" are ignored.

Config keys: none.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from ...domain.event import AgentStateChangedEvent, Event, TickEvent, TopologyChangeEvent
from ...domain.ids import AgentId, MetricName, VirtualTime
from ...domain.metric import MetricSeries
from ...domain.topology import TopologyGraph
from ...ports.metric_collector import MetricCollectorPort

_NAME = MetricName("consensus")


def _mean_var(values: list[float]) -> tuple[float, float]:
    # fsum and d*d: identical on every Python version and platform.
    mean = math.fsum(values) / len(values)
    return mean, math.fsum((v - mean) * (v - mean) for v in values) / len(values)


class ConsensusMetric(MetricCollectorPort):
    """Variance among running agents, among all agents, and drift of the mean."""

    def __init__(self) -> None:
        self._series = MetricSeries(name=_NAME)
        self._values: dict[AgentId, float] = {}
        self._failed: set[AgentId] = set()
        self._initial_mean: float | None = None

    def on_setup(self, topology: TopologyGraph, initial_states: Mapping[AgentId, Mapping[str, Any]]) -> None:
        for agent_id, state in initial_states.items():
            value = state.get("value")
            if isinstance(value, (int, float)):
                self._values[agent_id] = float(value)
        if self._values:
            self._initial_mean = math.fsum(self._values.values()) / len(self._values)

    def subscribed_events(self) -> frozenset[type[Event]]:
        return frozenset({AgentStateChangedEvent, TopologyChangeEvent, TickEvent})

    def on_event(self, event: Event, virtual_time: VirtualTime) -> None:
        if isinstance(event, AgentStateChangedEvent):
            value = event.state_snapshot.get("value")
            if isinstance(value, (int, float)):
                self._values[event.agent_id] = float(value)
        elif isinstance(event, TopologyChangeEvent):
            c = event.change
            self._failed = (self._failed | set(c.fail)) - set(c.recover)
        elif isinstance(event, TickEvent):
            running = [v for a, v in sorted(self._values.items()) if a not in self._failed]
            if not running or self._initial_mean is None:
                return
            mean, var = _mean_var(running)
            _, all_var = _mean_var([v for _, v in sorted(self._values.items())])
            self._series.append(
                virtual_time, var,
                all_variance=repr(all_var),
                mean=repr(mean),
                drift=repr(mean - self._initial_mean),
                running=str(len(running)),
            )

    def get_series(self) -> MetricSeries:
        return self._series

    def reset(self) -> None:
        self.__init__()
