"""
Regenerate README.md's tables from latency_results.json.

Per (shape, mean delay): mean ticks to converge with a 95% CI (t
distribution). Per shape: least-squares line through the per-point means,
with R^2. Exponential vs constant at each mean: ratio of means with a
bootstrap 95% CI.

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


def ci95(v):
    h = stats.t.ppf(0.975, len(v) - 1) * stdev(v) / math.sqrt(len(v))
    return mean(v), h


def ratio_ci(a, b, seed=0):
    """Bootstrap 95% CI of mean(a) / mean(b)."""
    rng = random.Random(seed)
    reps = sorted(mean([a[rng.randrange(len(a))] for _ in a]) / mean([b[rng.randrange(len(b))] for _ in b])
                  for _ in range(BOOT))
    return reps[int(0.025 * BOOT)], reps[int(0.975 * BOOT) - 1]


def main() -> None:
    rows = json.loads((HERE / "latency_results.json").read_text())
    assert all(r["converged_tick"] is not None for r in rows), "a run didn't converge"
    seeds = len({r["seed"] for r in rows})
    means = sorted({r["mean_delay"] for r in rows})
    ticks = {(s, m): [r["converged_tick"] for r in rows if r["shape"] == s and r["mean_delay"] == m]
             for s in ("constant", "exponential") for m in means}

    print(f"Ticks to converge, mean ± 95% CI over {seeds} seeds:\n")
    print("| Mean delay | Constant | Exponential | Exponential / constant (95% CI) |")
    print("|---:|---:|---:|---:|")
    for m in means:
        c, e = ticks[("constant", m)], ticks[("exponential", m)]
        (mc, hc), (me, he) = ci95(c), ci95(e)
        lo, hi = ratio_ci(e, c)
        print(f"| {m:g} | {mc:.1f} ± {hc:.1f} | {me:.1f} ± {he:.1f} | {me / mc:.2f} ({lo:.2f}–{hi:.2f}) |")

    print("\nLeast-squares linear fits (through the per-point means):\n")
    print("| Shape | Fit | R² |")
    print("|---|---|---:|")
    for shape in ("constant", "exponential"):
        fit = stats.linregress(means, [mean(ticks[(shape, m)]) for m in means])
        print(f"| {shape.capitalize()} | ticks ≈ {fit.intercept:.1f} + {fit.slope:.2f} · mean | {fit.rvalue ** 2:.4f} |")


if __name__ == "__main__":
    main()
