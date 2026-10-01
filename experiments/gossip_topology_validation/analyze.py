"""
Regenerate README.md's tables from full_results.json and full_ws_ba_results.json.

Per (topology, n): mean ticks to the 1% threshold with a 95% CI. Per
topology: the log-log slope of mean ticks against n, with a bootstrap 95% CI
(seeds resampled within each n, 2,000 times, fixed RNG). Runs that never
crossed the threshold are excluded and counted.

    python analyze.py
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path
from statistics import mean, stdev

from scipy import stats

HERE = Path(__file__).resolve().parent
BOOT = 2000


def slope(ns, means):
    return stats.linregress([math.log(n) for n in ns], [math.log(m) for m in means]).slope


def slope_ci(by_n, seed=0):
    rng = random.Random(seed)
    ns = sorted(by_n)
    reps = sorted(slope(ns, [mean([by_n[n][rng.randrange(len(by_n[n]))] for _ in by_n[n]]) for n in ns])
                  for _ in range(BOOT))
    return reps[int(0.025 * BOOT)], reps[int(0.975 * BOOT) - 1]


def main() -> None:
    rows = []
    for name in ("full_results.json", "full_ws_ba_results.json"):
        rows += json.loads((HERE / name).read_text())
    topologies = list(dict.fromkeys(r["topology"] for r in rows))
    seeds = len({r["seed"] for r in rows})

    print(f"Ticks to 1% of initial variance, mean ± 95% CI over {seeds} seeds:\n")
    print("| Topology | n | Mean ticks (95% CI) | Std dev | Not converged |")
    print("|---|---:|---:|---:|---:|")
    fits = []
    for topo in topologies:
        by_n = {}
        for r in rows:
            if r["topology"] == topo and r["converged"]:
                by_n.setdefault(r["n"], []).append(r["converged_tick"])
        missed = {n: sum(1 for r in rows if r["topology"] == topo and r["n"] == n and not r["converged"])
                  for n in by_n}
        for n in sorted(by_n):
            v = by_n[n]
            h = stats.t.ppf(0.975, len(v) - 1) * stdev(v) / math.sqrt(len(v))
            print(f"| {topo} | {n} | {mean(v):.1f} ± {h:.1f} | {stdev(v):.1f} | {missed[n] or ''} |")
        ns = sorted(by_n)
        lo, hi = slope_ci(by_n)
        fits.append((topo, slope(ns, [mean(by_n[n]) for n in ns]), lo, hi))

    print("\nLog-log slope of mean ticks against n (95% bootstrap CI):\n")
    print("| Topology | Slope (95% CI) |")
    print("|---|---:|")
    for topo, s, lo, hi in fits:
        print(f"| {topo} | {s:.2f} ({lo:.2f} to {hi:.2f}) |")


if __name__ == "__main__":
    main()
