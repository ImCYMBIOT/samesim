"""AsyncGossipBehavior: Boyd et al.'s pairwise averaging, over pull/push messages."""
from __future__ import annotations

import random

import pytest

from simul8.domain.ids import AgentId
from simul8.plugins.behaviors.async_gossip import AsyncGossipBehavior

A, B, C = AgentId(0), AgentId(1), AgentId(2)


def _setup(values):
    g = AsyncGossipBehavior()
    states = {}
    for aid, v in values.items():
        states[aid] = g.initialize(aid, {"initial_value_range": [v, v]}, random.Random(int(aid)))
    return g, states


def test_event_activation_only():
    assert AsyncGossipBehavior.activation_modes == frozenset({"event"})


def test_bootstrap_only_starts_the_clock():
    g, s = _setup({A: 1.0})
    r = g.step(A, s[A], [], frozenset({B}), 0.0)
    assert r.outbound_messages == []
    assert [t.tag for t in r.set_timers] == ["clock"] and r.set_timers[0].delay > 0


def test_one_exchange_averages_both_and_conserves_the_total():
    g, s = _setup({A: 2.0, B: 8.0})
    pull = g.on_timer(A, s[A], "clock", frozenset({B}), 1.0)
    assert [m.get("kind") for m in pull.outbound_messages] == ["pull"]
    assert pull.set_timers[0].tag == "clock", "the clock re-arms itself"

    at_b = g.step(B, s[B], pull.outbound_messages, frozenset({A}), 1.1)
    push = at_b.outbound_messages
    assert [(m.get("kind"), m.get("value"), m.recipient_id) for m in push] == [("push", 8.0, A)]

    at_a = g.step(A, pull.next_state, push, frozenset({B}), 1.2)
    assert at_a.next_state.get("value") == at_b.next_state.get("value") == 5.0


def test_isolated_agent_keeps_ticking_but_sends_nothing():
    g, s = _setup({A: 1.0})
    r = g.on_timer(A, s[A], "clock", frozenset(), 1.0)
    assert r.outbound_messages == [] and r.set_timers


def test_clock_intervals_are_exponential_with_the_configured_rate():
    g = AsyncGossipBehavior()
    state = g.initialize(A, {"clock_rate": 4.0}, random.Random(9))
    delays = [g.on_timer(A, state, "clock", frozenset({B}), 0.0).set_timers[0].delay
              for _ in range(20_000)]
    assert abs(sum(delays) / len(delays) - 0.25) < 0.01


@pytest.mark.parametrize("rate", [0, -1])
def test_rejects_non_positive_rate(rate):
    with pytest.raises(ValueError, match="clock_rate must be > 0"):
        AsyncGossipBehavior().initialize(A, {"clock_rate": rate}, random.Random(1))
