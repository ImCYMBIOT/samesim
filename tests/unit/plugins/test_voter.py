"""VoterBehavior and VoterMetric."""
from __future__ import annotations

import random

import pytest

from samesim.domain.event import AgentStateChangedEvent, TickEvent
from samesim.domain.ids import AgentId, EventId, MessageId, VirtualTime
from samesim.domain.message import Message
from samesim.domain.topology import TopologyGraph
from samesim.plugins.behaviors.voter import VoterBehavior
from samesim.plugins.metrics.voter_metrics import VoterMetric

A, B, C = AgentId(0), AgentId(1), AgentId(2)


def _said(sender, opinion):
    return Message(message_id=MessageId(1), sender_id=sender, recipient_id=sender,
                   payload={"opinion": opinion}, broadcast=True)


def test_initial_ones_sets_the_first_agents():
    v = VoterBehavior()
    states = [v.initialize(AgentId(i), {"initial_ones": 2}, random.Random(i)) for i in range(4)]
    assert [s.get("opinion") for s in states] == [1, 1, 0, 0]


def test_first_step_announces_and_changes_nothing():
    v = VoterBehavior()
    s = v.initialize(A, {"initial_ones": 1}, random.Random(0))
    r = v.step(A, s, [], frozenset({B}), VirtualTime(0.0))
    assert r.next_state.get("opinion") == 1
    assert len(r.outbound_messages) == 1 and r.outbound_messages[0].broadcast


def test_adopts_a_known_neighbors_opinion_and_announces_only_on_change():
    v = VoterBehavior()
    s = v.initialize(A, {"initial_ones": 0}, random.Random(0))   # opinion 0
    # Both neighbors announced 1: whichever is picked, A becomes 1 and says so.
    r = v.step(A, s, [_said(B, 1), _said(C, 1)], frozenset({B, C}), VirtualTime(1.0))
    assert r.next_state.get("opinion") == 1 and len(r.outbound_messages) == 1
    # Nothing new arrives; every known neighbor holds 1, so no change, no message.
    r = v.step(A, r.next_state, [], frozenset({B, C}), VirtualTime(2.0))
    assert r.next_state.get("opinion") == 1 and not r.outbound_messages


def test_unknown_neighbors_are_skipped():
    v = VoterBehavior()
    s = v.initialize(A, {"initial_ones": 1}, random.Random(0))
    r = v.step(A, s, [], frozenset({B}), VirtualTime(1.0))  # never heard from B
    assert r.next_state.get("opinion") == 1


def test_invalid_fraction_is_rejected():
    with pytest.raises(ValueError, match="initial_fraction"):
        VoterBehavior().initialize(A, {"initial_fraction": 1.5}, random.Random(0))


def test_metric_reports_plain_and_degree_weighted_fractions():
    # Star: A has degree 2, B and C degree 1. Only A holds opinion 1.
    g = TopologyGraph(agent_ids=frozenset({A, B, C}),
                      adjacency={A: frozenset({B, C}), B: frozenset({A}), C: frozenset({A})})
    m = VoterMetric()
    m.on_setup(g, {A: {"opinion": 1}, B: {"opinion": 0}, C: {"opinion": 0}})
    m.on_event(TickEvent(event_id=EventId(0), virtual_time=VirtualTime(0.0), source_id=None), 0.0)
    rec = m.get_series().records[-1]
    assert rec.value == pytest.approx(1 / 3) and float(dict(rec.tags)["weighted"]) == 0.5
    m.on_event(AgentStateChangedEvent(event_id=EventId(1), virtual_time=VirtualTime(1.0), source_id=B,
                                      agent_id=B, state_snapshot={"opinion": 1}), 1.0)
    m.on_event(TickEvent(event_id=EventId(2), virtual_time=VirtualTime(1.0), source_id=None), 1.0)
    rec = m.get_series().records[-1]
    assert rec.value == pytest.approx(2 / 3) and float(dict(rec.tags)["weighted"]) == 0.75
