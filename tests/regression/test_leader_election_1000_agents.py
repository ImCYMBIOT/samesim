"""
Regression test: 1,000-agent leader election experiment.

Verifies that:
    1. The simulation completes in reasonable time (< 120s on a laptop)
    2. Consensus is reached: nearly all agents converge on the true
       maximum candidate ID as the elected leader
    3. Same seed produces bit-identical results (reproducibility)

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
  name: "regression_leader_1000_agents"
  seed: 42

simulation:
  num_agents: 1000
  max_virtual_time: 30
  tick_interval: 1

plugins:
  behavior: "samesim.plugins.behaviors.leader_election.LeaderElectionBehavior"
  communication: "samesim.plugins.communication.gossip.GossipProtocol"
  topology: "samesim.plugins.topologies.random_graph.ErdosRenyiTopology"
  metrics:
    - "samesim.plugins.metrics.leader_metrics.LeaderConsensusMetric"
  persistence:
    - "samesim.plugins.persistence.csv_exporter.CsvExporter"

plugin_configs:
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


def test_1000_agents_reaches_consensus(regression_config):
    config_path, output_dir = regression_config
    ExperimentRunner().run(config_path, output_dir)

    consensus_file = output_dir / "regression_leader_1000_agents_leader_consensus_fraction.csv"
    lines = [l for l in consensus_file.read_text().splitlines() if not l.startswith("#")]
    data = [float(l.split(",")[1]) for l in lines[1:] if l.strip()]

    assert len(data) >= 10, "Too few data points"
    assert data[-1] >= 0.99, (
        f"Leader election did not reach consensus: final agreement fraction "
        f"= {data[-1]:.4f} (expected >= 0.99)"
    )


def test_1000_agents_reproducible(regression_config, tmp_path):
    """Same seed produces identical consensus series."""
    config_path, output_dir1 = regression_config
    output_dir2 = tmp_path / "results2"

    ExperimentRunner().run(config_path, output_dir1)
    ExperimentRunner().run(config_path, output_dir2)

    name = "regression_leader_1000_agents_leader_consensus_fraction.csv"
    f1 = (output_dir1 / name).read_text()
    f2 = (output_dir2 / name).read_text()
    assert f1 == f2, "Same seed produced different results — reproducibility broken!"
