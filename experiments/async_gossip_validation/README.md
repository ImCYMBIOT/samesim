# Synchronous vs. Asynchronous Gossip on a Ring

**Status:** first result that needs Phase 2 (event-driven agents) of
[docs/design.md](../../docs/design.md). It
**corrects** an interpretation in
[gossip_topology_validation/](../gossip_topology_validation/).

## Question

[gossip_topology_validation/](../gossip_topology_validation/) found that
synchronous push gossip converges in O(n) ticks on a ring, not the classical
O(n²). It offered two untested explanations:

1. the protocol: synchronous, full-neighbor push rather than Boyd et al.'s
   asynchronous pairwise exchanges;
2. the measurement: a 1% variance threshold, crossed while fast modes still
   dominate, before the slowest mode's O(n²) decay matters.

Before Phase 2, Simul8 couldn't run Boyd et al.'s model at all, so the two
couldn't be separated. Now it can.

## Method

`run_async_sweep.py` runs two protocols on the same graphs and seeds:

- **sync:** `GossipBehavior`. Every agent pushes to `fan_out=2` neighbors every
  tick and averages what it receives (synchronous activation).
- **async:** `AsyncGossipBehavior`, randomized pairwise averaging
  on per-agent Poisson clocks (Boyd, Ghosh, Prabhakar & Shah, *Randomized
  Gossip Algorithms*, IEEE Trans. Inf. Theory, 2006), under event
  activation. Latency is 0.01, a hundredth of the clock period, so exchanges
  rarely overlap and the model is Boyd's.

The communication budgets are matched: sync sends 2 messages per agent per tick,
and async at clock rate 1 makes one pull/push exchange (2 messages) per agent
per time unit. Rings with n = 10…160 and Erdős–Rényi graphs (average degree 8)
with n = 50…800 were tested, 5 seeds each, 100 runs in total. Each run records the time
until population variance first falls to **1e-2** and to **1e-4** of its
initial value. Both protocols get the same window, 0.5·n² time units on
rings.

```
python run_async_sweep.py           # full sweep, ~30 min (resumes if interrupted)
python run_async_sweep.py --quick   # smoke run
```

Raw output: `async_results.json`.

## Results

Mean time to threshold (± std over 5 seeds):

**Ring**

| n | sync, 1e-2 | async, 1e-2 | sync, 1e-4 | async, 1e-4 |
|---:|---:|---:|---:|---:|
| 10 | 7.6 ± 1.7 | 8.2 ± 2.5 | 24.4 ± 1.3 | 20.4 ± 2.7 |
| 20 | 20.6 ± 8.6 | 14.6 ± 6.6 | 87.0 ± 13.5 | 56.8 ± 17.3 |
| 40 | 40.4 ± 15.5 | 28.6 ± 12.2 | 281.8 ± 36.2 | 200.2 ± 30.6 |
| 80 | 50.4 ± 19.9 | 42.0 ± 20.5 | 811.8 ± 282.3 | 601.0 ± 183.5 |
| 160 | 177.4 ± 31.8 | 132.8 ± 45.8 | 4,381.6 ± 195.9 | 3,015.8 ± 143.5 |
| **fitted slope** | **1.04** | **0.96** | **1.82** | **1.78** |

**Erdős–Rényi** (average degree 8), fitted slopes: sync 0.04 / 0.12, async
0.04 / 0.05 (at 1e-2 / 1e-4). Flat, as expected. At 1e-4, async takes
11–14 time units against sync's 25–36.

## Interpretation

**Explanation 2 is right. Explanation 1 is not.**

- **The threshold decides the exponent, not the protocol.** At 1% both
  protocols look linear on the ring (1.04, 0.96). At 1e-4 both are close to
  quadratic (1.82, 1.78), with the largest-n segments at 2.43 and 2.33. The
  classical O(n²) regime appears as soon as the measurement reaches the
  slowest mode's decay, for synchronous push gossip as much as for Boyd's
  model.
- **Simul8 reproduces Boyd et al.'s O(n²).** The asynchronous pairwise model
  on a ring has a fitted slope of 1.78 at 1e-4. The fit is pulled below 2 by the
  smallest rings, where constant terms matter. The last doubling, 80 → 160, is
  2.33.
- **The earlier study's headline was an artifact.** Its README claimed the
  linear ring exponent was "a claim about this protocol". That is wrong, and it
  now carries a correction. Convergence-scaling results should be reported at a
  threshold in the asymptotic regime, or at more than one threshold.
- **Pairwise exchange mixes faster than one-way push** for the same message budget:
  async is about 1.4× faster on rings and 2–3× faster on Erdős–Rényi at 1e-4.
  That's plausible, since a pull/push exchange moves both endpoints to their mean,
  while push-averaging only moves the receiver. It hasn't been isolated
  further.

**Checks.** Re-running the synchronous ring configurations with a longer window
reproduced every earlier value exactly. One Erdős–Rényi graph (n = 800, seed 5)
never reached 1e-4 under **either** protocol. Regenerating it shows agent
799 has no edges, and an isolated agent keeps its value forever, which puts a
floor under the variance. That point is averaged over the 4 connected seeds. After the switch to portable math (async clocks
previously used libm's `log` via `random.expovariate`, whose last bit
differs by OS), the full sweep was re-run: all 100 runs gave identical
convergence times.

## What this doesn't cover yet

- Five seeds per point leaves the large-n ring estimates noisy (± 283 at
  n = 80). More seeds, or larger n with a run-until-converged stop condition,
  would tighten the exponent.
- No closed-form constant is checked, only the exponent.
- Boyd et al.'s model assumes instantaneous exchanges. The effect of latency
  comparable to the clock period (overlapping exchanges, where the sum of values
  is no longer conserved) is untested.
