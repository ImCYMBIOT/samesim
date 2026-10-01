"""Unit tests for SirEpidemicBehavior and SIR metrics."""
import random
import pytest
from samesim.domain.ids import AgentId, MessageId, VirtualTime
from samesim.domain.message import Message
from samesim.domain.state import AgentState
from samesim.plugins.behaviors.sir_behavior import SirEpidemicBehavior
from samesim.plugins.metrics.sir_metrics import SirSusceptibleMetric, SirInfectedMetric, SirRecoveredMetric
from samesim.core.agent_registry import AgentRegistry


def test_sir_initialization():
    behavior = SirEpidemicBehavior()
    # config specifies 2 initial infected
    config = {"initial_infected": 2}
    
    state0 = behavior.initialize(AgentId(0), config, random.Random(0))
    state1 = behavior.initialize(AgentId(1), config, random.Random(1))
    state2 = behavior.initialize(AgentId(2), config, random.Random(2))
    
    assert state0.get("status") == "I"
    assert state1.get("status") == "I"
    assert state2.get("status") == "S"


def test_sir_step_infection():
    behavior = SirEpidemicBehavior()
    # beta=1.0 guarantees infection if there is at least one contact
    behavior._beta = 1.0
    behavior._agent_rngs[AgentId(0)] = random.Random(42)
    
    state = AgentState(data={"status": "S"})
    inbox = [Message(message_id=MessageId(1), sender_id=AgentId(1), recipient_id=AgentId(0), payload={"status": "I"})]
    
    result = behavior.step(
        agent_id=AgentId(0),
        current_state=state,
        inbox=inbox,
        neighbors=frozenset({AgentId(1)}),
        virtual_time=VirtualTime(1.0)
    )
    
    assert result.next_state.get("status") == "I"


def test_sir_step_recovery():
    behavior = SirEpidemicBehavior()
    # gamma=1.0 guarantees recovery
    behavior._gamma = 1.0
    behavior._agent_rngs[AgentId(0)] = random.Random(42)
    
    state = AgentState(data={"status": "I"})
    
    result = behavior.step(
        agent_id=AgentId(0),
        current_state=state,
        inbox=[],
        neighbors=frozenset(),
        virtual_time=VirtualTime(1.0)
    )
    
    assert result.next_state.get("status") == "R"
    assert len(result.outbound_messages) == 0


def test_sir_metrics():
    registry = AgentRegistry()
    registry.create_agent(initial_state=AgentState(data={"status": "S"}))
    registry.create_agent(initial_state=AgentState(data={"status": "I"}))
    registry.create_agent(initial_state=AgentState(data={"status": "R"}))
    registry.create_agent(initial_state=AgentState(data={"status": "S"}))
    
    s_metric = SirSusceptibleMetric()
    i_metric = SirInfectedMetric()
    r_metric = SirRecoveredMetric()
    
    # Manually populate their agent states as if events had fired
    from samesim.domain.event import AgentStateChangedEvent, TickEvent
    
    for aid in registry.all_agent_ids():
        agent = registry.get(aid)
        state_event = AgentStateChangedEvent(
            event_id=MessageId(int(aid)),
            virtual_time=VirtualTime(0.0),
            agent_id=aid,
            state_snapshot=agent.state.to_dict()
        )
        s_metric.on_event(state_event, VirtualTime(0.0))
        i_metric.on_event(state_event, VirtualTime(0.0))
        r_metric.on_event(state_event, VirtualTime(0.0))
        
    tick = TickEvent(event_id=MessageId(10), virtual_time=VirtualTime(0.0))
    s_metric.on_event(tick, VirtualTime(0.0))
    i_metric.on_event(tick, VirtualTime(0.0))
    r_metric.on_event(tick, VirtualTime(0.0))
    
    assert s_metric.get_series().records[0].value == 2.0
    assert i_metric.get_series().records[0].value == 1.0
    assert r_metric.get_series().records[0].value == 1.0


def test_first_step_is_an_announcement_round():
    """At t=0 nobody has communicated yet: infected agents expose their
    neighbors and nobody changes state -- not even with certain recovery or
    certain infection. Otherwise the initially infected would take a recovery
    draw before ever exposing anyone (standard discrete SIR, and NDlib, let
    them infect first)."""
    import random as _random
    from samesim.domain.ids import AgentId as _Id
    b = SirEpidemicBehavior()
    config = {"transmission_rate": 1.0, "recovery_rate": 1.0, "initial_infected": 1}
    infected = b.initialize(_Id(0), config, _random.Random(0))
    susceptible = b.initialize(_Id(1), config, _random.Random(1))
    r = b.step(_Id(0), infected, [], frozenset({_Id(1)}), VirtualTime(0.0))
    assert r.next_state.get("status") == "I" and len(r.outbound_messages) == 1
    r = b.step(_Id(1), susceptible, [], frozenset({_Id(0)}), VirtualTime(0.0))
    assert r.next_state.get("status") == "S" and not r.outbound_messages
    # From t=1 on the usual transitions apply.
    r = b.step(_Id(0), infected, [], frozenset({_Id(1)}), VirtualTime(1.0))
    assert r.next_state.get("status") == "R"
