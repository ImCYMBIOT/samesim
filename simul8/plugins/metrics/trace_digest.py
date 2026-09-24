"""
TraceDigestMetric — a running SHA-256 fingerprint of an entire simulation.

Folds, in dispatch order, everything that defines a run's dynamics:

    - the topology and every agent's initial state   (once, via on_setup)
    - every delivered message: time, sender, recipient, addressing mode,
      message id and payload
    - every agent state change: time, agent, full state snapshot
    - every tick boundary

and records the digest at each tick. Two runs with the same digest at tick
t behaved identically up to t; the first tick where two digest series
differ is the first tick where the runs diverged.

Deliberately NOT folded: engine-internal event ids and wall-clock time.
Those can change under a refactor that leaves the simulation itself
untouched, and a fingerprint that flags them would cry wolf.

Uses:
    - Regression guard. tests/regression/test_golden_traces.py pins the
      digest of every behavior x protocol x topology combination, so a core
      change that alters any delivered message fails the build.
    - Reproducibility receipt. Publish the final digest alongside a result;
      anyone re-running the config can confirm they got the identical run,
      not just similar-looking numbers.

Cost: one JSON serialization plus a hash update per event. Negligible at
experiment sizes used for validation; measurable at 10^5 agents -- leave it
out of performance benchmarks.

Canonical form: state and payload values are serialized as sorted-key JSON,
with sets sorted and tuples treated as lists. Values must have a
deterministic repr; an object whose repr embeds a memory address would make
the digest differ between otherwise identical runs.

Config keys: none.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from ...domain.event import (
    AgentStateChangedEvent,
    Event,
    MessageDeliveredEvent,
    SimulationEndedEvent,
    TickEvent,
)
from ...domain.ids import AgentId, MetricName, VirtualTime
from ...domain.metric import MetricSeries
from ...domain.topology import TopologyGraph
from ...ports.metric_collector import MetricCollectorPort

_NAME = MetricName("trace_digest")


def _canonical(value: Any) -> Any:
    """Reduce a value to JSON-serializable form with a single fixed ordering."""
    if isinstance(value, Mapping):
        return {str(k): _canonical(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((_canonical(v) for v in value), key=repr)
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return repr(value)


def _encode(record: Any) -> bytes:
    return json.dumps(
        _canonical(record), sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"


class TraceDigestMetric(MetricCollectorPort):
    """Running SHA-256 over the full event trace, sampled every tick."""

    def __init__(self) -> None:
        self._series = MetricSeries(name=_NAME)
        self._hash = hashlib.sha256()
        self._folded = 0

    def on_setup(
        self,
        topology: TopologyGraph,
        initial_states: Mapping[AgentId, Mapping[str, Any]],
    ) -> None:
        adjacency = [
            [int(a), sorted(int(b) for b in topology.neighbors(a))]
            for a in sorted(topology.all_agent_ids())
        ]
        self._fold(["topology", adjacency])
        for agent_id, state in initial_states.items():
            self._fold(["init", int(agent_id), state])

    def subscribed_events(self) -> frozenset[type[Event]]:
        return frozenset({
            TickEvent,
            MessageDeliveredEvent,
            AgentStateChangedEvent,
            SimulationEndedEvent,
        })

    def on_event(self, event: Event, virtual_time: VirtualTime) -> None:
        t = float(virtual_time)
        if isinstance(event, MessageDeliveredEvent):
            m = event.message
            self._fold([
                "deliver", t, int(event.recipient_id),
                int(m.message_id), int(m.sender_id), int(m.recipient_id),
                m.broadcast, m.payload,
            ])
        elif isinstance(event, AgentStateChangedEvent):
            self._fold(["state", t, int(event.agent_id), event.state_snapshot])
        elif isinstance(event, TickEvent):
            self._fold(["tick", t])
            self._record(virtual_time)
        elif isinstance(event, SimulationEndedEvent):
            self._fold(["end", t])
            self._record(virtual_time)

    def _fold(self, record: Any) -> None:
        self._hash.update(_encode(record))
        self._folded += 1

    def _record(self, virtual_time: VirtualTime) -> None:
        self._series.append(
            virtual_time=virtual_time,
            value=float(self._folded),
            digest=self._hash.hexdigest(),
        )

    @property
    def digest(self) -> str:
        """The current fingerprint (final, once the run has ended)."""
        return self._hash.hexdigest()

    def get_series(self) -> MetricSeries:
        return self._series

    def reset(self) -> None:
        self._series = MetricSeries(name=_NAME)
        self._hash = hashlib.sha256()
        self._folded = 0
