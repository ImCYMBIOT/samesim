"""
ScheduledChurn — a scripted sequence of failures, recoveries, joins and edge
changes at fixed virtual times. For fault-injection experiments: "crash the
leader at t=1000, bring it back at t=3000".

Configuration (plugin_configs.ScheduledChurn):
    events: list of mappings, each with
        at:            virtual time (> 0; strictly increasing across events)
        fail:          selector -- which running agents crash
        recover:       selector -- which failed agents come back
        join:          list of new agent ids
        add_edges:     list of [a, b]
        remove_edges:  list of [a, b]

A selector is either a list of agent ids, or {"where": {key: value, ...}}:
every eligible agent (running, for fail; failed, for recover) whose state
matches all the pairs, resolved AT the event's time. So

    - {at: 1000, fail: {where: {role: leader}}}

crashes whoever is leader at t=1000, and "all" selects every eligible agent.
A selector that matches nobody is allowed and does nothing -- it is
recorded in the plugin's `unmatched` list so experiments can tell.
"""
from __future__ import annotations

import random
from collections.abc import Mapping
from typing import Any

from ...domain.ids import AgentId, VirtualTime
from ...domain.topology import TopologyGraph
from ...domain.topology_change import TopologyChange
from ...ports.topology_dynamics import TopologyDynamicsPort

_KEYS = {"at", "fail", "recover", "join", "add_edges", "remove_edges"}


class ScheduledChurn(TopologyDynamicsPort):
    """Scripted churn at fixed times, with state-based targeting."""

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._next = 0
        self.unmatched: list[tuple[float, str]] = []

    def initialize(self, topology: TopologyGraph, config: dict[str, Any], rng: random.Random) -> None:
        events = list(config.get("events", []))
        last = 0.0
        for i, ev in enumerate(events):
            unknown = set(ev) - _KEYS
            if unknown:
                raise ValueError(f"ScheduledChurn: event {i} has unknown keys {sorted(unknown)}")
            at = float(ev.get("at", 0))
            if not at > last:
                raise ValueError(
                    f"ScheduledChurn: event times must be > 0 and strictly increasing; "
                    f"event {i} has at={ev.get('at')!r} after {last}")
            last = at
        self._events = events
        self._next = 0
        self.unmatched = []

    def next_time(self, topology: TopologyGraph, virtual_time: VirtualTime,
                  failed: frozenset[AgentId]) -> float | None:
        if self._next >= len(self._events):
            return None
        return float(self._events[self._next]["at"]) - float(virtual_time)

    def change(self, topology: TopologyGraph, virtual_time: VirtualTime,
               states: Mapping[AgentId, Mapping[str, Any]],
               failed: frozenset[AgentId]) -> TopologyChange:
        ev = self._events[self._next]
        self._next += 1
        running = [a for a in sorted(states) if a not in failed]
        return TopologyChange(
            fail=self._select(ev.get("fail"), running, states, "fail", virtual_time),
            recover=self._select(ev.get("recover"), sorted(failed), states, "recover", virtual_time),
            join=frozenset(AgentId(int(a)) for a in ev.get("join", [])),
            add_edges=frozenset(tuple(e) for e in ev.get("add_edges", [])),
            remove_edges=frozenset(tuple(e) for e in ev.get("remove_edges", [])),
        )

    def _select(self, sel, eligible, states, what, t) -> frozenset[AgentId]:
        if sel is None:
            return frozenset()
        if sel == "all":
            chosen = frozenset(eligible)
        elif isinstance(sel, Mapping):
            where = sel.get("where", {})
            chosen = frozenset(a for a in eligible
                               if all(states[a].get(k) == v for k, v in where.items()))
        else:
            chosen = frozenset(AgentId(int(a)) for a in sel)
        if not chosen:
            self.unmatched.append((float(t), what))
        return chosen
