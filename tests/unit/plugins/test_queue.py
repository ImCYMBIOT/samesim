"""QueueBehavior and QueueMetric: FIFO service, timing, recovery, Little's law."""
from __future__ import annotations

import csv
import random

import yaml

from samesim.app.experiment_runner import ExperimentRunner
from samesim.domain.event import AgentStateChangedEvent, TickEvent
from samesim.domain.ids import AgentId, EventId, VirtualTime
from samesim.plugins.behaviors.queue import DEPARTURE, QueueBehavior
from samesim.plugins.metrics.queue_metrics import QueueMetric

S, A, B = AgentId(0), AgentId(1), AgentId(2)


def _behavior():
    q = QueueBehavior()
    states = {a: q.initialize(a, {"arrival_rate": 0.5, "service_rate": 1.0}, random.Random(int(a)))
              for a in (S, A, B)}
    return q, states


def _customer():
    from samesim.domain.ids import MessageId
    from samesim.domain.message import Message
    return Message(message_id=MessageId(1), sender_id=A, recipient_id=S, payload={"customer": True})


def test_fifo_waits_and_sojourns():
    q, st = _behavior()
    server = st[S]
    # Two customers arrive at t=1: the first starts service at once.
    r = q.step(S, server, [_customer(), _customer()], frozenset({A}), VirtualTime(1.0))
    server = r.next_state
    assert server.get("queue") == [1.0, 1.0] and server.get("in_service_since") == 1.0
    assert [t.tag for t in r.set_timers] == [DEPARTURE]
    # First departs at t=3: waited 0, in system 2; the second starts service.
    r = q.on_timer(S, server, DEPARTURE, frozenset({A}), VirtualTime(3.0))
    server = r.next_state
    assert (server.get("last_wait"), server.get("last_sojourn")) == (0.0, 2.0)
    assert server.get("queue") == [1.0] and server.get("in_service_since") == 3.0
    # Second departs at t=4: waited 2 (from 1 to 3), in system 3.
    r = q.on_timer(S, server, DEPARTURE, frozenset({A}), VirtualTime(4.0))
    server = r.next_state
    assert (server.get("last_wait"), server.get("last_sojourn")) == (2.0, 3.0)
    assert server.get("queue") == [] and server.get("in_service_since") is None
    assert server.get("served") == 2 and not r.set_timers


def test_a_customer_arriving_while_busy_waits():
    q, st = _behavior()
    r = q.step(S, st[S], [_customer()], frozenset({A}), VirtualTime(1.0))
    r = q.step(S, r.next_state, [_customer()], frozenset({A}), VirtualTime(1.5))
    assert r.next_state.get("queue") == [1.0, 1.5]
    assert not r.set_timers, "service already running; a new arrival must not restart it"


def test_only_neighbors_of_the_server_generate_customers():
    q, st = _behavior()
    assert q.step(A, st[A], [], frozenset({S}), VirtualTime(0.0)).set_timers
    assert not q.step(B, st[B], [], frozenset({A}), VirtualTime(0.0)).set_timers


def test_recovered_server_restarts_service_of_the_head_customer():
    q, st = _behavior()
    busy = q.step(S, st[S], [_customer(), _customer()], frozenset({A}), VirtualTime(1.0)).next_state
    r = q.on_recover(S, busy, frozenset({A}), VirtualTime(9.0))
    assert r.next_state.get("in_service_since") == 9.0
    assert [t.tag for t in r.set_timers] == [DEPARTURE]
    idle = st[S]
    assert not q.on_recover(S, idle, frozenset({A}), VirtualTime(9.0)).set_timers


def test_metric_integrates_number_in_system():
    m = QueueMetric()

    def server(t, queue, served=0, wait=None, sojourn=None):
        m.on_event(AgentStateChangedEvent(event_id=EventId(0), virtual_time=VirtualTime(t), source_id=S,
                                          agent_id=S, state_snapshot={
                                              "role": "server", "queue": queue, "served": served,
                                              "last_wait": wait, "last_sojourn": sojourn}), t)

    server(1.0, [1.0])               # N=1 from t=1
    server(2.0, [1.0, 2.0])          # N=2 from t=2
    server(4.0, [2.0], 1, 0.0, 3.0)  # N=1 from t=4, one departure
    m.on_event(TickEvent(event_id=EventId(0), virtual_time=VirtualTime(5.0), source_id=None), 5.0)
    rows = m.get_series().records
    departures = [r for r in rows if dict(r.tags)["kind"] == "departure"]
    areas = [r for r in rows if dict(r.tags)["kind"] == "area"]
    assert [(r.value, dict(r.tags)["sojourn"]) for r in departures] == [(0.0, "3.0")]
    assert areas[-1].value == 1 * 1 + 2 * 2 + 1 * 1  # area under N(t) on [0, 5]


def test_littles_law_holds_within_a_run(tmp_path):
    """L = lambda_eff * W holds for every sample path (up to edge effects),
    so it checks the metric's bookkeeping independently of the M/M/1
    closed forms and of seed noise."""
    cfg = {
        "schema_version": "1.0",
        "experiment": {"name": "q", "seed": 3},
        "simulation": {"num_agents": 3, "max_virtual_time": 4000.0, "tick_interval": 50.0,
                       "activation": "event"},
        "plugins": {
            "behavior": "samesim.plugins.behaviors.queue.QueueBehavior",
            "communication": "samesim.plugins.communication.latency.LatencyProtocol",
            "topology": "samesim.plugins.topologies.ring.RingTopology",
            "metrics": ["samesim.plugins.metrics.queue_metrics.QueueMetric"],
            "persistence": ["samesim.plugins.persistence.csv_exporter.CsvExporter"],
        },
        "plugin_configs": {
            "QueueBehavior": {"arrival_rate": 0.35, "service_rate": 1.0},
            "LatencyProtocol": {"distribution": "constant", "delay": 0.01},
        },
    }
    path = tmp_path / "q.yaml"
    path.write_text(yaml.safe_dump(cfg))
    ExperimentRunner().run(path, output_dir=tmp_path / "out")
    with open(tmp_path / "out" / "q_queue.csv", newline="") as f:
        rows = list(csv.DictReader(l for l in f if not l.startswith("#")))
    dep = [r for r in rows if r["kind"] == "departure"]
    area = [r for r in rows if r["kind"] == "area"]
    T = float(area[-1]["virtual_time"])
    L = float(area[-1]["value"]) / T
    W = sum(float(r["sojourn"]) for r in dep) / len(dep)
    assert len(dep) > 2000  # two sources at 0.35 each, rho = 0.7
    assert abs(L - (len(dep) / T) * W) / L < 0.02
