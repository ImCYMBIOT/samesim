# Gossip Convergence vs. Message Latency

**Status:** first result that needs Phase 1 of
[docs/design/event_model.md](../../docs/design/event_model.md). Before
per-message latency existed, every message took exactly one tick, so this
question could not be asked.

## Question

The Phase 1 design predicted that gossip convergence time grows linearly
with mean message latency. Is that true, and does it matter what shape the
delay distribution has, or only its mean?

## Method

`run_latency_sweep.py` runs push-gossip (`GossipBehavior`, `fan_out=2`) on
an Erdős–Rényi graph (n=200, average degree 8) through `LatencyProtocol`,
sweeping the mean delay over {1, 2, 3, 4, 6, 8, 12, 16} time units
(`tick_interval=1`) for two shapes with the **same mean**:

- **constant**: every message takes exactly the mean
- **exponential**: delays drawn from Exp(mean)

5 seeds per point, 80 runs total. Convergence is measured as in
[gossip_topology_validation/](../gossip_topology_validation/): the first
tick at which population variance falls to 1% of its initial value. Every
run converged.

```
python run_latency_sweep.py           # full sweep, ~5 min
python run_latency_sweep.py --quick   # smoke run
```

Raw output: `latency_results.json`.

## Results

Ticks to converge, mean ± std over 5 seeds:

| Mean delay | Constant | Exponential |
|---:|---:|---:|
| 1 | 9.8 ± 0.8 | 12.6 ± 0.9 |
| 2 | 15.0 ± 1.2 | 16.2 ± 1.3 |
| 3 | 18.8 ± 0.8 | 20.6 ± 1.1 |
| 4 | 23.0 ± 1.0 | 24.6 ± 1.1 |
| 6 | 32.4 ± 0.5 | 31.4 ± 0.9 |
| 8 | 41.8 ± 0.4 | 38.6 ± 2.1 |
| 12 | 62.2 ± 0.4 | 50.2 ± 2.9 |
| 16 | 82.2 ± 0.4 | 63.4 ± 4.2 |

Least-squares linear fits:

| Shape | Fit | R² |
|---|---|---:|
| Constant | ticks ≈ 4.3 + 4.82 · mean | 0.999 |
| Exponential | ticks ≈ 10.4 + 3.36 · mean | 0.997 |

## Interpretation

**The prediction holds.** Convergence time is linear in the mean delay for
both shapes, with R² ≥ 0.997. For constant delay, once latency dominates,
convergence takes about 5 delay-lengths (ticks / mean falls from 9.8 at
mean 1 toward 5.1 at mean 16). A log-log slope computed over the same data
comes out below 1 (0.77 and 0.59) only because of the intercept: the
relationship is affine, not sublinear.

**But the shape of the distribution matters, not just its mean.** With
identical means, exponential delays converge *slower* than constant ones at
small means and *faster* at large means, crossing between 4 and 6. At mean
16, exponential is 23% faster. Two mechanisms plausibly explain the two
regimes. Neither has been isolated yet:

1. **Small means: tick rounding.** Delays round up to whole ticks. Exp(1)
   puts 37% of messages at 2 or more ticks, so its effective mean is
   1/(1 − e⁻¹) ≈ 1.58 ticks, not 1. Constant delay 1 is exactly 1 tick.
2. **Large means: fast paths.** The exponential's density peaks at zero,
   so a sizeable fraction of messages always arrive well ahead of the mean.
   Gossip on a well-connected graph spreads information along whichever
   paths happen to be fast, so what matters is closer to the *minimum* over
   many paths than to the mean. Constant delay has no fast paths.

The variance across seeds also grows with mean for exponential delays
(±0.9 at mean 6, ±4.2 at mean 16) and stays flat for constant delays. That
is consistent with outcomes depending on which fast paths a given run
happened to draw.

## What this doesn't cover yet

- The two mechanisms are hypotheses. Tests that would separate them: run
  the same sweep at `tick_interval=0.1`, where rounding is ten times
  finer (mechanism 1 should shrink, mechanism 2 should not), and compare
  delay distributions with equal mean but different minimum.
- One graph, one size, one fan-out.
- Under synchronous activation, agents still act only on ticks. Latency
  under asynchronous activation (Phase 2) may behave differently.
