"""
Gossip convergence vs. topology validation harness.

Hypothesis (mixing-time theory): push-gossip convergence time tracks the
mixing time of a random walk on the underlying graph.
  - Erdos-Renyi at constant average degree (above connectivity threshold):
    mixing time O(log n)  -> convergence time should grow slowly with n.
  - Ring (2-regular cycle): mixing time O(n^2)
    -> convergence time should grow much faster (~quadratically) with n.

This script runs Simul8's real ExperimentRunner (the same code path the CLI
uses) across a sweep of (topology, n, seed), then measures the tick at which
population variance of agent values first drops to <=1% of its initial value.
"""
from __future__ import annotations

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
CONFIG_DIR = SCRATCH / "configs"
RESULTS_DIR = SCRATCH / "results"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

CONVERGENCE_THRESHOLD_FRACTION = 0.01  # converged when variance <= 1% of initial variance
FAN_OUT = 2
AVG_DEGREE_ER = 8.0  # held constant across n so ER graphs stay in the same "well-connected" regime


def make_config(topology_name: str, topology_class: str, topology_config: dict,
                 n: int, max_time: int, seed: int) -> tuple[str, Path]:
    name = f"gv_{topology_name}_n{n}_s{seed}"
    cfg = {
        "schema_version": "1.0",
        "experiment": {"name": name, "seed": seed},
        "simulation": {"num_agents": n, "max_virtual_time": max_time, "tick_interval": 1},
        "plugins": {
            "behavior": "simul8.plugins.behaviors.gossip_behavior.GossipBehavior",
            "communication": "simul8.plugins.communication.gossip.GossipProtocol",
            "topology": topology_class,
            "metrics": ["simul8.plugins.metrics.convergence.ConvergenceMetric"],
            "persistence": ["simul8.plugins.persistence.csv_exporter.CsvExporter"],
        },
        "plugin_configs": {
            "GossipBehavior": {"initial_value_range": [0.0, 1.0], "fan_out": FAN_OUT},
            topology_class.rsplit(".", 1)[-1]: topology_config,
        },
    }
    path = CONFIG_DIR / f"{name}.yaml"
    with open(path, "w") as f:
        yaml.dump(cfg, f)
    return name, path


def run_one(topology_name: str, topology_class: str, topology_config: dict,
            n: int, max_time: int, seed: int) -> dict:
    name, cfg_path = make_config(topology_name, topology_class, topology_config, n, max_time, seed)
    out_dir = RESULTS_DIR / name

    runner = ExperimentRunner()
    t0 = time.perf_counter()
    runner.run(cfg_path, output_dir=out_dir)
    wall = time.perf_counter() - t0

    csv_path = out_dir / f"{name}_convergence_variance.csv"
    ticks: list[float] = []
    variances: list[float] = []
    with open(csv_path) as f:
        for row in csv.reader(f):
            if not row or row[0].startswith("#") or row[0] == "virtual_time":
                continue
            ticks.append(float(row[0]))
            variances.append(float(row[1]))

    initial_var = variances[0] if variances else 0.0
    threshold = initial_var * CONVERGENCE_THRESHOLD_FRACTION
    converged_tick = None
    for t, v in zip(ticks, variances):
        if v <= threshold:
            converged_tick = t
            break

    return {
        "topology": topology_name,
        "n": n,
        "seed": seed,
        "max_virtual_time": max_time,
        "initial_variance": initial_var,
        "final_variance": variances[-1] if variances else None,
        "converged_tick": converged_tick,
        "converged": converged_tick is not None,
        "wall_seconds": wall,
    }


def er_config(n: int) -> dict:
    p = min(1.0, AVG_DEGREE_ER / max(1, n - 1))
    return {"edge_probability": p}


def ws_config(n: int) -> dict:
    # k is the fixed initial-lattice degree; rewiring doesn't change degree.
    return {"k": 8, "rewire_probability": 0.15}


def ba_config(n: int) -> dict:
    # avg degree approx 2m for large n; m=4 -> avg degree ~8, matching ER/WS.
    return {"m": 4}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["pilot", "full", "pilot_ws_ba", "full_ws_ba"], default="pilot")
    args = parser.parse_args()

    ER_NS = (50, 100, 200, 400, 800, 1600)

    if args.mode == "pilot":
        jobs = []
        for n in (20, 40, 80):
            jobs.append(("ring", "simul8.plugins.topologies.ring.RingTopology", {}, n, 6000, 1))
        for n in (50, 200, 800):
            jobs.append(("erdos_renyi", "simul8.plugins.topologies.random_graph.ErdosRenyiTopology", er_config(n), n, 200, 1))
    elif args.mode == "full":
        jobs = []
        seeds = tuple(range(1, 21))
        # Calibrated from pilot data: ring n=20/40/80/160/320 converged at
        # ticks 9/51/64/176/249 respectively -- max(300, 8n) gives ample margin.
        for n in (10, 20, 40, 80, 160, 320):
            for s in seeds:
                jobs.append(("ring", "simul8.plugins.topologies.ring.RingTopology", {}, n, max(300, 8 * n), s))
        for n in ER_NS:
            for s in seeds:
                jobs.append(("erdos_renyi", "simul8.plugins.topologies.random_graph.ErdosRenyiTopology", er_config(n), n, 200, s))
    elif args.mode == "pilot_ws_ba":
        jobs = []
        for n in (50, 800, 1600):
            jobs.append(("watts_strogatz", "simul8.plugins.topologies.watts_strogatz.WattsStrogatzTopology", ws_config(n), n, 200, 1))
            jobs.append(("barabasi_albert", "simul8.plugins.topologies.barabasi_albert.BarabasiAlbertTopology", ba_config(n), n, 200, 1))
    else:  # full_ws_ba
        jobs = []
        seeds = tuple(range(1, 21))
        for n in ER_NS:
            for s in seeds:
                jobs.append(("watts_strogatz", "simul8.plugins.topologies.watts_strogatz.WattsStrogatzTopology", ws_config(n), n, 200, s))
        for n in ER_NS:
            for s in seeds:
                jobs.append(("barabasi_albert", "simul8.plugins.topologies.barabasi_albert.BarabasiAlbertTopology", ba_config(n), n, 200, s))

    results = []
    for i, (topo_name, topo_class, topo_cfg, n, max_t, seed) in enumerate(jobs):
        print(f"[{i+1}/{len(jobs)}] {topo_name} n={n} seed={seed} max_t={max_t} ...", flush=True)
        r = run_one(topo_name, topo_class, topo_cfg, n, max_t, seed)
        results.append(r)
        print(f"    -> converged={r['converged']} at tick={r['converged_tick']} "
              f"final_var={r['final_variance']:.6g} wall={r['wall_seconds']:.2f}s", flush=True)

    out_json = HERE / f"{args.mode}_results.json"
    with open(out_json, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote {out_json}")
