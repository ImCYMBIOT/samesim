"""
Tables for README.md from mm1_results.json.

For each rho and each of Wq, W, L:
  - each tool's mean over seeds with a 95% CI (t distribution);
  - TOST equivalence of each tool with the closed form, within +/-3% of
    the closed-form value (one-sample);
  - TOST equivalence of Simul8 with SimPy, within +/-3% of the closed-form
    value (two-sample, Welch).
The +/-3% margin was fixed before the first run.

Throughput: customers completed per second of run time, median and IQR.

    python analyze.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import mean, median, stdev

from scipy import stats

HERE = Path(__file__).resolve().parent
MU = 1.0
MARGIN = 0.03


def theory(rho):
    lam = rho * MU
    return {"Wq": rho / (MU - lam), "W": 1 / (MU - lam), "L": rho / (1 - rho)}


def ci95(v):
    return mean(v), stats.t.ppf(0.975, len(v) - 1) * stdev(v) / math.sqrt(len(v))


def tost_one(v, target, m):
    lo = stats.ttest_1samp(v, target - m, alternative="greater").pvalue
    hi = stats.ttest_1samp(v, target + m, alternative="less").pvalue
    return max(lo, hi)


def tost_two(a, b, m):
    lo = stats.ttest_ind([x + m for x in a], b, equal_var=False, alternative="greater").pvalue
    hi = stats.ttest_ind([x - m for x in a], b, equal_var=False, alternative="less").pvalue
    return max(lo, hi)


def quartiles(v):
    q = stats.mstats.mquantiles(v, prob=[0.25, 0.5, 0.75])
    return q[0], q[1], q[2]


def main() -> None:
    rows = json.loads((HERE / "mm1_results.json").read_text())
    rhos = sorted({r["rho"] for r in rows})
    seeds = len({r["seed"] for r in rows})
    print(f"Mean over {seeds} seeds ± 95% CI. TOST margin ±{MARGIN:.0%} of the closed form; "
          f"p < 0.05 means equivalence is shown.\n")
    print("| ρ | Metric | Closed form | Simul8 | SimPy | Simul8 ≡ theory (TOST p) | "
          "SimPy ≡ theory (TOST p) | Simul8 ≡ SimPy (TOST p) |")
    print("|---:|---|---:|---:|---:|---:|---:|---:|")
    for rho in rhos:
        th = theory(rho)
        for metric in ("Wq", "W", "L"):
            s8 = [r[metric] for r in rows if r["rho"] == rho and r["tool"] == "simul8"]
            sp = [r[metric] for r in rows if r["rho"] == rho and r["tool"] == "simpy"]
            m = MARGIN * th[metric]
            (ms, hs), (mp, hp) = ci95(s8), ci95(sp)
            print(f"| {rho:g} | {metric} | {th[metric]:.3f} | {ms:.3f} ± {hs:.3f} | {mp:.3f} ± {hp:.3f} | "
                  f"{tost_one(s8, th[metric], m):.2g} | {tost_one(sp, th[metric], m):.2g} | "
                  f"{tost_two(s8, sp, m):.2g} |")

    print("\nThroughput, customers completed per second of run time (median, IQR):\n")
    print("| ρ | Simul8 | SimPy | SimPy / Simul8 |")
    print("|---:|---:|---:|---:|")
    for rho in rhos:
        s8 = [r["customers_per_s"] for r in rows if r["rho"] == rho and r["tool"] == "simul8"]
        sp = [r["customers_per_s"] for r in rows if r["rho"] == rho and r["tool"] == "simpy"]
        a, b = quartiles(s8), quartiles(sp)
        print(f"| {rho:g} | {a[1]:,.0f} ({a[0]:,.0f}–{a[2]:,.0f}) | {b[1]:,.0f} ({b[0]:,.0f}–{b[2]:,.0f}) | "
              f"{median(sp) / median(s8):.1f}× |")


if __name__ == "__main__":
    main()
