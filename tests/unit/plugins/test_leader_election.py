"""Unit tests for LeaderElectionBehavior and LeaderConsensusMetric."""
import random
import pytest
from simul8.domain.ids import AgentId, MessageId, VirtualTime
from simul8.domain.message import Message
from simul8.domain.state import AgentState
from simul8.plugins.behaviors.leader_election import LeaderElectionBehavior
from simul8.plugins.metrics.leader_metrics import LeaderConsensusMetric
from simul8.domain.topology import TopologyGraph


def test_leader_election_initialization():
    behavior = LeaderElectionBehavior()
    rng = random.Random(42)
    state = behavior.initialize(AgentId(0), {}, rng)
    
    uid = state.get("uid")
    leader_id = state.get("leader_id")
    
    assert uid is not None
    assert leader_id == uid
    assert isinstance(uid, int)


def test_leader_election_step_adoption():
    behavior = LeaderElectionBehavior()
    # Initialize state with a low UID
    state = AgentState(data={"uid": 100, "leader_id": 100})
    
    # Inbox contains a higher leader ID
    inbox = [
        Message(message_id=MessageId(1), sender_id=AgentId(1), recipient_id=AgentId(0), payload={"leader_id": 200}),
        Message(message_id=MessageId(2), sender_id=AgentId(2), recipient_id=AgentId(0), payload={"leader_id": 150}),
    ]
    
    result = behavior.step(
        agent_id=AgentId(0),
        current_state=state,
        inbox=inbox,
        neighbors=frozenset({AgentId(1), AgentId(2)}),
        virtual_time=VirtualTime(1.0)
    )
    
    assert result.next_state.get("leader_id") == 200
    assert len(result.outbound_messages) == 2
    # Outbound messages should advertise the newly adopted leader
    for msg in result.outbound_messages:
        assert msg.get("leader_id") == 200


def test_leader_consensus_metric():
    # Plain domain data -- a metric plugin is testable with no core objects.
    aid0, aid1, aid2 = AgentId(0), AgentId(1), AgentId(2)
    initial_states = {
        aid0: {"uid": 10, "leader_id": 10},
        aid1: {"uid": 50, "leader_id": 50},
        aid2: {"uid": 30, "leader_id": 30},
    }

    metric = LeaderConsensusMetric()
    metric.on_setup(TopologyGraph(agent_ids=frozenset(initial_states), adjacency={}), initial_states)
    
    # True leader should be 50 (max UID)
    assert metric._true_leader_id == 50
    
    # Initially, only agent 1 points to 50
    # Consensus fraction should be 1/3
    from simul8.domain.event import TickEvent
    metric.on_event(TickEvent(event_id=MessageId(1), virtual_time=VirtualTime(0.0)), VirtualTime(0.0))
    
    series = metric.get_series()
    assert len(series.records) == 1
    assert series.records[0].value == pytest.approx(1/3)
