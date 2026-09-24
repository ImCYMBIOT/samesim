"""
Scaling benchmark: wall-clock time, throughput, and peak memory vs. agent count.

Runs the same gossip experiment (Erdos-Renyi, average degree 8, fixed 50 ticks)
at agent counts from 100 to 100,000 through the real ExperimentRunner pipeline,
and records wall-clock time, events processed, and peak RSS memory.

Fixed tick count (not "run until converged") isolates raw engine throughput
from the convergence behavior already studied in
experiments/gossip_topology_validation/ -- this benchmark answers "how fast
does the engine run," not "how fast does gossip converge."
"""
from __future__ import annotations

import csv
import json
import logging
import resource
import os
import sys
import time
from pathlib import Path

import yaml

# Repo root, derived from this file so the script runs from any checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from simul8.app.experiment_runner import ExperimentRunner  # noqa: E402


class _EventsCapture(logging.Handler):
    """Grabs events_processed out of the engine's own completion log record."""

    def __init__(self) -> None:
        super().__init__()
        self.events_processed: int | None = None

    def emit(self, record: logging.LogRecord) -> None:
        if record.name == "simul8.core.engine" and "events_processed" in record.msg:
            # record.args = (name, events_processed, final_time)
            self.events_processed = record.args[1]

HERE = Path(__file__).resolve().parent
# Intermediate configs and per-run CSVs. Kept out of the repo by default
# (see .gitignore); override with SIMUL8_EXPERIMENT_WORK to relocate.
SCRATCH = Path(os.environ.get("SIMUL8_EXPERIMENT_WORK", HERE / "_work"))
CONFIG_DIR = SCRATCH / "configs"
RESULTS_DIR = SCRATCH / "results"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

AVG_DEGREE = 8.0
FAN_OUT = 2
MAX_VIRTUAL_TIME = 50


def er_config(n: int) -> dict:
    p = min(1.0, AVG_DEGREE / max(1, n - 1))
    return {"edge_probability": p}


def make_config(n: int, seed: int) -> tuple[str, Path]:
    name = f"scale_n{n}_s{seed}"
    cfg = {
        "schema_version": "1.0",
        "experiment": {"name": name, "seed": seed},
        "simulation": {"num_agents": n, "max_virtual_time": MAX_VIRTUAL_TIME, "tick_interval": 1},
        "plugins": {
            "behavior": "simul8.plugins.behaviors.gossip_behavior.GossipBehavior",
            "communication": "simul8.plugins.communication.gossip.GossipProtocol",
            "topology": "simul8.plugins.topologies.random_graph.ErdosRenyiTopology",
            "metrics": [
                "simul8.plugins.metrics.message_count.MessageCountMetric",
                "simul8.plugins.metrics.convergence.ConvergenceMetric",
            ],
            "persistence": ["simul8.plugins.persistence.csv_exporter.CsvExporter"],
        },
        "plugin_configs": {
            "GossipBehavior": {"initial_value_range": [0.0, 1.0], "fan_out": FAN_OUT},
            "ErdosRenyiTopology": er_config(n),
        },
    }
    path = CONFIG_DIR / f"{name}.yaml"
    with open(path, "w") as f:
        yaml.dump(cfg, f)
    return name, path


def run_one(n: int, seed: int) -> dict:
    name, cfg_path = make_config(n, seed)
    out_dir = RESULTS_DIR / name

    mem_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # KB on Linux

    capture = _EventsCapture()
    engine_logger = logging.getLogger("simul8.core.engine")
    engine_logger.addHandler(capture)
    previous_level = engine_logger.level
    engine_logger.setLevel(logging.INFO)
    try:
        t0 = time.perf_counter()
        ExperimentRunner().run(cfg_path, output_dir=out_dir)
        wall = time.perf_counter() - t0
    finally:
        engine_logger.removeHandler(capture)
        engine_logger.setLevel(previous_level)

    mem_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # peak RSS since process start

    return {
        "n": n,
        "seed": seed,
        "max_virtual_time": MAX_VIRTUAL_TIME,
        "wall_seconds": wall,
        "events_processed": capture.events_processed,
        "events_per_second": (capture.events_processed / wall) if capture.events_processed and wall > 0 else None,
        "peak_rss_kb": mem_after,
        "peak_rss_delta_kb": mem_after - mem_before,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--ns", type=str, default="100,300,1000,3000,10000,30000,100000")
    parser.add_argument("--seeds", type=str, default="1")
    args = parser.parse_args()

    ns = [int(x) for x in args.ns.split(",")]
    seeds = [int(x) for x in args.seeds.split(",")]

    results = []
    for n in ns:
        for seed in seeds:
            print(f"n={n} seed={seed} ...", flush=True)
            r = run_one(n, seed)
            results.append(r)
            print(f"    -> wall={r['wall_seconds']:.3f}s peak_rss={r['peak_rss_kb']/1024:.1f}MB", flush=True)

    out_json = HERE / "scaling_results.json"
    with open(out_json, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote {out_json}")
