"""
Integration test: full gossip experiment end-to-end.

Tests that a 50-agent gossip simulation runs to completion,
produces convergence metrics, and that convergence actually occurs
(variance decreases over time with gossip averaging).

Uses the smallest meaningful scale to keep CI fast (50 agents, 50 ticks).
The 1,000-agent regression test lives in tests/regression/.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from samesim.app.experiment_runner import ExperimentRunner


INTEGRATION_CONFIG = """\
schema_version: "1.0"

experiment:
  name: "integration_test"
  seed: 42

simulation:
  num_agents: 50
  max_virtual_time: 50
  tick_interval: 1

plugins:
  behavior: "samesim.plugins.behaviors.gossip_behavior.GossipBehavior"
  communication: "samesim.plugins.communication.gossip.GossipProtocol"
  topology: "samesim.plugins.topologies.ring.RingTopology"
  metrics:
    - "samesim.plugins.metrics.message_count.MessageCountMetric"
    - "samesim.plugins.metrics.convergence.ConvergenceMetric"
  persistence:
    - "samesim.plugins.persistence.csv_exporter.CsvExporter"

plugin_configs:
  GossipBehavior:
    initial_value_range: [0.0, 1.0]
    fan_out: 2
  GossipProtocol: {}
  RingTopology: {}
"""


@pytest.fixture
def tmp_experiment(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(INTEGRATION_CONFIG, encoding="utf-8")
    output_dir = tmp_path / "results"
    return config_path, output_dir


def test_experiment_runs_to_completion(tmp_experiment):
    config_path, output_dir = tmp_experiment
    runner = ExperimentRunner()
    runner.run(config_path, output_dir)  # should not raise


def test_experiment_writes_csv_files(tmp_experiment):
    config_path, output_dir = tmp_experiment
    ExperimentRunner().run(config_path, output_dir)

    csv_files = list(output_dir.glob("*.csv"))
    assert len(csv_files) == 2, f"Expected 2 CSV files, got: {[f.name for f in csv_files]}"


def test_convergence_metric_written(tmp_experiment):
    config_path, output_dir = tmp_experiment
    ExperimentRunner().run(config_path, output_dir)

    convergence_file = output_dir / "integration_test_convergence_variance.csv"
    assert convergence_file.exists(), "Convergence metric CSV not written"

    lines = [l for l in convergence_file.read_text().splitlines() if not l.startswith("#")]
    # header + at least 1 data row
    assert len(lines) >= 2, "Convergence CSV has no data rows"


def test_message_count_increases(tmp_experiment):
    config_path, output_dir = tmp_experiment
    ExperimentRunner().run(config_path, output_dir)

    msg_file = output_dir / "integration_test_message_count.csv"
    lines = [l for l in msg_file.read_text().splitlines() if not l.startswith("#")]
    data = [float(l.split(",")[1]) for l in lines[1:] if l.strip()]

    assert len(data) > 0
    assert data[-1] > 0, "No messages were delivered"
    # Message count should be monotonically non-decreasing (cumulative)
    for i in range(1, len(data)):
        assert data[i] >= data[i - 1]


def test_reproducibility_same_seed(tmp_experiment, tmp_path):
    """Same seed produces identical convergence series."""
    config_path, output_dir1 = tmp_experiment
    output_dir2 = tmp_path / "results2"

    ExperimentRunner().run(config_path, output_dir1)
    ExperimentRunner().run(config_path, output_dir2)

    f1 = (output_dir1 / "integration_test_convergence_variance.csv").read_text()
    f2 = (output_dir2 / "integration_test_convergence_variance.csv").read_text()
    assert f1 == f2, "Same seed produced different results — reproducibility broken!"


def test_gossip_converges(tmp_experiment):
    """Variance at the end of the simulation is less than at the start."""
    config_path, output_dir = tmp_experiment
    ExperimentRunner().run(config_path, output_dir)

    convergence_file = output_dir / "integration_test_convergence_variance.csv"
    lines = [l for l in convergence_file.read_text().splitlines() if not l.startswith("#")]
    data = [float(l.split(",")[1]) for l in lines[1:] if l.strip()]

    assert len(data) >= 2
    # After 50 ticks, variance should have decreased
    assert data[-1] < data[0], (
        f"Gossip did not converge: initial variance={data[0]:.4f}, "
        f"final variance={data[-1]:.4f}"
    )
