"""
Regression test: 1,000-agent SIR epidemic experiment.

Verifies that:
    1. The simulation completes in reasonable time (< 120s on a laptop)
    2. An outbreak actually occurs (infected count rises above the seed count)
    3. The epidemic burns out (infected count returns to 0 by the end,
       with population conserved across S + I + R)
    4. Same seed produces bit-identical results (reproducibility)

This test is marked @pytest.mark.slow and is excluded from the default
test suite. Run with: pytest -m slow
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from simul8.app.experiment_runner import ExperimentRunner

pytestmark = pytest.mark.slow


REGRESSION_CONFIG = """\
schema_version: "1.0"

experiment:
  name: "regression_sir_1000_agents"
  seed: 42

simulation:
  num_agents: 1000
  max_virtual_time: 150
  tick_interval: 1

plugins:
  behavior: "simul8.plugins.behaviors.sir_behavior.SirEpidemicBehavior"
  communication: "simul8.plugins.communication.broadcast.BroadcastProtocol"
  topology: "simul8.plugins.topologies.watts_strogatz.WattsStrogatzTopology"
  metrics:
    - "simul8.plugins.metrics.sir_metrics.SirSusceptibleMetric"
    - "simul8.plugins.metrics.sir_metrics.SirInfectedMetric"
    - "simul8.plugins.metrics.sir_metrics.SirRecoveredMetric"
  persistence:
    - "simul8.plugins.persistence.csv_exporter.CsvExporter"

plugin_configs:
  SirEpidemicBehavior:
    transmission_rate: 0.25
    recovery_rate: 0.12
    initial_infected: 5
  WattsStrogatzTopology:
    k: 8
    rewire_probability: 0.15
"""


@pytest.fixture
def regression_config(tmp_path: Path):
    config_path = tmp_path / "regression.yaml"
    config_path.write_text(REGRESSION_CONFIG, encoding="utf-8")
    return config_path, tmp_path / "results"


def _read_series(output_dir: Path, name: str) -> list[float]:
    path = output_dir / f"regression_sir_1000_agents_sir_{name}.csv"
    lines = [l for l in path.read_text().splitlines() if not l.startswith("#")]
    return [float(l.split(",")[1]) for l in lines[1:] if l.strip()]


def test_1000_agents_completes(regression_config):
    config_path, output_dir = regression_config
    start = time.time()
    ExperimentRunner().run(config_path, output_dir)
    elapsed = time.time() - start
    assert elapsed < 120, f"Simulation took too long: {elapsed:.1f}s > 120s"


def test_1000_agents_outbreak_occurs_and_burns_out(regression_config):
    config_path, output_dir = regression_config
    ExperimentRunner().run(config_path, output_dir)

    susceptible = _read_series(output_dir, "susceptible")
    infected = _read_series(output_dir, "infected")
    recovered = _read_series(output_dir, "recovered")

    assert len(infected) >= 10, "Too few data points"
    assert max(infected) > 5, (
        f"No real outbreak occurred: peak infected = {max(infected)} "
        f"(expected > seed count of 5)"
    )
    assert infected[-1] == 0, (
        f"Epidemic did not burn out within the simulation window: "
        f"final infected count = {infected[-1]}"
    )
    assert recovered[-1] > 0, "No agents ever recovered"

    # Population conservation: S + I + R must equal 1000 at every sampled tick.
    for s, i, r in zip(susceptible, infected, recovered):
        assert s + i + r == 1000, f"Population not conserved: S={s} I={i} R={r}"


def test_1000_agents_reproducible(regression_config, tmp_path):
    """Same seed produces identical infection curves."""
    config_path, output_dir1 = regression_config
    output_dir2 = tmp_path / "results2"

    ExperimentRunner().run(config_path, output_dir1)
    ExperimentRunner().run(config_path, output_dir2)

    name = "regression_sir_1000_agents_sir_infected.csv"
    f1 = (output_dir1 / name).read_text()
    f2 = (output_dir2 / name).read_text()
    assert f1 == f2, "Same seed produced different results — reproducibility broken!"
