"""
Regenerate README.md's tables from async_results.json.

Per (protocol, topology, n, threshold): mean time to threshold with a 95% CI.
Per (protocol, topology, threshold): the log-log slope of mean time against
n with a bootstrap 95% CI (seeds resampled within each n), and for rings the
slope of the last doubling. Runs that never reached a threshold are excluded
and counted.

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
THRESHOLDS = ("t_0.01", "t_0.0001")


def slope(ns, means):
    return stats.linregress([math.log(n) for n in ns], [math.log(m) for m in means]).slope


def slope_ci(by_n, seed=0):
    rng = random.Random(seed)
    ns = sorted(by_n)
    reps = sorted(slope(ns, [mean([by_n[n][rng.randrange(len(by_n[n]))] for _ in by_n[n]]) for n in ns])
                  for _ in range(BOOT))
    return reps[int(0.025 * BOOT)], reps[int(0.975 * BOOT) - 1]


def main() -> None:
    rows = json.loads((HERE / "async_results.json").read_text())
    seeds = len({r["seed"] for r in rows})
    print(f"{seeds} seeds per point.\n")
    for topo in dict.fromkeys(r["topology"] for r in rows):
        ns = sorted({r["n"] for r in rows if r["topology"] == topo})
        print(f"### {topo}\n")
        print("| n | " + " | ".join(f"{p}, {t[2:]}" for t in THRESHOLDS for p in ("sync", "async")) + " |")
        print("|---:|" + "---:|" * 4)
        data = {}
        for n in ns:
            cells = []
            for t in THRESHOLDS:
                for p in ("sync", "async"):
                    rs = [r for r in rows if r["topology"] == topo and r["n"] == n and r["protocol"] == p]
                    v = [r[t] for r in rs if r[t] is not None]
                    data.setdefault((p, t), {})[n] = v
                    h = stats.t.ppf(0.975, len(v) - 1) * stdev(v) / math.sqrt(len(v))
                    miss = len(rs) - len(v)
                    cells.append(f"{mean(v):,.1f} ± {h:,.1f}" + (f" ({miss} not reached)" if miss else ""))
            print(f"| {n} | " + " | ".join(cells) + " |")
        cells = []
        for t in THRESHOLDS:
            for p in ("sync", "async"):
                by_n = data[(p, t)]
                s = slope(sorted(by_n), [mean(by_n[n]) for n in sorted(by_n)])
                lo, hi = slope_ci(by_n)
                cells.append(f"**{s:.2f}** ({lo:.2f}–{hi:.2f})")
        print("| **slope (95% CI)** | " + " | ".join(cells) + " |")
        if topo == "ring":
            last = []
            for t in THRESHOLDS:
                for p in ("sync", "async"):
                    by_n = data[(p, t)]
                    a, b = ns[-2], ns[-1]
                    last.append(f"{math.log(mean(by_n[b]) / mean(by_n[a])) / math.log(b / a):.2f}")
            print(f"| last doubling ({ns[-2]} → {ns[-1]}) | " + " | ".join(last) + " |")
        print()


if __name__ == "__main__":
    main()
