"""
TopologyChange — one batch of changes to who is running and who is connected.

Two kinds of change, deliberately kept apart:

    Liveness  fail     crash-stop: the agent stops running, loses its inbox
                       and timers, and messages reaching it are lost. It is
                       NOT removed from anyone's neighbor set -- a crash is
                       silent; neighbors find out only the way real systems
                       do, through missing replies and timeouts.
              recover  a failed agent comes back with the state it had when
                       it failed (durable state), via BehaviorPort.on_recover.
              join     a brand-new agent (unused id) enters: initialize()
                       with its usual per-agent RNG, then a bootstrap step.

    Structure add_edges / remove_edges  -- undirected; (a, b) == (b, a).

A graceful departure is `fail` plus `remove_edges` for its links in the same
change; a joining agent usually comes with `add_edges`.

Within one change: joins, then edge additions, then edge removals, then
failures, then recoveries. An agent may not appear in more than one of
fail / recover / join in the same change.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .ids import AgentId


def _edges(pairs) -> frozenset[tuple[AgentId, AgentId]]:
    out = set()
    for a, b in pairs:
        a, b = AgentId(int(a)), AgentId(int(b))
        if a == b:
            raise ValueError(f"TopologyChange: self-loop ({a}, {b}) is not an edge")
        out.add((a, b) if a < b else (b, a))
    return frozenset(out)


@dataclass(frozen=True)
class TopologyChange:
    fail: frozenset[AgentId] = frozenset()
    recover: frozenset[AgentId] = frozenset()
    join: frozenset[AgentId] = frozenset()
    add_edges: frozenset[tuple[AgentId, AgentId]] = field(default=frozenset())
    remove_edges: frozenset[tuple[AgentId, AgentId]] = field(default=frozenset())

    def __post_init__(self) -> None:
        for name in ("fail", "recover", "join"):
            object.__setattr__(self, name, frozenset(AgentId(int(a)) for a in getattr(self, name)))
        object.__setattr__(self, "add_edges", _edges(self.add_edges))
        object.__setattr__(self, "remove_edges", _edges(self.remove_edges))
        overlap = (self.fail & self.recover) | (self.fail & self.join) | (self.recover & self.join)
        if overlap:
            raise ValueError(
                f"TopologyChange: agents {sorted(overlap)} appear in more than one of "
                f"fail / recover / join")
        both = self.add_edges & self.remove_edges
        if both:
            raise ValueError(f"TopologyChange: edges {sorted(both)} are both added and removed")

    def is_empty(self) -> bool:
        return not (self.fail or self.recover or self.join or self.add_edges or self.remove_edges)

    @property
    def is_structural(self) -> bool:
        """True if the graph itself changes (joins or edges), not just liveness."""
        return bool(self.join or self.add_edges or self.remove_edges)
