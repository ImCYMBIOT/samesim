"""
Tables for README.md from peersim_results.json.

Per run: the per-cycle variance reduction factor, as the geometric mean of
var(c+1)/var(c) over all cycles. Per tool and part: mean with a 95% CI;
TOST equivalence with Jelasity's 1/(2*sqrt(e)) on the complete graph, and
between the tools, within +/-0.01 (fixed before the run).

Speed: wall time per run (median of 3) and node-exchanges per second.

    python analyze.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import mean, median, stdev

from scipy import stats

HERE = Path(__file__).resolve().parent
THEORY = 1 / (2 * math.sqrt(math.e))
MARGIN = 0.01


def factor(var):
    ratios = [b / a for a, b in zip(var, var[1:])]
    return math.exp(mean(math.log(r) for r in ratios))


def ci(v):
    return mean(v), stats.t.ppf(0.975, len(v) - 1) * stdev(v) / math.sqrt(len(v))


def tost_one(v, target, m):
    return max(stats.ttest_1samp(v, target - m, alternative="greater").pvalue,
               stats.ttest_1samp(v, target + m, alternative="less").pvalue)


def tost_two(a, b, m):
    return max(stats.ttest_ind([x + m for x in a], b, equal_var=False, alternative="greater").pvalue,
               stats.ttest_ind([x - m for x in a], b, equal_var=False, alternative="less").pvalue)


def main() -> None:
    rows = json.loads((HERE / "peersim_results.json").read_text())
    print(f"Per-cycle variance reduction factor (geometric mean over 15 cycles), mean ± 95% CI.\n"
          f"Jelasity et al.: 1/(2√e) = {THEORY:.4f}. TOST margin ±{MARGIN}.\n")
    print("| Graph | SameSim | PeerSim | SameSim ≡ theory (TOST p) | PeerSim ≡ theory (TOST p) | "
          "SameSim ≡ PeerSim (TOST p) |")
    print("|---|---:|---:|---:|---:|---:|")
    for part, label in (("theory", "complete, n = 1,000"), ("sparse", "Erdős–Rényi, degree 20, n = 1,000")):
        s = [factor(r["variance"]) for r in rows if r["part"] == part and r["tool"] == "samesim"]
        p = [factor(r["variance"]) for r in rows if r["part"] == part and r["tool"] == "peersim"]
        if not s:
            continue
        (ms, hs), (mp, hp) = ci(s), ci(p)
        th = (f"{tost_one(s, THEORY, MARGIN):.2g}", f"{tost_one(p, THEORY, MARGIN):.2g}") if part == "theory" else ("–", "–")
        print(f"| {label} ({len(s)} seeds) | {ms:.4f} ± {hs:.4f} | {mp:.4f} ± {hp:.4f} | {th[0]} | {th[1]} | "
              f"{tost_two(s, p, MARGIN):.2g} |")

    speed = [r for r in rows if r["part"] == "speed"]
    if speed:
        print("\nSpeed: Erdős–Rényi, average degree 20, 20 cycles; wall time per run, median of 3 "
              "(PeerSim: whole JVM process; SameSim: whole run, and the event loop alone).\n")
        print("| n | PeerSim | SameSim | SameSim event loop | SameSim / PeerSim | "
              "SameSim exchanges/s | PeerSim exchanges/s |")
        print("|---:|---:|---:|---:|---:|---:|---:|")
        for n in sorted({r["n"] for r in speed}):
            ps = median(r["wall_total"] for r in speed if r["n"] == n and r["tool"] == "peersim")
            ss = median(r["wall_total"] for r in speed if r["n"] == n and r["tool"] == "samesim")
            se = median(r["wall_engine"] for r in speed if r["n"] == n and r["tool"] == "samesim")
            ex = n * 20
            print(f"| {n:,} | {ps:.2f} s | {ss:.2f} s | {se:.2f} s | {ss / ps:.0f}× | "
                  f"{ex / se:,.0f} | {ex / ps:,.0f} |")


if __name__ == "__main__":
    main()
