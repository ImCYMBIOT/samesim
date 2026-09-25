"""
Synchronous vs. asynchronous gossip: does Simul8 reproduce the O(n^2) ring?

Runs, on the same graphs and seeds:

    sync   GossipBehavior -- every agent pushes to fan_out=2 neighbors every
           tick and averages what it receives (synchronous activation)
    async  AsyncGossipBehavior -- Boyd et al.'s randomized pairwise
           averaging on per-agent Poisson clocks (event activation),
           latency 0.01 so exchanges rarely overlap

Communication budget is matched: sync sends 2 messages per agent per tick;
async at clock_rate 1 makes one pull/push exchange (2 messages) per agent
per time unit.

For each run records the time at which population variance first falls to
1e-2 and to 1e-4 of its initial value. Ticks (tick_interval=1) are the
sampling clock, so times have a resolution of 1.

    python run_async_sweep.py              # full sweep, ~15-20 min
    python run_async_sweep.py --quick      # smoke run

Output: async_results.json next to this script.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

import yaml

# Repo root, derived from this file so the script runs from any checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from simul8.app.experiment_runner import ExperimentRunner  # noqa: E402

HERE = Path(__file__).resolve().parent
# Intermediate configs and per-run CSVs. Kept out of the repo by default
# (see .gitignore); override with SIMUL8_EXPERIMENT_WORK to relocate.
SCRATCH = Path(os.environ.get("SIMUL8_EXPERIMENT_WORK", HERE / "_work"))
THRESHOLDS = (1e-2, 1e-4)


def horizon(protocol: str, topology: str, n: int) -> float:
    """Run length with generous headroom over pilot measurements."""
    if topology == "ring":
        # Both protocols get the same n^2-scaled window. (An earlier version
        # gave sync only 20n, assuming the O(n) seen at a 1% threshold;
        # at 1e-4 sync is ~n^2 too, and n=160 never finished.)
        return float(max(200, int(0.5 * n * n)))
    return 300.0


def run_one(protocol: str, topology: str, n: int, seed: int) -> dict:
    name = f"{protocol}_{topology}_n{n}_s{seed}"
    topo = ({"topology": "simul8.plugins.topologies.ring.RingTopology"}, {})
    if topology == "erdos_renyi":
        topo = ({"topology": "simul8.plugins.topologies.random_graph.ErdosRenyiTopology"},
                {"ErdosRenyiTopology": {"edge_probability": 8.0 / (n - 1)}})
    if protocol == "sync":
        plugins = {"behavior": "simul8.plugins.behaviors.gossip_behavior.GossipBehavior",
                   "communication": "simul8.plugins.communication.gossip.GossipProtocol"}
        pconf = {"GossipBehavior": {"fan_out": 2, "initial_value_range": [0.0, 1.0]}}
        activation = "synchronous"
    else:
        plugins = {"behavior": "simul8.plugins.behaviors.async_gossip.AsyncGossipBehavior",
                   "communication": "simul8.plugins.communication.latency.LatencyProtocol"}
        pconf = {"AsyncGossipBehavior": {"clock_rate": 1.0, "initial_value_range": [0.0, 1.0]},
                 "LatencyProtocol": {"distribution": "constant", "delay": 0.01}}
        activation = "event"
    max_t = horizon(protocol, topology, n)
    cfg = {
        "schema_version": "1.0",
        "experiment": {"name": name, "seed": seed},
        "simulation": {"num_agents": n, "max_virtual_time": max_t,
                       "tick_interval": 1.0, "activation": activation},
        "plugins": {**plugins, **topo[0],
                    "metrics": ["simul8.plugins.metrics.convergence.ConvergenceMetric"],
                    "persistence": ["simul8.plugins.persistence.csv_exporter.CsvExporter"]},
        "plugin_configs": {**pconf, **topo[1]},
    }
    (SCRATCH / "configs").mkdir(parents=True, exist_ok=True)
    path = SCRATCH / "configs" / f"{name}.yaml"
    path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    out = SCRATCH / "results" / name
    t0 = time.perf_counter()
    ExperimentRunner().run(path, output_dir=out)
    wall = time.perf_counter() - t0

    with open(out / f"{name}_convergence_variance.csv", newline="") as f:
        rows = [(float(r["virtual_time"]), float(r["value"]))
                for r in csv.DictReader(l for l in f if not l.startswith("#"))]
    v0 = rows[0][1]
    reached = {f"t_{th:g}": next((t for t, v in rows if v <= th * v0), None) for th in THRESHOLDS}
    return {"protocol": protocol, "topology": topology, "n": n, "seed": seed,
            "max_virtual_time": max_t, "wall_seconds": wall, **reached}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    seeds = [1, 2] if args.quick else [1, 2, 3, 4, 5]
    grid = {
        "ring": [10, 20, 40] if args.quick else [10, 20, 40, 80, 160],
        "erdos_renyi": [50, 100] if args.quick else [50, 100, 200, 400, 800],
    }
    # Resume: keep runs already saved, so an interrupted sweep continues
    # where it stopped instead of redoing hours of ring runs.
    out_json = HERE / "async_results.json"
    results = json.loads(out_json.read_text()) if out_json.exists() and not args.quick else []
    done = {(r["protocol"], r["topology"], r["n"], r["seed"]) for r in results}
    for topology, ns in grid.items():
        for protocol in ("sync", "async"):
            for n in ns:
                for seed in seeds:
                    if (protocol, topology, n, seed) in done:
                        continue
                    r = run_one(protocol, topology, n, seed)
                    results.append(r)
                    print(f"{protocol:5} {topology:11} n={n:<4} seed={seed}  "
                          f"t(1e-2)={r['t_0.01']}  t(1e-4)={r['t_0.0001']}  "
                          f"({r['wall_seconds']:.1f}s)", flush=True)
                    out_json.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {out_json}")


if __name__ == "__main__":
    main()
