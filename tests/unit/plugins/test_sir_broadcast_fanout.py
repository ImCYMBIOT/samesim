"""
Regression test: SirEpidemicBehavior must send exactly one outbound message
per tick when infected, not one per neighbor.

Bug history: the behavior looped over every neighbor and addressed one
message to each -- correct for a pass-through protocol (GossipProtocol),
but SirEpidemicBehavior is paired with BroadcastProtocol, which ALSO fans
each message out to every neighbor of the sender (ignoring the message's
addressed recipient). The combination double-fanned-out: a degree-d
infected agent delivered d copies to each neighbor instead of 1, inflating
the effective transmission rate far above the configured beta. Found via
experiments/external_validation/sir_vs_ndlib.py (peak infection count was
~28% higher than an independent NDlib run of the same parameters on the
same graph); confirmed by tracing exact delivery counts on a tiny 4-agent
star topology.
"""
from __future__ import annotations

import random

from simul8.domain.ids import AgentId
from simul8.domain.state import AgentState
from simul8.domain.topology import TopologyGraph
from simul8.plugins.behaviors.sir_behavior import SirEpidemicBehavior
from simul8.plugins.communication.broadcast import BroadcastProtocol


def test_infected_agent_sends_exactly_one_message_per_tick():
    behavior = SirEpidemicBehavior()
    behavior._agent_rngs[AgentId(0)] = random.Random(1)
    state = AgentState(data={"status": "I"})
    neighbors = frozenset({AgentId(1), AgentId(2), AgentId(3)})

    result = behavior.step(AgentId(0), state, [], neighbors, 0.0)

    assert len(result.outbound_messages) == 1, (
        f"Expected exactly 1 outbound message (BroadcastProtocol fans it out), "
        f"got {len(result.outbound_messages)} -- indicates the behavior is "
        f"doing its own per-neighbor fan-out again, double-counting deliveries."
    )


def test_each_neighbor_receives_exactly_one_delivery_via_broadcast():
    """End-to-end through BroadcastProtocol.route(): every neighbor of an
    infected agent must receive exactly one copy of the infection message,
    regardless of the agent's degree."""
    agent_ids = [AgentId(i) for i in range(4)]
    adjacency = {
        AgentId(0): frozenset({AgentId(1), AgentId(2), AgentId(3)}),
        AgentId(1): frozenset({AgentId(0)}),
        AgentId(2): frozenset({AgentId(0)}),
        AgentId(3): frozenset({AgentId(0)}),
    }
    topology = TopologyGraph(agent_ids=frozenset(agent_ids), adjacency=adjacency)

    behavior = SirEpidemicBehavior()
    behavior._agent_rngs[AgentId(0)] = random.Random(1)
    state = AgentState(data={"status": "I"})
    result = behavior.step(AgentId(0), state, [], adjacency[AgentId(0)], 0.0)

    protocol = BroadcastProtocol()
    protocol.initialize(topology, {}, random.Random(1))

    deliveries_per_recipient: dict[int, int] = {1: 0, 2: 0, 3: 0}
    for msg in result.outbound_messages:
        for recipient_id, _delivered_msg in protocol.route(msg, AgentId(0), topology):
            deliveries_per_recipient[int(recipient_id)] += 1

    assert deliveries_per_recipient == {1: 1, 2: 1, 3: 1}, (
        f"Expected exactly 1 delivery per neighbor, got {deliveries_per_recipient} "
        f"-- a degree-3 infected agent should not deliver 3 copies to each neighbor."
    )
