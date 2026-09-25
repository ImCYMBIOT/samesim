"""CommunicationLayer normalizes route() output and enforces the latency contract."""
from __future__ import annotations

import pytest

from simul8.core.communication_layer import CommunicationLayer
from simul8.domain.delivery import Delivery
from simul8.domain.ids import AgentId, MessageId
from simul8.domain.message import Message
from simul8.domain.topology import TopologyGraph
from simul8.ports.communication import CommunicationProtocolPort

A, B = AgentId(0), AgentId(1)
GRAPH = TopologyGraph(agent_ids=frozenset({A, B}), adjacency={A: frozenset({B}), B: frozenset({A})})
MSG = Message(message_id=MessageId(1), sender_id=A, recipient_id=B, payload={})


class _Returns(CommunicationProtocolPort):
    def __init__(self, items):
        self.items = items

    def initialize(self, topology, config, rng): ...

    def route(self, message, sender_id, topology):
        return self.items


def test_bare_tuples_mean_default_latency():
    out = CommunicationLayer(_Returns([(B, MSG)])).route(MSG, A, GRAPH)
    assert out == [Delivery(B, MSG, None)]


def test_deliveries_pass_through_and_are_counted():
    layer = CommunicationLayer(_Returns([Delivery(B, MSG, 2.5), (B, MSG)]))
    assert [d.delay for d in layer.route(MSG, A, GRAPH)] == [2.5, None]
    assert layer.messages_sent == 1


@pytest.mark.parametrize("bad", [0, -0.5, float("nan"), float("-inf"), True, "1.0"])
def test_illegal_delays_are_rejected_naming_the_protocol(bad):
    with pytest.raises(ValueError, match="_Returns.route"):
        CommunicationLayer(_Returns([Delivery(B, MSG, bad)])).route(MSG, A, GRAPH)
