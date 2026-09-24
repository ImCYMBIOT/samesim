"""
Contract test: every behavior must be safe to pair with every protocol.

This is the structural guard against a whole class of bug, not a test of
one plugin pair. It DISCOVERS behaviors and protocols by walking the
plugins package, so a newly added plugin is covered automatically -- nobody
has to remember to extend this file.

The bug class it prevents: a behavior that enumerates its own neighbors
(one addressed message each) paired with a protocol that also fans out to
all neighbors produces deg(sender) copies per neighbor. That does not
crash; it silently multiplies effective message/transmission rates, which
is why it survived in the codebase long enough to skew a published-looking
epidemic curve by ~28% before an external cross-check caught it.

The rule enforced here is the addressing contract from
simul8/ports/communication.py:

    broadcast=False  ->  recipients subset of {recipient_id}
    broadcast=True   ->  recipients subset of neighbors(sender_id)

plus the practical invariant that a lossless protocol delivers to each
intended neighbor exactly once -- never zero times, never d times.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
import random

import pytest

import simul8.plugins.behaviors as behaviors_pkg
import simul8.plugins.communication as communication_pkg
from simul8.domain.ids import AgentId
from simul8.domain.state import AgentState
from simul8.domain.topology import TopologyGraph
from simul8.ports.behavior import BehaviorPort
from simul8.ports.communication import CommunicationProtocolPort


def _discover(package, base_class) -> list[type]:
    """Find every concrete subclass of base_class in a plugins subpackage."""
    found: list[type] = []
    for _finder, name, _ispkg in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{package.__name__}.{name}")
        for _attr, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, base_class)
                and obj is not base_class
                and not inspect.isabstract(obj)
                and obj.__module__ == module.__name__
            ):
                found.append(obj)
    return sorted(set(found), key=lambda c: c.__name__)


BEHAVIORS = _discover(behaviors_pkg, BehaviorPort)
PROTOCOLS = _discover(communication_pkg, CommunicationProtocolPort)

# Config generous enough that any shipped behavior produces outbound traffic
# on its first step: fan_out covers gossip, initial_infected covers SIR.
BEHAVIOR_CONFIG = {
    "fan_out": 4,
    "initial_infected": 99,
    "initial_value_range": [0.0, 1.0],
}
# Lossless so every intended delivery must actually land.
PROTOCOL_CONFIG = {"loss_probability": 0.0}

STAR_SIZE = 5  # agent 0 at the centre, agents 1..4 as its neighbors


def _star_topology() -> tuple[TopologyGraph, frozenset]:
    ids = [AgentId(i) for i in range(STAR_SIZE)]
    adjacency = {AgentId(0): frozenset(ids[1:])}
    for i in range(1, STAR_SIZE):
        adjacency[AgentId(i)] = frozenset({AgentId(0)})
    return (
        TopologyGraph(agent_ids=frozenset(ids), adjacency=adjacency),
        adjacency[AgentId(0)],
    )


def test_discovery_found_the_plugins():
    """Guard the guard: if discovery silently finds nothing, the matrix
    below would vacuously pass."""
    assert len(BEHAVIORS) >= 3, f"Expected to discover behaviors, got {BEHAVIORS}"
    assert len(PROTOCOLS) >= 3, f"Expected to discover protocols, got {PROTOCOLS}"


@pytest.mark.parametrize("protocol_cls", PROTOCOLS, ids=lambda c: c.__name__)
@pytest.mark.parametrize("behavior_cls", BEHAVIORS, ids=lambda c: c.__name__)
def test_every_behavior_protocol_pair_delivers_once_per_neighbor(behavior_cls, protocol_cls):
    topology, neighbors = _star_topology()
    sender = AgentId(0)

    behavior = behavior_cls()
    rng = random.Random(1)
    state = behavior.initialize(sender, BEHAVIOR_CONFIG, rng)
    # Behaviors that keep per-agent RNGs look them up by id during step().
    if hasattr(behavior, "_agent_rngs"):
        behavior._agent_rngs[sender] = random.Random(1)
    # SIR only emits while infected; force that state so it produces traffic.
    if "status" in state.data:
        state = AgentState(data={**state.data, "status": "I"})

    result = behavior.step(sender, state, [], neighbors, 0.0)
    if not result.outbound_messages:
        pytest.skip(f"{behavior_cls.__name__} sends nothing on its first step")

    protocol = protocol_cls()
    protocol.initialize(topology, PROTOCOL_CONFIG, random.Random(1))

    counts = {AgentId(i): 0 for i in range(STAR_SIZE)}
    for message in result.outbound_messages:
        for recipient_id, _delivered in protocol.route(message, sender, topology):
            # Contract: recipients must be authorised by the addressing mode.
            if message.broadcast:
                assert recipient_id in topology.neighbors(sender), (
                    f"{protocol_cls.__name__} delivered a broadcast message to "
                    f"{recipient_id}, which is not a neighbor of {sender}"
                )
            else:
                assert recipient_id == message.recipient_id, (
                    f"{protocol_cls.__name__} rerouted an addressed message from "
                    f"{message.recipient_id} to {recipient_id} -- protocols may drop "
                    f"or delay, never invent recipients"
                )
            counts[recipient_id] += 1

    assert counts[sender] == 0, (
        f"{behavior_cls.__name__} + {protocol_cls.__name__} delivered to the sender "
        f"itself -- a broadcast-intent message must not be treated as addressed."
    )
    per_neighbor = [counts[n] for n in sorted(neighbors)]
    assert all(c == 1 for c in per_neighbor), (
        f"{behavior_cls.__name__} + {protocol_cls.__name__} delivered "
        f"{per_neighbor} per neighbor; expected exactly 1 each under a lossless "
        f"protocol. More than 1 means the behavior enumerated neighbors AND the "
        f"protocol fanned out (deliveries multiplied by degree); 0 means the "
        f"message never reached the neighborhood at all."
    )
