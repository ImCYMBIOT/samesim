"""RaftElectionBehavior: each transition of Raft's election rules (§5.2)."""
from __future__ import annotations

import random

import pytest

from simul8.domain.event import AgentStateChangedEvent
from simul8.domain.ids import AgentId, EventId, MessageId, VirtualTime
from simul8.domain.message import Message
from simul8.plugins.behaviors.raft_election import RaftElectionBehavior
from simul8.plugins.metrics.raft_metrics import RaftElectionMetric

A, B, C = AgentId(0), AgentId(1), AgentId(2)
ALL = frozenset({A, B, C})


def _cluster(n=3):
    r = RaftElectionBehavior()
    states = {AgentId(i): r.initialize(AgentId(i), {}, random.Random(i)) for i in range(n)}
    return r, states


def _msg(sender, kind, term, to=None):
    return Message(message_id=MessageId(99), sender_id=sender, recipient_id=to or sender,
                   payload={"kind": kind, "term": term}, broadcast=to is None)


def test_event_activation_only():
    assert RaftElectionBehavior.activation_modes == frozenset({"event"})


def test_bootstrap_arms_a_randomized_election_timer():
    r, s = _cluster()
    delays = [r.step(a, s[a], [], ALL - {a}, 0.0).set_timers[0].delay for a in (A, B, C)]
    assert all(150 <= d <= 300 for d in delays) and len(set(delays)) == 3


def test_timeout_starts_an_election_in_the_next_term():
    r, s = _cluster()
    res = r.on_timer(A, s[A], "election", ALL - {A}, 200.0)
    st = res.next_state.data
    assert (st["role"], st["term"], st["voted_for"], st["votes"]) == ("candidate", 1, 0, [0])
    assert [(m.get("kind"), m.broadcast) for m in res.outbound_messages] == [("request_vote", True)]
    assert [t.tag for t in res.set_timers] == ["election"], "candidate re-arms its timeout"


def test_majority_of_votes_makes_a_leader_that_heartbeats():
    r, s = _cluster()
    cand = r.on_timer(A, s[A], "election", ALL - {A}, 200.0).next_state
    res = r.step(A, cand, [_msg(B, "vote", 1, to=A)], ALL - {A}, 210.0)
    assert res.next_state.get("role") == "leader" and res.next_state.get("leader_id") == 0
    assert [m.get("kind") for m in res.outbound_messages] == ["heartbeat"]
    assert [t.tag for t in res.set_timers] == ["heartbeat"]
    assert res.cancel_timers == frozenset({"election"})


def test_votes_at_most_once_per_term():
    r, s = _cluster()
    first = r.step(C, s[C], [_msg(A, "request_vote", 1)], ALL - {C}, 200.0)
    assert [(m.get("kind"), m.recipient_id) for m in first.outbound_messages] == [("vote", A)]
    second = r.step(C, first.next_state, [_msg(B, "request_vote", 1)], ALL - {C}, 201.0)
    assert second.outbound_messages == []
    # ...but a new term is a new vote.
    third = r.step(C, second.next_state, [_msg(B, "request_vote", 2)], ALL - {C}, 400.0)
    assert [(m.get("kind"), m.recipient_id) for m in third.outbound_messages] == [("vote", B)]


def test_granting_a_vote_resets_the_election_timer():
    r, s = _cluster()
    res = r.step(C, s[C], [_msg(A, "request_vote", 1)], ALL - {C}, 200.0)
    assert [t.tag for t in res.set_timers] == ["election"]


def test_heartbeat_makes_a_candidate_follow_the_leader():
    r, s = _cluster()
    cand = r.on_timer(B, s[B], "election", ALL - {B}, 200.0).next_state
    res = r.step(B, cand, [_msg(A, "heartbeat", 1)], ALL - {B}, 210.0)
    assert (res.next_state.get("role"), res.next_state.get("leader_id")) == ("follower", 0)


def test_higher_term_deposes_a_leader():
    r, s = _cluster()
    cand = r.on_timer(A, s[A], "election", ALL - {A}, 200.0).next_state
    leader = r.step(A, cand, [_msg(B, "vote", 1, to=A)], ALL - {A}, 210.0).next_state
    res = r.step(A, leader, [_msg(C, "request_vote", 5)], ALL - {A}, 300.0)
    st = res.next_state.data
    assert (st["role"], st["term"], st["voted_for"]) == ("follower", 5, 2)
    assert "heartbeat" in res.cancel_timers
    assert [t.tag for t in res.set_timers] == ["election"]


def test_stale_messages_are_ignored():
    r, s = _cluster()
    newer = r.step(C, s[C], [_msg(A, "request_vote", 3)], ALL - {C}, 200.0).next_state
    res = r.step(C, newer, [_msg(B, "request_vote", 2), _msg(B, "heartbeat", 2)], ALL - {C}, 250.0)
    assert res.outbound_messages == [] and res.next_state.data == newer.data


def test_single_agent_cluster_elects_itself():
    r, s = _cluster(n=1)
    res = r.on_timer(A, s[A], "election", frozenset(), 200.0)
    assert res.next_state.get("role") == "leader"


@pytest.mark.parametrize("config,match", [
    ({"election_timeout_min": 300, "election_timeout_max": 150}, "election_timeout_min <= election_timeout_max"),
    ({"election_timeout_min": 0}, "0 < election_timeout_min"),
    ({"heartbeat_interval": 0}, "heartbeat_interval must be > 0"),
])
def test_invalid_config(config, match):
    with pytest.raises(ValueError, match=match):
        RaftElectionBehavior().initialize(A, config, random.Random(1))


def test_metric_flags_two_leaders_in_one_term():
    m = RaftElectionMetric()
    def became(agent, term, t):
        m.on_event(AgentStateChangedEvent(event_id=EventId(0), virtual_time=VirtualTime(t),
                                          agent_id=agent, state_snapshot={"role": "leader", "term": term}),
                   VirtualTime(t))
    became(A, 1, 10.0)
    assert m.violations == 0
    became(B, 1, 12.0)
    assert m.violations == 1
    events = [dict(r.tags)["event"] for r in m.get_series().records]
    assert events == ["elected", "elected", "SAFETY_VIOLATION"]
