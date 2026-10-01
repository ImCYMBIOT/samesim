"""TraceDigestMetric: sensitive to every real difference, blind to incidental ones."""
from __future__ import annotations

from samesim.domain.event import AgentStateChangedEvent, MessageDeliveredEvent, TickEvent
from samesim.domain.ids import AgentId, EventId, MessageId, VirtualTime
from samesim.domain.message import Message
from samesim.domain.topology import TopologyGraph
from samesim.plugins.metrics.trace_digest import TraceDigestMetric

A, B = AgentId(0), AgentId(1)
GRAPH = TopologyGraph(agent_ids=frozenset({A, B}), adjacency={A: frozenset({B}), B: frozenset({A})})


def _digest(events, states=None, graph=GRAPH) -> str:
    m = TraceDigestMetric()
    m.on_setup(graph, states or {A: {"v": 1.0}, B: {"v": 2.0}})
    for e in events:
        m.on_event(e, e.virtual_time)
    return m.digest


def _deliver(event_id=0, payload=None, t=1.0, broadcast=False):
    msg = Message(message_id=MessageId(7), sender_id=A, recipient_id=B,
                  payload=payload if payload is not None else {"v": 1.0}, broadcast=broadcast)
    return MessageDeliveredEvent(event_id=EventId(event_id), virtual_time=VirtualTime(t),
                                 source_id=A, recipient_id=B, message=msg)


def _state(event_id=0, snapshot=None, t=1.0):
    return AgentStateChangedEvent(event_id=EventId(event_id), virtual_time=VirtualTime(t),
                                  source_id=A, agent_id=A,
                                  state_snapshot=snapshot if snapshot is not None else {"v": 1.5})


def test_identical_runs_have_identical_digests():
    assert _digest([_deliver(), _state()]) == _digest([_deliver(), _state()])


def test_engine_event_ids_are_ignored():
    """Renumbering events without changing the run must not look like a change."""
    assert _digest([_deliver(event_id=1), _state(event_id=2)]) == \
           _digest([_deliver(event_id=900), _state(event_id=901)])


def test_set_iteration_order_is_ignored():
    """Sets must not leak Python's per-process hash order into the digest."""
    a = _digest([_state(snapshot={"peers": {"x", "y", "z"}})])
    b = _digest([_state(snapshot={"peers": {"z", "y", "x"}})])
    assert a == b


def test_every_real_difference_changes_the_digest():
    base = _digest([_deliver(), _state()])
    variants = {
        "payload": _digest([_deliver(payload={"v": 1.0000000000000002}), _state()]),
        "delivery time": _digest([_deliver(t=2.0), _state()]),
        "addressing mode": _digest([_deliver(broadcast=True), _state()]),
        "state": _digest([_deliver(), _state(snapshot={"v": 1.6})]),
        "order": _digest([_state(), _deliver()]),
        "missing event": _digest([_deliver()]),
        "initial state": _digest([_deliver(), _state()], states={A: {"v": 1.0}, B: {"v": 2.5}}),
        "topology": _digest([_deliver(), _state()], graph=TopologyGraph(
            agent_ids=frozenset({A, B}), adjacency={A: frozenset(), B: frozenset()})),
    }
    unchanged = [name for name, d in variants.items() if d == base]
    assert not unchanged, f"Digest blind to: {unchanged}"


def test_a_record_per_tick():
    m = TraceDigestMetric()
    m.on_setup(GRAPH, {})
    for i, t in enumerate((0.0, 1.0, 2.0)):
        m.on_event(TickEvent(event_id=EventId(i), virtual_time=VirtualTime(t)), VirtualTime(t))
    records = m.get_series().records
    assert [r.virtual_time for r in records] == [0.0, 1.0, 2.0]
    assert len({dict(r.tags)["digest"] for r in records}) == 3
