"""
M/M/1 queue: Simul8 vs. SimPy vs. the closed forms.

The same queue -- Poisson arrivals at rate lambda, one server with
exponential service at rate mu = 1, FIFO -- run in both tools:

    simul8  QueueBehavior (one source agent sending customers to one server
            agent as messages, constant latency 0.001), event activation,
            QueueMetric
    simpy   the textbook SimPy model: a source process, a Resource of
            capacity 1, customers that request it and hold it for an
            exponential time

for rho = lambda / mu in {0.5, 0.8, 0.9}, 100 seeds each, horizon 50,000
time units with the first 5,000 discarded as warm-up. Per run:

    Wq  mean wait in queue of customers arriving after the warm-up
    W   mean time in system of the same customers
    L   time-average number in system over [warm-up, horizon]
    customers_per_s  customers completed per second of run time (the
        simulation itself: Simul8's engine loop, SimPy's env.run)

Closed forms: Wq = rho / (mu - lambda), W = 1 / (mu - lambda),
L = rho / (1 - rho).

    python run_mm1.py            # full (~20 min)
    python run_mm1.py --quick    # smoke run -> mm1_results_quick.json

Output: mm1_results.json next to this script.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
import time
from pathlib import Path

import simpy
import yaml

# Repo root, derived from this file so the script runs from any checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from simul8.app.experiment_runner import ExperimentRunner  # noqa: E402

HERE = Path(__file__).resolve().parent
SCRATCH = Path(os.environ.get("SIMUL8_EXPERIMENT_WORK", HERE / "_work"))

MU = 1.0
HORIZON = 50_000.0
WARMUP = 5_000.0
LATENCY = 0.001  # Simul8's source -> server message delay: shifts every arrival equally


def summarize(customers, area_at, horizon, warmup):
    """customers: (arrival, start, end) of each completed customer."""
    kept = [(a, s, e) for a, s, e in customers if a >= warmup]
    wq = sum(s - a for a, s, _ in kept) / len(kept)
    w = sum(e - a for a, _, e in kept) / len(kept)
    L = (area_at(horizon) - area_at(warmup)) / (horizon - warmup)
    return {"Wq": wq, "W": w, "L": L, "customers": len(customers)}


def run_simul8(rho: float, seed: int) -> dict:
    name = f"mm1_r{rho:g}_s{seed}"
    cfg = {
        "schema_version": "1.0",
        "experiment": {"name": name, "seed": seed},
        "simulation": {"num_agents": 2, "max_virtual_time": HORIZON,
                       "tick_interval": 100.0, "activation": "event"},
        "plugins": {
            "behavior": "simul8.plugins.behaviors.queue.QueueBehavior",
            "communication": "simul8.plugins.communication.latency.LatencyProtocol",
            "topology": "simul8.plugins.topologies.ring.RingTopology",
            "metrics": ["simul8.plugins.metrics.queue_metrics.QueueMetric"],
            "persistence": ["simul8.plugins.persistence.csv_exporter.CsvExporter"],
        },
        "plugin_configs": {
            "QueueBehavior": {"arrival_rate": rho * MU, "service_rate": MU},
            "LatencyProtocol": {"distribution": "constant", "delay": LATENCY},
        },
    }
    (SCRATCH / "configs").mkdir(parents=True, exist_ok=True)
    path = SCRATCH / "configs" / f"{name}.yaml"
    path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    out = SCRATCH / "results" / name
    ExperimentRunner().run(path, output_dir=out)

    wall = json.loads((out / "summary.json").read_text())["wall_clock_runtime_seconds"]
    with open(out / f"{name}_queue.csv", newline="") as f:
        rows = list(csv.DictReader(l for l in f if not l.startswith("#")))
    customers = []
    for r in rows:
        if r["kind"] == "departure":
            end = float(r["virtual_time"])
            arrival = end - float(r["sojourn"])
            customers.append((arrival, arrival + float(r["value"]), end))
    area = {float(r["virtual_time"]): float(r["value"]) for r in rows if r["kind"] == "area"}
    res = summarize(customers, lambda t: area[t], HORIZON, WARMUP)
    res["customers_per_s"] = res["customers"] / wall
    return res


def run_simpy(rho: float, seed: int) -> dict:
    rng = random.Random(seed)
    env = simpy.Environment()
    server = simpy.Resource(env, capacity=1)
    customers = []
    occupancy = {"n": 0, "last": 0.0, "area": 0.0, "marks": {}}

    def change(delta):
        occupancy["area"] += occupancy["n"] * (env.now - occupancy["last"])
        occupancy["last"] = env.now
        occupancy["n"] += delta

    def customer():
        arrival = env.now
        change(+1)
        with server.request() as req:
            yield req
            start = env.now
            yield env.timeout(rng.expovariate(MU))
        change(-1)
        customers.append((arrival, start, env.now))

    def source():
        while True:
            yield env.timeout(rng.expovariate(rho * MU))
            env.process(customer())

    def mark(t):  # record the integral of N(t) at time t
        yield env.timeout(t)
        change(0)
        occupancy["marks"][t] = occupancy["area"]

    env.process(source())
    env.process(mark(WARMUP))
    env.process(mark(HORIZON))
    t0 = time.perf_counter()
    env.run(until=HORIZON + 1e-9)
    wall = time.perf_counter() - t0
    res = summarize(customers, lambda t: occupancy["marks"][t], HORIZON, WARMUP)
    res["customers_per_s"] = res["customers"] / wall
    return res


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    rhos = [0.8] if args.quick else [0.5, 0.8, 0.9]
    seeds = [1, 2] if args.quick else list(range(1, 101))
    out_json = HERE / ("mm1_results_quick.json" if args.quick else "mm1_results.json")
    results = []
    for rho in rhos:
        for seed in seeds:
            for tool, fn in (("simul8", run_simul8), ("simpy", run_simpy)):
                r = {"tool": tool, "rho": rho, "seed": seed, **fn(rho, seed)}
                results.append(r)
                print(f"{tool:6} rho={rho} seed={seed:2d}  Wq={r['Wq']:.3f}  W={r['W']:.3f}  "
                      f"L={r['L']:.3f}  {r['customers_per_s']:,.0f} customers/s", flush=True)
    out_json.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {out_json}")


if __name__ == "__main__":
    main()
