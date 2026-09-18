"""
Regression test: the engine must fully process every event AT
max_virtual_time, not just the first one.

Bug history: SimulationEngine.run() used to break out of its dispatch loop
immediately after processing the first event whose virtual_time reached
max_virtual_time, rather than draining every event scheduled at that same
instant. Since multiple events routinely share a virtual_time (a tick's
worth of message deliveries all land together), this silently dropped most
of the final tick's activity -- the tick AT max_virtual_time never actually
ran, and most of the message batch delivered at that instant was never
processed. Found via a message-count closed-form sanity check.

This test locks in the fix with the smallest case that reproduces it:
5 agents on a ring (fan_out=2, so every agent has exactly enough neighbors
to always send exactly 2 messages/tick), max_virtual_time=3.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from simul8.app.experiment_runner import ExperimentRunner

CONFIG = """\
schema_version: "1.0"

experiment:
  name: "termination_boundary"
  seed: 1

simulation:
  num_agents: 5
  max_virtual_time: 3
  tick_interval: 1

plugins:
  behavior: "simul8.plugins.behaviors.gossip_behavior.GossipBehavior"
  communication: "simul8.plugins.communication.gossip.GossipProtocol"
  topology: "simul8.plugins.topologies.ring.RingTopology"
  metrics:
    - "simul8.plugins.metrics.message_count.MessageCountMetric"
    - "simul8.plugins.metrics.convergence.ConvergenceMetric"
  persistence:
    - "simul8.plugins.persistence.csv_exporter.CsvExporter"

plugin_configs:
  GossipBehavior:
    fan_out: 2
"""


@pytest.fixture
def config(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(CONFIG, encoding="utf-8")
    return config_path, tmp_path / "results"


def _rows(path: Path) -> list[str]:
    return [l for l in path.read_text().splitlines() if not l.startswith("#") and l.strip()]


def test_final_tick_at_max_virtual_time_actually_runs(config):
    """ConvergenceMetric samples once per TickEvent -- with max_virtual_time=3
    and tick_interval=1, ticks occur at t=0,1,2,3, so there must be exactly
    4 sampled rows (plus the header)."""
    config_path, output_dir = config
    ExperimentRunner().run(config_path, output_dir)

    rows = _rows(output_dir / "termination_boundary_convergence_variance.csv")
    times = [float(r.split(",")[0]) for r in rows[1:]]
    assert times == [0.0, 1.0, 2.0, 3.0], (
        f"Expected ticks at t=0,1,2,3; got {times}. "
        f"If t=3 is missing, the final tick never dispatched."
    )


def test_final_batch_of_messages_fully_delivered(config):
    """With 5 agents each sending fan_out=2 messages every tick, exactly
    5*2=10 messages must be delivered at each of t=1, t=2, and t=3 (from
    ticks t=0, t=1, t=2 respectively) -- including the final batch, not
    just the first message of it."""
    config_path, output_dir = config
    ExperimentRunner().run(config_path, output_dir)

    rows = _rows(output_dir / "termination_boundary_message_count.csv")
    by_time: dict[float, float] = {}
    for r in rows[1:]:
        t, v = r.split(",")
        by_time[float(t)] = float(v)  # cumulative count, last value per tick wins

    assert by_time[1.0] == 10, f"Expected 10 cumulative at t=1, got {by_time[1.0]}"
    assert by_time[2.0] == 20, f"Expected 20 cumulative at t=2, got {by_time[2.0]}"
    assert by_time[3.0] == 30, (
        f"Expected 30 cumulative at t=3, got {by_time[3.0]} -- "
        f"the final tick's message batch was not fully delivered."
    )
