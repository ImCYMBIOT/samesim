"""
Raft election time vs. election-timeout range -- after Ongaro & Ousterhout
(2014), Figure 16.

The paper measured, on a 5-server cluster with a broadcast time of roughly
15 ms, how long it takes to elect a leader for different election-timeout
ranges. Two sweeps:

    randomness  timeouts 150-150, 150-151, 150-155, 150-175, 150-200, 150-300
    scale       timeouts 12-24, 25-50, 50-100, 100-200, 150-300

The paper times recovery after a leader crash; this study times election
from a cold start, where every node's timer starts at t=0. Both begin with
every follower's timer armed at nearly the same instant, which is the
situation the randomization is there to resolve.

Network: LatencyProtocol, uniform 5-15 ms per message (a request/response
exchange takes 10-30 ms, bracketing the paper's ~15 ms broadcast time).
Heartbeat interval: one third of the minimum timeout.

For each trial records the time and term of the first election, and how
many further elections followed within the horizon (unnecessary leader
changes, which too-short timeouts cause). Also counts Election Safety
violations, which must be zero.

    python run_raft_sweep.py             # full, 500 trials per range (~10 min)
    python run_raft_sweep.py --quick     # 40 trials per range

Output: raft_results.json next to this script.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import yaml

# Repo root, derived from this file so the script runs from any checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from simul8.app.experiment_runner import ExperimentRunner  # noqa: E402

HERE = Path(__file__).resolve().parent
# Intermediate configs and per-run CSVs. Kept out of the repo by default
# (see .gitignore); override with SIMUL8_EXPERIMENT_WORK to relocate.
SCRATCH = Path(os.environ.get("SIMUL8_EXPERIMENT_WORK", HERE / "_work"))

RANGES = {
    "randomness": [(150, 150), (150, 151), (150, 155), (150, 175), (150, 200), (150, 300)],
    "scale": [(12, 24), (25, 50), (50, 100), (100, 200), (150, 300)],
}
HORIZON_MS = 5000.0


def run_trial(lo: float, hi: float, seed: int) -> dict:
    name = f"raft_{lo:g}_{hi:g}_s{seed}"
    cfg = {
        "schema_version": "1.0",
        "experiment": {"name": name, "seed": seed},
        "simulation": {"num_agents": 5, "max_virtual_time": HORIZON_MS,
                       "tick_interval": 100.0, "activation": "event"},
        "plugins": {
            "behavior": "simul8.plugins.behaviors.raft_election.RaftElectionBehavior",
            "communication": "simul8.plugins.communication.latency.LatencyProtocol",
            "topology": "simul8.plugins.topologies.random_graph.ErdosRenyiTopology",
            "metrics": ["simul8.plugins.metrics.raft_metrics.RaftElectionMetric"],
            "persistence": ["simul8.plugins.persistence.csv_exporter.CsvExporter"],
        },
        "plugin_configs": {
            "RaftElectionBehavior": {"election_timeout_min": lo, "election_timeout_max": hi,
                                     "heartbeat_interval": lo / 3},
            "LatencyProtocol": {"distribution": "uniform", "low": 5, "high": 15},
            "ErdosRenyiTopology": {"edge_probability": 1.0},
        },
    }
    (SCRATCH / "configs").mkdir(parents=True, exist_ok=True)
    path = SCRATCH / "configs" / f"{name}.yaml"
    path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    out = SCRATCH / "results" / name
    ExperimentRunner().run(path, output_dir=out)
    with open(out / f"{name}_raft_elections.csv", newline="") as f:
        rows = list(csv.DictReader(l for l in f if not l.startswith("#")))
    elected = [r for r in rows if r["event"] == "elected"]
    return {
        "lo": lo, "hi": hi, "seed": seed,
        "first_election_ms": float(elected[0]["virtual_time"]) if elected else None,
        "first_term": int(float(elected[0]["value"])) if elected else None,
        "later_elections": max(0, len(elected) - 1),
        "safety_violations": sum(1 for r in rows if r["event"] == "SAFETY_VIOLATION"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    trials = 40 if args.quick else 500
    results = []
    for sweep, ranges in RANGES.items():
        for lo, hi in ranges:
            batch = [dict(run_trial(lo, hi, seed), sweep=sweep) for seed in range(trials)]
            results.extend(batch)
            times = sorted(r["first_election_ms"] for r in batch if r["first_election_ms"] is not None)
            med = f"{times[len(times) // 2]:.0f}" if times else "-"
            print(f"{sweep:10} {lo:g}-{hi:g} ms: elected {len(times)}/{trials}, median {med} ms, "
                  f"violations {sum(r['safety_violations'] for r in batch)}", flush=True)
            (HERE / "raft_results.json").write_text(json.dumps(results, indent=2))
    print(f"\nWrote {HERE / 'raft_results.json'}")


if __name__ == "__main__":
    main()
