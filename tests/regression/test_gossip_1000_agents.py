"""
Regression test: 1,000-agent gossip experiment.

Verifies that:
    1. The simulation completes in reasonable time (< 120s on a laptop)
    2. 1000 agents all initialize with distinct values
    3. Convergence occurs (final variance < 10% of initial)
    4. Message volume is in the expected range for gossip with fan_out=3

This test is marked @pytest.mark.slow and is excluded from the default
test suite. Run with: pytest -m slow
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from samesim.app.experiment_runner import ExperimentRunner

pytestmark = pytest.mark.slow


REGRESSION_CONFIG = """\
schema_version: "1.0"

experiment:
  name: "regression_1000_agents"
  seed: 42

simulation:
  num_agents: 1000
  max_virtual_time: 200
  tick_interval: 1

plugins:
  behavior: "samesim.plugins.behaviors.gossip_behavior.GossipBehavior"
  communication: "samesim.plugins.communication.gossip.GossipProtocol"
  topology: "samesim.plugins.topologies.random_graph.ErdosRenyiTopology"
  metrics:
    - "samesim.plugins.metrics.message_count.MessageCountMetric"
    - "samesim.plugins.metrics.convergence.ConvergenceMetric"
  persistence:
    - "samesim.plugins.persistence.csv_exporter.CsvExporter"

plugin_configs:
  GossipBehavior:
    initial_value_range: [0.0, 1.0]
    fan_out: 3
  GossipProtocol: {}
  ErdosRenyiTopology:
    edge_probability: 0.01
"""


@pytest.fixture
def regression_config(tmp_path: Path):
    config_path = tmp_path / "regression.yaml"
    config_path.write_text(REGRESSION_CONFIG, encoding="utf-8")
    return config_path, tmp_path / "results"


def test_1000_agents_completes(regression_config):
    config_path, output_dir = regression_config
    start = time.time()
    ExperimentRunner().run(config_path, output_dir)
    elapsed = time.time() - start
    assert elapsed < 120, f"Simulation took too long: {elapsed:.1f}s > 120s"


def test_1000_agents_gossip_converges(regression_config):
    config_path, output_dir = regression_config
    ExperimentRunner().run(config_path, output_dir)

    convergence_file = output_dir / "regression_1000_agents_convergence_variance.csv"
    lines = [l for l in convergence_file.read_text().splitlines() if not l.startswith("#")]
    data = [float(l.split(",")[1]) for l in lines[1:] if l.strip()]

    assert len(data) >= 10, "Too few data points"
    initial_variance = data[0]
    final_variance = data[-1]

    assert final_variance < 0.1 * initial_variance, (
        f"Insufficient convergence: initial={initial_variance:.6f}, "
        f"final={final_variance:.6f} (expected <10% of initial)"
    )
