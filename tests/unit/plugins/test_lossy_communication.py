"""Unit tests for LossyProtocol."""
import random
from simul8.domain.ids import AgentId, MessageId
from simul8.domain.message import Message
from simul8.domain.topology import TopologyGraph
from simul8.plugins.communication.lossy import LossyProtocol


def test_lossy_protocol_drop_all():
    protocol = LossyProtocol()
    topology = TopologyGraph(agent_ids=frozenset({AgentId(0), AgentId(1)}), adjacency={})
    
    # 1.0 probability means 100% message loss
    protocol.initialize(topology, {"loss_probability": 1.0}, random.Random(42))
    
    msg = Message(message_id=MessageId(1), sender_id=AgentId(0), recipient_id=AgentId(1), payload={})
    deliveries = protocol.route(msg, AgentId(0), topology)
    
    assert len(deliveries) == 0


def test_lossy_protocol_keep_all():
    protocol = LossyProtocol()
    topology = TopologyGraph(agent_ids=frozenset({AgentId(0), AgentId(1)}), adjacency={})
    
    # 0.0 probability means 0% message loss (pass-through)
    protocol.initialize(topology, {"loss_probability": 0.0}, random.Random(42))
    
    msg = Message(message_id=MessageId(1), sender_id=AgentId(0), recipient_id=AgentId(1), payload={})
    deliveries = protocol.route(msg, AgentId(0), topology)
    
    assert len(deliveries) == 1
    assert deliveries[0][0] == AgentId(1)
    assert deliveries[0][1] is msg
