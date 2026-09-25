"""
Raft recovery after a leader crash -- Ongaro & Ousterhout (2014), Figure 16,
in its actual setting.

Each trial starts a 5-node cluster in steady state (initial_leader: agent 0
leads term 1), crashes whoever is leader at t = 1000 ms + a random offset
within one heartbeat interval (so the crash lands at a random point of the
heartbeat cycle, as in the paper), and measures the time until a new leader
is elected: the cluster's downtime.

Unlike the cold-start study (run_raft_sweep.py), followers' timers here were
last reset by heartbeats that arrived 5-15 ms apart, so they are already
staggered by network jitter when the leader disappears.

Same timeout ranges, network (uniform 5-15 ms) and heartbeat rule (a third
of the minimum timeout) as the cold-start sweep.

    python run_raft_crash_sweep.py            # 500 trials per range (~5 min)
    python run_raft_crash_sweep.py --quick    # 40 trials per range

Output: raft_crash_results.json next to this script.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
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
CRASH_AT = 1000.0
WINDOW = 5000.0


def run_trial(lo: float, hi: float, seed: int) -> dict:
    hb = lo / 3
    crash = CRASH_AT + random.Random(seed).uniform(0.0, hb)
    name = f"crash_{lo:g}_{hi:g}_s{seed}"
    cfg = {
        "schema_version": "1.0",
        "experiment": {"name": name, "seed": seed},
        "simulation": {"num_agents": 5, "max_virtual_time": crash + WINDOW,
                       "tick_interval": 100.0, "activation": "event"},
        "plugins": {
            "behavior": "simul8.plugins.behaviors.raft_election.RaftElectionBehavior",
            "communication": "simul8.plugins.communication.latency.LatencyProtocol",
            "topology": "simul8.plugins.topologies.random_graph.ErdosRenyiTopology",
            "dynamics": "simul8.plugins.dynamics.scheduled.ScheduledChurn",
            "metrics": ["simul8.plugins.metrics.raft_metrics.RaftElectionMetric"],
            "persistence": ["simul8.plugins.persistence.csv_exporter.CsvExporter"],
        },
        "plugin_configs": {
            "RaftElectionBehavior": {"election_timeout_min": lo, "election_timeout_max": hi,
                                     "heartbeat_interval": hb, "initial_leader": 0},
            "LatencyProtocol": {"distribution": "uniform", "low": 5, "high": 15},
            "ErdosRenyiTopology": {"edge_probability": 1.0},
            "ScheduledChurn": {"events": [{"at": crash, "fail": {"where": {"role": "leader"}}}]},
        },
    }
    (SCRATCH / "configs").mkdir(parents=True, exist_ok=True)
    path = SCRATCH / "configs" / f"{name}.yaml"
    path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    out = SCRATCH / "results" / name
    ExperimentRunner().run(path, output_dir=out)
    with open(out / f"{name}_raft_elections.csv", newline="") as f:
        rows = list(csv.DictReader(l for l in f if not l.startswith("#")))
    before = [r for r in rows if r["event"] == "elected" and float(r["virtual_time"]) < crash]
    after = [r for r in rows if r["event"] == "elected" and float(r["virtual_time"]) >= crash]
    return {
        "lo": lo, "hi": hi, "seed": seed, "crash_ms": crash,
        # With a steady-state start, any election before the crash means the
        # cluster was already unstable (timeouts too close to the network delay).
        "elections_before_crash": len(before),
        "downtime_ms": float(after[0]["virtual_time"]) - crash if after else None,
        "new_term": int(float(after[0]["value"])) if after else None,
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
            batch = [dict(run_trial(lo, hi, s), sweep=sweep) for s in range(trials)]
            results.extend(batch)
            d = sorted(r["downtime_ms"] for r in batch if r["downtime_ms"] is not None)
            med = f"{d[len(d) // 2]:.0f}" if d else "-"
            print(f"{sweep:10} {lo:g}-{hi:g} ms: recovered {len(d)}/{trials}, median downtime {med} ms, "
                  f"violations {sum(r['safety_violations'] for r in batch)}", flush=True)
            (HERE / "raft_crash_results.json").write_text(json.dumps(results, indent=2))
    print(f"\nWrote {HERE / 'raft_crash_results.json'}")


if __name__ == "__main__":
    main()
