"""The queue through the real engine matches Lindley's recursion, customer by customer.

For a FIFO single-server queue, each customer's wait is determined by the
interarrival and service times alone (Lindley, 1952):

    W_1 = 0,    W_{n+1} = max(0, W_n + S_n - A_{n+1})

where S_n is customer n's service time and A_{n+1} the gap before customer
n+1 arrives. This test replays the exact random draws SameSim's agents make
-- the source's interarrival gaps from its stream, the server's service
times from its own -- through the recursion, and requires every wait
recorded by the engine to match.

Unlike a comparison of averages with the M/M/1 closed forms, this has no
sampling noise: it checks the event ordering, timer replacement, message
delivery and the FIFO bookkeeping exactly, on every one of thousands of
customers.
"""
from __future__ import annotations

import csv
import random

import yaml

from samesim.app.experiment_runner import ExperimentRunner
from samesim.domain import portable_math

SEED, LAM, MU, LATENCY, HORIZON = 11, 0.9, 1.0, 0.001, 5000.0


def _draws(stream: str, rate: float):
    """The delays an agent's stream produces, as QueueBehavior draws them."""
    rng = random.Random(f"{SEED}/agent/{stream}")
    while True:
        d = portable_math.expovariate(rng, rate)
        if d > 0.0:
            yield d


def test_waits_match_lindley_recursion_exactly(tmp_path):
    cfg = {
        "schema_version": "1.0",
        "experiment": {"name": "lindley", "seed": SEED},
        "simulation": {"num_agents": 2, "max_virtual_time": HORIZON, "tick_interval": 100.0,
                       "activation": "event"},
        "plugins": {
            "behavior": "samesim.plugins.behaviors.queue.QueueBehavior",
            "communication": "samesim.plugins.communication.latency.LatencyProtocol",
            "topology": "samesim.plugins.topologies.ring.RingTopology",
            "metrics": ["samesim.plugins.metrics.queue_metrics.QueueMetric"],
            "persistence": ["samesim.plugins.persistence.csv_exporter.CsvExporter"],
        },
        "plugin_configs": {
            "QueueBehavior": {"arrival_rate": LAM, "service_rate": MU},
            "LatencyProtocol": {"distribution": "constant", "delay": LATENCY},
        },
    }
    path = tmp_path / "q.yaml"
    path.write_text(yaml.safe_dump(cfg))
    ExperimentRunner().run(path, output_dir=tmp_path / "out")
    with open(tmp_path / "out" / "lindley_queue.csv", newline="") as f:
        rows = list(csv.DictReader(l for l in f if not l.startswith("#")))
    engine_waits = [float(r["value"]) for r in rows if r["kind"] == "departure"]
    assert len(engine_waits) > 3000, "too few customers for a meaningful check"

    gaps, services = _draws("1", LAM), _draws("0", MU)  # agent 1 = source, 0 = server
    wait = 0.0
    for n, got in enumerate(engine_waits):
        if n > 0:
            wait = max(0.0, wait + service - next(gaps))
        else:
            next(gaps)  # the first gap only places the first arrival
        service = next(services)
        # Absolute event times vs. accumulated differences: rounding only.
        assert abs(got - wait) <= 1e-9 * max(1.0, wait), (
            f"customer {n}: engine recorded wait {got!r}, Lindley gives {wait!r}"
        )
