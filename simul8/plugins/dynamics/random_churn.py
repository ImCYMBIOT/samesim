"""
RandomChurn — agents fail and recover at random, as independent Poisson
processes.

Each running agent fails at rate failure_rate; each failed agent recovers at
rate recovery_rate (0 = failures are permanent). Simulated exactly with
Gillespie's algorithm: the time to the next event is exponential in the
total rate, and the event is a failure or a recovery in proportion to the
two rates, applied to an agent chosen uniformly.

With recovery, each agent alternates up and down independently, so in the
long run a fraction failure_rate / (failure_rate + recovery_rate) of agents
is down at any moment.

Configuration (plugin_configs.RandomChurn):
    failure_rate:  failures per running agent per unit time (default 0.01)
    recovery_rate: recoveries per failed agent per unit time (default 0.1)
    max_failed:    never have more than this many agents down at once
                   (default: no limit)
    start_after:   no churn before this time (default 0)

Uses portable_math for the exponential draws so runs are identical on every
platform.
"""
from __future__ import annotations

import random
from collections.abc import Mapping
from typing import Any

from ...domain import portable_math
from ...domain.ids import AgentId, VirtualTime
from ...domain.topology import TopologyGraph
from ...domain.topology_change import TopologyChange
from ...ports.topology_dynamics import TopologyDynamicsPort


class RandomChurn(TopologyDynamicsPort):
    """Independent Poisson failures and recoveries (Gillespie)."""

    def __init__(self) -> None:
        self._rng: random.Random | None = None
        self._fail_rate = 0.01
        self._recover_rate = 0.1
        self._max_failed: int | None = None
        self._start_after = 0.0

    def initialize(self, topology: TopologyGraph, config: dict[str, Any], rng: random.Random) -> None:
        self._rng = rng
        self._fail_rate = float(config.get("failure_rate", 0.01))
        self._recover_rate = float(config.get("recovery_rate", 0.1))
        mf = config.get("max_failed")
        self._max_failed = None if mf is None else int(mf)
        self._start_after = float(config.get("start_after", 0.0))
        if self._fail_rate < 0 or self._recover_rate < 0:
            raise ValueError("RandomChurn: rates must be >= 0")
        if self._max_failed is not None and self._max_failed < 0:
            raise ValueError("RandomChurn: max_failed must be >= 0")
        if self._start_after < 0:
            raise ValueError("RandomChurn: start_after must be >= 0")

    def _rates(self, topology: TopologyGraph, failed: frozenset[AgentId]) -> tuple[float, float]:
        running = len(topology.agent_ids) - len(failed)
        can_fail = self._max_failed is None or len(failed) < self._max_failed
        return (running * self._fail_rate if can_fail else 0.0,
                len(failed) * self._recover_rate)

    def next_time(self, topology: TopologyGraph, virtual_time: VirtualTime,
                  failed: frozenset[AgentId]) -> float | None:
        if float(virtual_time) < self._start_after:
            return self._start_after - float(virtual_time)
        f, r = self._rates(topology, failed)
        if f + r == 0.0:
            return None
        return _positive(lambda: portable_math.expovariate(self._rng, f + r))

    def change(self, topology: TopologyGraph, virtual_time: VirtualTime,
               states: Mapping[AgentId, Mapping[str, Any]],
               failed: frozenset[AgentId]) -> TopologyChange:
        f, r = self._rates(topology, failed)
        if f + r == 0.0:
            return TopologyChange()  # waking at start_after with nothing to do
        if self._rng.random() * (f + r) < f:
            running = sorted(set(topology.agent_ids) - failed)
            return TopologyChange(fail=frozenset({self._rng.choice(running)}))
        return TopologyChange(recover=frozenset({self._rng.choice(sorted(failed))}))


def _positive(draw) -> float:
    """Redraw the (probability 2^-53) exact zero; a delay must be > 0."""
    while True:
        d = draw()
        if d > 0.0:
            return d
