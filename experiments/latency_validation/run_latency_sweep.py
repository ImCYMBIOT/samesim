"""
Gossip convergence vs. message latency -- the first result that needs Phase 1.

Sweeps LatencyProtocol's mean delay for push-gossip on a fixed Erdos-Renyi
graph, for two delay shapes with the same mean:

    constant     every message takes exactly `mean` time units
    exponential  delays drawn from Exp(mean) -- same mean, heavy spread

and records ticks until population variance falls to 1% of its initial
value (the same convergence criterion as gossip_topology_validation/).

    python run_latency_sweep.py            # full sweep, 20 seeds (~20 min)
    python run_latency_sweep.py --quick    # smoke run

Output: latency_results.json next to this script.
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
from samesim.app.experiment_runner import ExperimentRunner  # noqa: E402

HERE = Path(__file__).resolve().parent
# Intermediate configs and per-run CSVs. Kept out of the repo by default
# (see .gitignore); override with SAMESIM_EXPERIMENT_WORK to relocate.
SCRATCH = Path(os.environ.get("SAMESIM_EXPERIMENT_WORK", HERE / "_work"))

N_AGENTS = 200
AVG_DEGREE = 8.0
FAN_OUT = 2
MAX_TIME = 600
THRESHOLD = 0.01


def run_one(shape: str, mean: float, seed: int) -> dict:
    name = f"lat_{shape}_m{mean:g}_s{seed}"
    protocol_cfg = (
        {"distribution": "constant", "delay": mean}
        if shape == "constant"
        else {"distribution": "exponential", "mean": mean}
    )
    cfg = {
        "schema_version": "1.0",
        "experiment": {"name": name, "seed": seed},
        "simulation": {"num_agents": N_AGENTS, "max_virtual_time": MAX_TIME, "tick_interval": 1},
        "plugins": {
            "behavior": "samesim.plugins.behaviors.gossip_behavior.GossipBehavior",
            "communication": "samesim.plugins.communication.latency.LatencyProtocol",
            "topology": "samesim.plugins.topologies.random_graph.ErdosRenyiTopology",
            "metrics": ["samesim.plugins.metrics.convergence.ConvergenceMetric"],
            "persistence": ["samesim.plugins.persistence.csv_exporter.CsvExporter"],
        },
        "plugin_configs": {
            "GossipBehavior": {"fan_out": FAN_OUT, "initial_value_range": [0.0, 1.0]},
            "LatencyProtocol": protocol_cfg,
            "ErdosRenyiTopology": {"edge_probability": AVG_DEGREE / (N_AGENTS - 1)},
        },
    }
    (SCRATCH / "configs").mkdir(parents=True, exist_ok=True)
    cfg_path = SCRATCH / "configs" / f"{name}.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    out = SCRATCH / "results" / name
    ExperimentRunner().run(cfg_path, output_dir=out)

    with open(out / f"{name}_convergence_variance.csv", newline="") as f:
        rows = list(csv.DictReader(l for l in f if not l.startswith("#")))
    series = [(float(r["virtual_time"]), float(r["value"])) for r in rows]
    v0 = series[0][1]
    converged = next((t for t, v in series if v <= THRESHOLD * v0), None)
    return {"shape": shape, "mean_delay": mean, "seed": seed, "converged_tick": converged}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()

    means = [1, 2, 4] if args.quick else [1, 2, 3, 4, 6, 8, 12, 16]
    seeds = [1, 2] if args.quick else list(range(1, 21))
    results = []
    for shape in ("constant", "exponential"):
        for mean in means:
            for seed in seeds:
                r = run_one(shape, float(mean), seed)
                results.append(r)
                print(f"{shape:12} mean={mean:<3} seed={seed}  converged at tick {r['converged_tick']}",
                      flush=True)

    out_json = HERE / ("latency_results_quick.json" if args.quick else "latency_results.json")
    out_json.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {out_json}")


if __name__ == "__main__":
    main()
