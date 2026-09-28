"""
Summarize churn_results.json: median convergence times per (down fraction,
downtime), slowdown relative to no churn, a power-law fit in the live
fraction (1 - f), the lost-message count against its closed form, and a
stale-agent model for whole-system agreement (see stale_model).

    python analyze.py
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent
N, K, T = 200, 2, 400  # must match run_churn_sweep.py


def _med(values):
    vals = [v for v in values if v is not None]
    return (median(vals), len(values) - len(vals)) if vals else (None, len(values))


def _iqr(values):
    vals = sorted(v for v in values if v is not None)
    if len(vals) < 4:
        return "-"
    q = lambda p: vals[round(p * (len(vals) - 1))]
    return f"{q(0.25):g}-{q(0.75):g}"


def _fit(points):
    """Least-squares slope of log(t) against log(1 - f)."""
    xs = [math.log(1 - f) for f, _ in points]
    ys = [math.log(t) for _, t in points]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)


def stale_model(f: float, downtime: float, t_star: float, base: float, samples: int = 20000) -> float:
    """Median whole-system agreement time if only stale values mattered.

    An agent that crashes before t_star (while values are still far apart)
    comes back with a value far enough from consensus to hold the
    all-agent variance above threshold; one that crashes later doesn't.
    So agreement waits until the last pre-t_star crash has recovered, and
    at least until the churn-free convergence time `base`. Crashes are
    Poisson at rate lambda per agent, downtimes Exp(mean = downtime).
    """
    lam = f / (1 - f) / downtime
    p_crash = 1 - math.exp(-lam * t_star)
    rng = random.Random(1)
    out = []
    for _ in range(samples):
        m = sum(1 for _ in range(N) if rng.random() < p_crash)
        last = max((rng.uniform(0, t_star) + rng.expovariate(1 / downtime) for _ in range(m)),
                   default=0.0)
        out.append(max(base, last + 2))  # +2: a couple of ticks to re-absorb it
    return median(out)


def main() -> None:
    rows = json.loads((HERE / "churn_results.json").read_text())
    base = [r for r in rows if r["down_fraction"] == 0]
    downtimes = sorted({r["downtime"] for r in rows if r["down_fraction"] > 0})
    fractions = sorted({r["down_fraction"] for r in rows})
    b_run, _ = _med([r["t_running_0.0001"] for r in base])

    for d in downtimes:
        print(f"\n=== mean downtime D = {d:g} ticks ===")
        print(f"{'f':>5} {'obs f':>6} {'t_run 1e-2':>10} {'t_run 1e-4':>10} {'t_all 1e-4':>10} "
              f"{'t_all IQR':>10} {'settled':>8} {'slowdown':>8} {'|drift|':>8} {'lost':>7} {'pred lost':>9}")
        fit_pts = []
        for f in fractions:
            rs = base if f == 0 else [r for r in rows if r["down_fraction"] == f and r["downtime"] == d]
            if not rs:
                continue
            t2, _ = _med([r["t_running_0.01"] for r in rs])
            t4, c4 = _med([r["t_running_0.0001"] for r in rs])
            ta, ca = _med([r["t_all_0.0001"] for r in rs])
            st, cs = _med([r["settled_all_1e-4"] for r in rs])
            drift = median(abs(r["drift"]) for r in rs)
            lost = median(r["lost"] for r in rs)
            obs = median(r["down_fraction_observed"] for r in rs)
            # Closed form at the OBSERVED down fraction: RandomChurn starts
            # with everyone up and takes ~D ticks to reach f, so with long
            # downtimes the time-averaged fraction is below the target.
            pred = obs * (1 - obs) * N * K * T
            if t4:
                fit_pts.append((f, t4))
            fmt = lambda v, c: ("-" if v is None else f"{v:g}") + (f" ({c} cens.)" if c else "")
            print(f"{f:>5g} {obs:>6.3f} {fmt(t2, 0):>10} {fmt(t4, c4):>10} {fmt(ta, ca):>10} "
                  f"{_iqr([r['t_all_0.0001'] for r in rs]):>10} {fmt(st, cs):>8} {t4 / b_run if t4 else float('nan'):>8.2f} {drift:>8.3f} "
                  f"{lost:>7g} {pred:>9.0f}")
        if len(fit_pts) >= 3:
            print(f"fit: t_running(1e-4) ~ (1 - f)^{_fit(fit_pts):.2f}")

    # t_star is not fitted: it is the churn-free time to reach 1e-2 v0,
    # after which a typical agent is within ~0.1 sigma of consensus.
    t_star, _ = _med([r["t_running_0.01"] for r in base])
    print(f"\nstale-agent model (t* = {t_star:g}) vs observed median t_all(1e-4):")
    for d in downtimes:
        for f in fractions:
            if f == 0:
                continue
            obs, _ = _med([r["t_all_0.0001"] for r in rows if r["down_fraction"] == f and r["downtime"] == d])
            print(f"  D={d:<4g} f={f:<5g} model {stale_model(f, d, t_star, b_run):6.1f}   observed {obs}")


if __name__ == "__main__":
    main()
