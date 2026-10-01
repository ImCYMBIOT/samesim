"""
Regenerate every table in README.md from raft_results.json and
raft_crash_results.json.

Medians come with bootstrap 95% confidence intervals (2,000 resamples,
fixed RNG).

The crash-vs-cold-start comparison uses the MEAN and the fraction of runs
that needed a second election round, each with a bootstrap CI of the
difference -- not the median. With narrow timeout ranges the distribution
is bimodal (one round at ~hi ms, two rounds at ~2*lo ms), and when about
half the runs need a second round the median jumps between the two modes
from one sample to the next: the 150-175 ms crash median was 299 ms in one
run of this sweep and 186 ms in another, from nearly identical
distributions. A run "needed a second round" if it took longer than
hi + 50 ms: the first round is over by then (timeout <= hi, plus at most
~15 ms of latency per message), and the second can't start before 2 * lo.

    python analyze.py
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path
from statistics import mean, median

HERE = Path(__file__).resolve().parent
BOOT = 2000


def pct(values, p):
    """Nearest-rank percentile."""
    v = sorted(values)
    return v[max(0, math.ceil(p / 100 * len(v)) - 1)]


def boot_ci(values, stat=median, seed=0):
    rng = random.Random(seed)
    n = len(values)
    reps = sorted(stat([values[rng.randrange(n)] for _ in range(n)]) for _ in range(BOOT))
    return reps[int(0.025 * BOOT)], reps[int(0.975 * BOOT) - 1]


def boot_diff_ci(a, b, stat=mean, seed=0):
    rng = random.Random(seed)
    reps = sorted(
        stat([a[rng.randrange(len(a))] for _ in a]) - stat([b[rng.randrange(len(b))] for _ in b])
        for _ in range(BOOT)
    )
    return reps[int(0.025 * BOOT)], reps[int(0.975 * BOOT) - 1]


def fmt_ci(values):
    lo, hi = boot_ci(values)
    return f"{median(values):,.0f} ({lo:,.0f}–{hi:,.0f})"


def main() -> None:
    cold = json.loads((HERE / "raft_results.json").read_text())
    crash = json.loads((HERE / "raft_crash_results.json").read_text())

    def group(rows, sweep):
        out = {}
        for r in rows:
            if r["sweep"] == sweep:
                out.setdefault((r["lo"], r["hi"]), []).append(r)
        return out

    print("## Cold start: timeout randomization (5 nodes, 5 s)\n")
    print("| Timeout range (ms) | Elected within 5 s | Median (95% CI) | p95 | Max | Mean winning term |")
    print("|---|---:|---:|---:|---:|---:|")
    for (lo, hi), rs in group(cold, "randomness").items():
        t = [r["first_election_ms"] for r in rs if r["first_election_ms"] is not None]
        if t:
            terms = mean(r["first_term"] for r in rs if r["first_term"] is not None)
            print(f"| {lo:g}–{hi:g} | {len(t)} / {len(rs)} | {fmt_ci(t)} | {pct(t, 95):,.0f} | "
                  f"{max(t):,.0f} | {terms:.2f} |")
        else:
            print(f"| {lo:g}–{hi:g} | 0 / {len(rs)} | — | — | — | — |")

    print("\n## Cold start: timeout scale\n")
    print("| Timeout range (ms) | Median (95% CI) | p95 | Mean winning term | Further elections per run |")
    print("|---|---:|---:|---:|---:|")
    for (lo, hi), rs in group(cold, "scale").items():
        t = [r["first_election_ms"] for r in rs if r["first_election_ms"] is not None]
        terms = mean(r["first_term"] for r in rs if r["first_term"] is not None)
        later = mean(r["later_elections"] for r in rs)
        print(f"| {lo:g}–{hi:g} | {fmt_ci(t)} | {pct(t, 95):,.0f} | {terms:.2f} | {later:.2f} |")

    cold_times = {k: [r["first_election_ms"] for r in rs if r["first_election_ms"] is not None]
                  for sweep in ("randomness", "scale") for k, rs in group(cold, sweep).items()}

    print("\n## Leader crash (steady state, crash the leader, time until a new leader)\n")
    print("| Timeout range (ms) | Recovered within 5 s | Median downtime (95% CI) | p95 | Max | "
          "Mean new term | Mean: crash vs cold (difference, 95% CI) | Second round: crash vs cold (difference, 95% CI) |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|")
    seen = set()
    for sweep in ("randomness", "scale"):
        for (lo, hi), rs in group(crash, sweep).items():
            if (lo, hi) in seen:
                continue
            seen.add((lo, hi))
            d = [r["downtime_ms"] for r in rs if r["downtime_ms"] is not None]
            c = cold_times.get((lo, hi), [])
            if not d:
                print(f"| {lo:g}–{hi:g} | 0 / {len(rs)} | — | — | — | — | — | — |")
                continue
            terms = mean(r["new_term"] for r in rs if r["new_term"] is not None)
            if len(c) >= 20 and len(d) >= 20:
                dlo, dhi = boot_diff_ci(d, c)
                mean_cmp = (f"{mean(d):,.0f} vs {mean(c):,.0f} "
                            f"({mean(d) - mean(c):+,.0f}; {dlo:+,.0f} to {dhi:+,.0f})")
                cut = hi + 50
                sd = [1.0 if x > cut else 0.0 for x in d]
                sc = [1.0 if x > cut else 0.0 for x in c]
                flo, fhi = boot_diff_ci(sd, sc)
                frac_cmp = (f"{mean(sd):.0%} vs {mean(sc):.0%} "
                            f"({(mean(sd) - mean(sc)) * 100:+.0f} pts; {flo * 100:+.0f} to {fhi * 100:+.0f})")
            else:
                mean_cmp = frac_cmp = "cold start never elects" if not c else "—"
            print(f"| {lo:g}–{hi:g} | {len(d)} / {len(rs)} | {fmt_ci(d)} | {pct(d, 95):,.0f} | "
                  f"{max(d):,.0f} | {terms:.2f} | {mean_cmp} | {frac_cmp} |")

    trials = len(cold) + len(crash)
    violations = sum(r["safety_violations"] for r in cold + crash)
    print(f"\nElection Safety violations: {violations} in {trials:,} trials")


if __name__ == "__main__":
    main()
