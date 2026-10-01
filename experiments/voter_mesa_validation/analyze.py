"""
Tables for README.md from voter_results.json.

Per tool:
  - win rate of opinion 1 vs the mean predicted probability M(0): the mean
    of (won - M(0)) per run, with a 95% CI and TOST equivalence to 0 within
    +/-0.03 (margin fixed before the run);
  - the same against the naive prediction, the plain initial fraction 0.10;
  - consensus time: mean, median.
Between tools: TOST on the win-rate difference within +/-0.03, and a
two-sample Kolmogorov-Smirnov test on consensus times (same model, same
graphs: the distributions should be the same).
Throughput: agent-updates per second of run time, median and IQR.

    python analyze.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import mean, median, stdev

from scipy import stats

HERE = Path(__file__).resolve().parent
MARGIN = 0.03
NAIVE = 0.10


def tost_zero(v, m):
    lo = stats.ttest_1samp(v, -m, alternative="greater").pvalue
    hi = stats.ttest_1samp(v, m, alternative="less").pvalue
    return max(lo, hi)


def ci(v):
    return mean(v), 1.96 * stdev(v) / math.sqrt(len(v))


def main() -> None:
    rows = json.loads((HERE / "voter_results.json").read_text())
    tools = ("simul8", "mesa")
    by = {t: [r for r in rows if r["tool"] == t] for t in tools}
    print(f"{len(by['simul8'])} seeds per tool; each seed is one graph, shared by both tools.\n")
    print("| Tool | Runs reaching consensus | P(opinion 1 wins) | Mean M(0) (prediction) | "
          "Wins − M(0), 95% CI | ≡ 0 within ±0.03 (TOST p) | Wins − naive 0.10, 95% CI |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    for t in tools:
        done = [r for r in by[t] if r["winner"] is not None]
        d = [r["winner"] - r["m0"] for r in done]
        n = [r["winner"] - NAIVE for r in done]
        (md, hd), (mn, hn) = ci(d), ci(n)
        print(f"| {t} | {len(done)} / {len(by[t])} | {mean(r['winner'] for r in done):.3f} | "
              f"{mean(r['m0'] for r in done):.3f} | {md:+.3f} ± {hd:.3f} | {tost_zero(d, MARGIN):.2g} | "
              f"{mn:+.3f} ± {hn:.3f} |")

    s8 = [r["winner"] for r in by["simul8"] if r["winner"] is not None]
    me = [r["winner"] for r in by["mesa"] if r["winner"] is not None]
    lo = stats.ttest_ind([x + MARGIN for x in s8], me, equal_var=False, alternative="greater").pvalue
    hi = stats.ttest_ind([x - MARGIN for x in s8], me, equal_var=False, alternative="less").pvalue
    print(f"\nSimul8 − Mesa win rate: {mean(s8) - mean(me):+.3f}; equivalent within ±{MARGIN} "
          f"(TOST p = {max(lo, hi):.2g})")

    ts8 = [r["consensus_tick"] for r in by["simul8"] if r["consensus_tick"] is not None]
    tme = [r["consensus_tick"] for r in by["mesa"] if r["consensus_tick"] is not None]
    ks = stats.ks_2samp(ts8, tme)
    print(f"Consensus tick: Simul8 mean {mean(ts8):.1f}, median {median(ts8):g}; "
          f"Mesa mean {mean(tme):.1f}, median {median(tme):g}; KS p = {ks.pvalue:.2g}")

    print("\nThroughput, agent-updates per second of run time (median, IQR):\n")
    print("| Tool | Updates/s | IQR |")
    print("|---|---:|---:|")
    meds = {}
    for t in tools:
        q = stats.mstats.mquantiles([r["updates_per_s"] for r in by[t]], prob=[0.25, 0.5, 0.75])
        meds[t] = q[1]
        print(f"| {t} | {q[1]:,.0f} | {q[0]:,.0f}–{q[2]:,.0f} |")
    print(f"\nMesa / Simul8: {meds['mesa'] / meds['simul8']:.1f}×")


if __name__ == "__main__":
    main()
