"""
Gossip convergence under churn -- the Phase 3 validation target.

Push gossip (GossipBehavior, fan-out 2) on an Erdos-Renyi graph (n=200,
average degree 8) while RandomChurn crashes and restarts agents. Two knobs:

    down_fraction f   long-run fraction of agents down at any moment,
                      f = failure_rate / (failure_rate + recovery_rate)
    downtime D        mean time an agent stays down (recovery_rate = 1/D)

A crashed agent keeps its value and rejoins with it, so churn does two
things: it loses the messages sent to crashed agents, and it reinjects
stale values when they come back. ConsensusMetric separates the effects:

    value          variance among RUNNING agents
    all_variance   variance among ALL agents, crashed ones at their frozen value
    drift          consensus mean minus the true initial mean

Recorded per run, relative to the initial variance v0:
    t_running_{1e-2,1e-4}  first tick running-agent variance <= threshold * v0
    t_all_{1e-2,1e-4}      same for all-agent variance
    settled_all_1e-4       tick after which all-agent variance stays <= 1e-4 v0
                           (None if it never settles within the horizon)
    drift                  final drift / sqrt(v0)
    lost                   messages lost to crashed agents
    down_fraction_observed mean fraction of agents down over the run

    python run_churn_sweep.py            # full sweep, resumable (~10 min)
    python run_churn_sweep.py --quick    # smoke run -> churn_results_quick.json

Output: churn_results.json next to this script.
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

N_AGENTS = 200
AVG_DEGREE = 8.0
FAN_OUT = 2
HORIZON = 400
THRESHOLDS = (1e-2, 1e-4)


def _rows(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(l for l in f if not l.startswith("#")))


def run_one(f: float, downtime: float, seed: int) -> dict:
    name = f"churn_f{f:g}_D{downtime:g}_s{seed}"
    plugins = {
        "behavior": "simul8.plugins.behaviors.gossip_behavior.GossipBehavior",
        "communication": "simul8.plugins.communication.gossip.GossipProtocol",
        "topology": "simul8.plugins.topologies.random_graph.ErdosRenyiTopology",
        "metrics": ["simul8.plugins.metrics.consensus.ConsensusMetric",
                    "simul8.plugins.metrics.churn_metrics.ChurnMetric"],
        "persistence": ["simul8.plugins.persistence.csv_exporter.CsvExporter"],
    }
    plugin_configs = {
        "GossipBehavior": {"fan_out": FAN_OUT, "initial_value_range": [0.0, 1.0]},
        "ErdosRenyiTopology": {"edge_probability": AVG_DEGREE / (N_AGENTS - 1)},
    }
    if f > 0:
        mu = 1.0 / downtime
        plugins["dynamics"] = "simul8.plugins.dynamics.random_churn.RandomChurn"
        plugin_configs["RandomChurn"] = {"failure_rate": f * mu / (1.0 - f), "recovery_rate": mu}
    cfg = {
        "schema_version": "1.0",
        "experiment": {"name": name, "seed": seed},
        "simulation": {"num_agents": N_AGENTS, "max_virtual_time": HORIZON, "tick_interval": 1},
        "plugins": plugins,
        "plugin_configs": plugin_configs,
    }
    (SCRATCH / "configs").mkdir(parents=True, exist_ok=True)
    cfg_path = SCRATCH / "configs" / f"{name}.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    out = SCRATCH / "results" / name
    ExperimentRunner().run(cfg_path, output_dir=out)

    cons = _rows(out / f"{name}_consensus.csv")
    times = [float(r["virtual_time"]) for r in cons]
    running = [float(r["value"]) for r in cons]
    everyone = [float(r["all_variance"]) for r in cons]
    v0 = everyone[0]

    def first(series, thr):
        return next((t for t, v in zip(times, series) if v <= thr * v0), None)

    def settled(series, thr):
        above = [t for t, v in zip(times, series) if v > thr * v0]
        if not above:
            return times[0]
        return None if above[-1] == times[-1] else above[-1] + 1

    result = {"down_fraction": f, "downtime": downtime, "seed": seed,
              "drift": float(cons[-1]["drift"]) / v0 ** 0.5}
    for thr in THRESHOLDS:
        result[f"t_running_{thr:g}"] = first(running, thr)
        result[f"t_all_{thr:g}"] = first(everyone, thr)
    result["settled_all_1e-4"] = settled(everyone, 1e-4)

    churn = _rows(out / f"{name}_churn.csv") if f > 0 else []
    result["lost"] = int(churn[-1]["lost"]) if churn else 0
    result["down_fraction_observed"] = (
        sum(int(r["failed"]) for r in churn) / (len(churn) * N_AGENTS) if churn else 0.0
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()

    fractions = [0.0, 0.1, 0.3] if args.quick else [0.0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5]
    downtimes = [5.0] if args.quick else [5.0, 50.0]
    seeds = [1, 2] if args.quick else list(range(1, 11))
    out_json = HERE / ("churn_results_quick.json" if args.quick else "churn_results.json")

    # Resumable: keep finished runs, skip them on restart.
    done = json.loads(out_json.read_text()) if out_json.exists() else []
    have = {(r["down_fraction"], r["downtime"], r["seed"]) for r in done}
    for downtime in downtimes:
        for f in fractions:
            for seed in seeds:
                # No churn: one baseline, shared by every downtime.
                d = downtimes[0] if f == 0 else downtime
                if (f, d, seed) in have:
                    continue
                r = run_one(f, d, seed)
                done.append(r)
                have.add((f, d, seed))
                out_json.write_text(json.dumps(done, indent=2))
                print(f"f={f:<5} D={d:<4} seed={seed:<2} t_running(1e-4)={r['t_running_0.0001']} "
                      f"t_all(1e-4)={r['t_all_0.0001']} settled={r['settled_all_1e-4']} "
                      f"drift={r['drift']:+.3f} lost={r['lost']}", flush=True)
    print(f"\nWrote {out_json}")


if __name__ == "__main__":
    main()
