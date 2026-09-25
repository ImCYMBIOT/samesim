"""Raft leader election through the real engine: liveness and Election Safety."""
from __future__ import annotations

import csv
from pathlib import Path

import pytest
import yaml

from simul8.app.experiment_runner import ExperimentRunner


def _run(tmp_path: Path, *, seed: int, n: int = 5, max_time: float = 3000.0,
         timeouts=(150.0, 300.0), protocol_cfg=None) -> list[dict]:
    cfg = {
        "schema_version": "1.0",
        "experiment": {"name": "raft", "seed": seed},
        "simulation": {"num_agents": n, "max_virtual_time": max_time,
                       "tick_interval": 10.0, "activation": "event"},
        "plugins": {
            "behavior": "simul8.plugins.behaviors.raft_election.RaftElectionBehavior",
            "communication": "simul8.plugins.communication.latency.LatencyProtocol",
            "topology": "simul8.plugins.topologies.random_graph.ErdosRenyiTopology",
            "metrics": ["simul8.plugins.metrics.raft_metrics.RaftElectionMetric",
                        "simul8.plugins.metrics.state_trace.StateTraceMetric"],
            "persistence": ["simul8.plugins.persistence.csv_exporter.CsvExporter"],
        },
        "plugin_configs": {
            "RaftElectionBehavior": {"election_timeout_min": timeouts[0],
                                     "election_timeout_max": timeouts[1]},
            "LatencyProtocol": protocol_cfg or {"distribution": "uniform", "low": 5, "high": 15},
            "ErdosRenyiTopology": {"edge_probability": 1.0},
        },
    }
    path = tmp_path / f"raft_{seed}.yaml"
    path.write_text(yaml.safe_dump(cfg))
    out = tmp_path / f"out_{seed}"
    ExperimentRunner().run(path, output_dir=out)
    with open(out / "raft_raft_elections.csv", newline="") as f:
        return list(csv.DictReader(l for l in f if not l.startswith("#")))


def test_a_leader_is_elected_quickly_and_stays(tmp_path):
    rows = _run(tmp_path, seed=1)
    elected = [r for r in rows if r["event"] == "elected"]
    assert elected, "no leader elected in 3 seconds"
    assert float(elected[0]["virtual_time"]) < 1000
    assert len(elected) == 1, "with a healthy leader there should be no further elections"


@pytest.mark.parametrize("scenario", [
    {"protocol_cfg": {"distribution": "exponential", "mean": 20.0, "loss_probability": 0.2}},
    {"protocol_cfg": {"distribution": "lognormal", "mu": 3.0, "sigma": 1.0, "loss_probability": 0.3}},
    # Randomization range comparable to the 5-15 latency: frequent split
    # votes that still resolve -- many terms per run.
    {"timeouts": (150.0, 160.0)},
    {"n": 7, "protocol_cfg": {"distribution": "uniform", "low": 1, "high": 120, "loss_probability": 0.1}},
], ids=["lossy-exponential", "heavy-tail-lossy", "split-votes", "seven-slow-reordering"])
def test_election_safety_holds_under_adversity(tmp_path, scenario):
    """Raft's Election Safety: at most one leader per term, whatever the
    network does. Latency spread beyond the heartbeat interval, heavy loss
    and near-equal timeouts force many terms and re-elections; across 25
    seeds each, no term may ever have two leaders."""
    terms_seen = 0
    for seed in range(25):
        rows = _run(tmp_path, seed=seed, **scenario)
        assert not [r for r in rows if r["event"] == "SAFETY_VIOLATION"], (seed, rows)
        terms_seen += len({r["value"] for r in rows})
    assert terms_seen >= 25, "the scenario never elected anyone -- vacuous"


def test_randomization_below_network_delay_never_elects(tmp_path):
    """The paper's motivating failure (Ongaro & Ousterhout, §9.3). With
    timeouts in [150, 151] and messages taking 5-15, every agent times out
    within ~1 of the others -- each becomes a candidate and votes for itself
    before any RequestVote arrives, so no vote is ever granted. Each round
    redraws the timeouts, but the spread grows only as a random walk
    (~1.3 after 20 rounds), never reaching the 5 minimum latency. Raft
    depends on the randomization range exceeding the broadcast time; the
    simulator must reproduce that dependence, not paper over it."""
    for seed in range(5):
        rows = _run(tmp_path, seed=seed, timeouts=(150.0, 151.0))
        assert rows == [], f"seed {seed} elected a leader: {rows}"
