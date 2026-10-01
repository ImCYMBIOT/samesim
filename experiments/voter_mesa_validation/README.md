# Voter model: SameSim vs. Mesa vs. an exact result

The voter model in SameSim and in [Mesa](https://mesa.readthedocs.io), the
standard Python agent-based modeling library, on identical graphs, checked
against an exact martingale result. It is also a second, very different
domain (opinion dynamics) run on the same engine with no core changes.

**Result: both tools follow the exact prediction, not the naive one.
SameSim is shown equivalent to it within ±0.03; for Mesa, and between the
two tools, no difference is significant but equivalence isn't shown at
2,000 seeds. Mesa is 7.4× faster per agent update.**

## The model and the exact result

Synchronous voter model: at every tick, every agent picks a neighbor
uniformly at random and adopts the opinion (0 or 1) that neighbor held at
the previous tick. On a connected, non-bipartite graph, everyone eventually
agrees.

The degree-weighted fraction holding opinion 1,
M(t) = Σᵢ dᵢ xᵢ(t) / Σᵢ dᵢ, is a martingale: each agent's expected next
opinion is the mean of its neighbors', and summing dᵢ times that over all
agents gives M(t) back. So the probability that opinion 1 wins is
**M(0), its degree-weighted initial fraction, not its plain initial
fraction.**

To make the two predictions far apart, agents 0–4 start with opinion 1 on a
Barabási–Albert graph (n = 50, m = 2). Those are the oldest,
best-connected nodes: the plain fraction is 0.10, but M(0) averages 0.27.

## Setup

- 2,000 seeds. Each seed gives one graph, **shared by both tools**: SameSim's
  `BarabasiAlbertTopology` with `random.Random(seed)`, exactly as the
  experiment runner builds it, handed to Mesa as an adjacency list. M(0)
  is computed per run (it is identical in both tools for every seed).
- **SameSim:** `VoterBehavior` and `VoterMetric`, synchronous activation,
  `GossipProtocol`. Agents announce opinions at t = 0 and then only when
  they change.
- **Mesa 3.5:** the same rule as a two-stage step (every agent chooses,
  then every agent applies), seeded with `rng=seed`.
- Horizon 400 ticks. Every run in both tools reached consensus.
- **Statistics:** per run, won − M(0). Mean with a 95% CI, and TOST
  equivalence to 0 within ±0.03, a margin fixed before the run.

```bash
python run_voter.py    # ~15 min
python analyze.py      # the tables below
```

Raw output: [`voter_results.json`](voter_results.json); analysis output:
[`summary.txt`](summary.txt).

## Results

| Tool | P(opinion 1 wins) | Mean M(0) | Wins − M(0), 95% CI | ≡ M(0) within ±0.03 (TOST p) | Wins − naive 0.10, 95% CI |
|---|---:|---:|---:|---:|---:|
| SameSim | 0.267 | 0.272 | −0.005 ± 0.019 | **0.006** | +0.167 ± 0.019 |
| Mesa | 0.255 | 0.272 | −0.017 ± 0.019 | 0.097 | +0.154 ± 0.019 |

- **Both tools follow the martingale, and the naive prediction is
  decisively wrong** for both (+0.17 and +0.15, CIs far from 0).
- **SameSim is equivalent to the exact result within ±0.03.**
- **Mesa is not significantly different from it** (the CI contains 0),
  but its CI reaches −0.036, so equivalence within ±0.03 isn't shown.
- **Between the tools**, the win rates differ by +0.012, not
  significantly, and equivalence within ±0.03 isn't shown (TOST
  p = 0.097). The sample size was fixed in advance at 2,000; this result is
  inconclusive, not a failure, and more seeds would settle it.
- **Consensus time has the same distribution in both tools**: mean 43.2
  vs. 42.7 ticks, median 32 vs. 31 (two-sample KS p = 0.21).

### Throughput

Agent updates per second of run time, median and IQR over 2,000 runs, same
machine:

| Tool | Updates/s | IQR |
|---|---:|---:|
| SameSim | 139,213 | 120,986–151,600 |
| Mesa | 1,026,714 | 914,497–1,123,623 |

**Mesa is 7.4× faster.** A Mesa step is a direct method call on a Python
object that reads its neighbor's attribute. In SameSim, opinions travel as
messages through the protocol and event queue, state is immutable and
copied on change, and every change is dispatched to metrics. SameSim also
keeps stepping every agent after consensus until the horizon (its
synchronous mode has no stop condition), which this measure counts as
updates.

## What this doesn't cover yet

- The asynchronous (random sequential) voter model, which Mesa would run
  with `shuffle_do`; it needs a Poisson-clock version in SameSim's event mode.
- Cross-version and cross-platform determinism of either tool, run as its
  own study.
- A stop-on-condition feature in SameSim, so runs can end at consensus.
