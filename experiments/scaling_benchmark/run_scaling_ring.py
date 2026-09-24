"""
Scaling benchmark, Ring topology arm.

RingTopology.generate() is O(n) (each agent just connects to its immediate
left/right neighbor), unlike ErdosRenyiTopology.generate() which checks every
possible pair (O(n^2)) regardless of edge probability. Running the same
scaling sweep on Ring isolates the *engine's own* scaling behavior from that
one topology plugin's complexity -- see run_scaling.py's results for the
combined (engine + O(n^2) topology-gen) picture on Erdos-Renyi.
"""
from __future__ import annotations

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

HERE = Path(__file__).resolve().parent
# Intermediate configs and per-run CSVs. Kept out of the repo by default
# (see .gitignore); override with SIMUL8_EXPERIMENT_WORK to relocate.
SCRATCH = Path(os.environ.get("SIMUL8_EXPERIMENT_WORK", HERE / "_work"))
CONFIG_DIR = SCRATCH / "configs_ring"
RESULTS_DIR = SCRATCH / "results_ring"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

FAN_OUT = 2
MAX_VIRTUAL_TIME = 50


class _EventsCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.events_processed = None

    def emit(self, record: logging.LogRecord) -> None:
        if record.name == "simul8.core.engine" and "events_processed" in record.msg:
            self.events_processed = record.args[1]


def make_config(n: int, seed: int) -> tuple[str, Path]:
    name = f"ring_n{n}_s{seed}"
    cfg = {
        "schema_version": "1.0",
        "experiment": {"name": name, "seed": seed},
        "simulation": {"num_agents": n, "max_virtual_time": MAX_VIRTUAL_TIME, "tick_interval": 1},
        "plugins": {
            "behavior": "simul8.plugins.behaviors.gossip_behavior.GossipBehavior",
            "communication": "simul8.plugins.communication.gossip.GossipProtocol",
            "topology": "simul8.plugins.topologies.ring.RingTopology",
            "metrics": [
                "simul8.plugins.metrics.message_count.MessageCountMetric",
                "simul8.plugins.metrics.convergence.ConvergenceMetric",
            ],
            "persistence": ["simul8.plugins.persistence.csv_exporter.CsvExporter"],
        },
        "plugin_configs": {
            "GossipBehavior": {"initial_value_range": [0.0, 1.0], "fan_out": FAN_OUT},
            "RingTopology": {},
        },
    }
    path = CONFIG_DIR / f"{name}.yaml"
    with open(path, "w") as f:
        yaml.dump(cfg, f)
    return name, path


def run_one(n: int, seed: int) -> dict:
    name, cfg_path = make_config(n, seed)
    out_dir = RESULTS_DIR / name

    mem_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

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

    mem_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    return {
        "n": n,
        "seed": seed,
        "max_virtual_time": MAX_VIRTUAL_TIME,
        "wall_seconds": wall,
        "events_processed": capture.events_processed,
        "events_per_second": (capture.events_processed / wall) if capture.events_processed and wall > 0 else None,
        "peak_rss_kb": mem_after,
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
            print(f"    -> wall={r['wall_seconds']:.3f}s events/s={r['events_per_second']:.0f}", flush=True)

    out_json = HERE / "scaling_ring_results.json"
    with open(out_json, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote {out_json}")
