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
samesim/ports/communication.py:

    broadcast=False  ->  recipients subset of {recipient_id}
    broadcast=True   ->  recipients subset of neighbors(sender_id)

plus the practical invariant that a lossless protocol delivers each
intended copy exactly once -- never zero times, never d times. "Intended" is
read off the messages (addressed -> its recipient; broadcast -> every
neighbor), and the behavior side is checked too: an addressed message must
name an actual neighbor.

It also enforces the latency contract: every delay a protocol returns is
None or a finite number > 0. The engine rejects anything else at run time;
checking here catches it at the plugin, for every protocol, before any
experiment runs.
"""
from __future__ import annotations

import importlib
import inspect
import math
import pkgutil
import random

import pytest

import samesim.plugins.behaviors as behaviors_pkg
import samesim.plugins.communication as communication_pkg
from samesim.domain.delivery import as_delivery
from samesim.domain.ids import AgentId
from samesim.domain.state import AgentState
from samesim.domain.topology import TopologyGraph
from samesim.ports.behavior import BehaviorPort
from samesim.ports.communication import CommunicationProtocolPort


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
def _first_traffic(behavior_cls, sender, neighbors):
    """What `sender` sends on its first step and on the timers that step sets."""
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
    outbound = list(result.outbound_messages)
    # Event-driven behaviors typically only set timers on their first step
    # and send from on_timer(). Follow those timers, or such behaviors would
    # be skipped -- silently leaving them outside this contract.
    for timer in result.set_timers:
        fired = behavior.on_timer(sender, result.next_state, timer.tag, neighbors, timer.delay)
        outbound.extend(fired.outbound_messages)
    return outbound


@pytest.mark.parametrize("protocol_cls", PROTOCOLS, ids=lambda c: c.__name__)
@pytest.mark.parametrize("behavior_cls", BEHAVIORS, ids=lambda c: c.__name__)
def test_every_behavior_protocol_pair_delivers_once_per_neighbor(behavior_cls, protocol_cls):
    # Try the sender in every role the star offers -- the centre (agent 0)
    # and a leaf. A behavior can give agents roles by id (QueueBehavior's
    # agent 0 is a server that never sends), and testing only the centre
    # would skip such a behavior entirely. Skip only if NO role sends.
    topology, _ = _star_topology()
    cases = []
    for sender in (AgentId(0), AgentId(1)):
        outbound = _first_traffic(behavior_cls, sender, topology.neighbors(sender))
        if outbound:
            cases.append((sender, outbound))
    if not cases:
        pytest.skip(f"{behavior_cls.__name__} sends nothing on its first step or first timers, in any role")
    for sender, outbound in cases:
        _check_deliveries(behavior_cls, protocol_cls, topology, sender, outbound)


def _check_deliveries(behavior_cls, protocol_cls, topology, sender, outbound):
    neighbors = topology.neighbors(sender)
    protocol = protocol_cls()
    protocol.initialize(topology, PROTOCOL_CONFIG, random.Random(1))

    # Behavior side of the contract: an addressed message must name an actual
    # neighbor. Addressing yourself is how a broadcast intent once went wrong
    # (SIR + GossipProtocol delivered only to the sender), and an expectation
    # derived from the messages alone would take that at face value.
    for message in outbound:
        if not message.broadcast:
            assert message.recipient_id in neighbors, (
                f"{behavior_cls.__name__} addressed a message to {message.recipient_id}, "
                f"which is not a neighbor of the sender {sender}. To reach the whole "
                f"neighborhood, send ONE message with broadcast=True."
            )

    # Intended recipients, read off the messages: an addressed message means
    # its recipient; a broadcast means every neighbor. Not every behavior
    # wants to reach every neighbor (AsyncGossip contacts one per clock tick).
    expected = {AgentId(i): 0 for i in range(STAR_SIZE)}
    for message in outbound:
        if message.broadcast:
            for n in neighbors:
                expected[n] += 1
        else:
            expected[message.recipient_id] += 1

    counts = {AgentId(i): 0 for i in range(STAR_SIZE)}
    for message in outbound:
        for item in protocol.route(message, sender, topology):
            delivery = as_delivery(item)
            recipient_id = delivery.recipient_id
            assert delivery.delay is None or (
                isinstance(delivery.delay, (int, float))
                and not isinstance(delivery.delay, bool)
                and math.isfinite(delivery.delay)
                and delivery.delay > 0
            ), (
                f"{protocol_cls.__name__} returned delay={delivery.delay!r}; a delay "
                f"must be None or a finite number > 0"
            )
            # Protocol side: recipients must be authorised by the addressing mode.
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

    got = [counts[a] for a in sorted(counts)]
    want = [expected[a] for a in sorted(expected)]
    assert got == want, (
        f"{behavior_cls.__name__} + {protocol_cls.__name__} delivered {got} copies "
        f"per agent (agent {sender} is the sender); the messages asked for {want}. Under a "
        f"lossless protocol each intended copy must arrive exactly once. A multiple "
        f"of the intended count means the behavior enumerated neighbors AND the "
        f"protocol fanned out (deliveries multiplied by degree); fewer means "
        f"messages never reached their recipients."
    )
