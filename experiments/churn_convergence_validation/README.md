# Gossip convergence under churn

The Phase 3 validation target of [docs/design.md](../../docs/design.md): does
gossip convergence degrade gracefully as agents fail and recover more often,
or is there a cliff?

**Answer: among running agents, gracefully.** Convergence time grows as a
smooth power of the fraction of agents that are up, with no threshold, and
doubles only when half the agents are down. **Agreement across *every*
agent, crashed ones included, is a different quantity.** With long
downtimes it is set by how long the agents that crashed early stay down,
not by the churn rate, and a simple stale-value model predicts it.

## Setup

- Push gossip (`GossipBehavior`, fan-out 2), synchronous, lossless
  `GossipProtocol`. Erdős–Rényi, n = 200, average degree 8. 400 ticks.
- `RandomChurn`: each running agent fails at rate λ, each failed one
  recovers at rate μ = 1/D. Long-run down fraction f = λ/(λ+μ).
- f ∈ {0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5}, mean downtime D ∈ {5, 50}
  ticks, 10 seeds each: 150 runs. f = 0 is a single shared baseline.
- A crashed agent keeps its value and rejoins with it
  (see the [User Guide](../../docs/user_guide.md#6-churn-failures-recoveries-joins-rewiring)).

Measured with `ConsensusMetric`, added for this study:

| Series | Meaning |
|---|---|
| running variance | variance of `value` among agents that are up |
| all variance | variance among all agents, crashed ones at their frozen value |
| drift | consensus mean minus the true initial mean, in units of the initial σ |

Times are the first tick a variance falls to 10⁻² or 10⁻⁴ of its initial
value, as medians over seeds.

## Results

### Running agents: graceful

| f | D = 5: t(10⁻⁴) | slowdown | D = 50: t(10⁻⁴) | slowdown |
|---:|---:|---:|---:|---:|
| 0 | 29.5 | 1.00 | 29.5 | 1.00 |
| 0.05 | 33 | 1.12 | 29.5 | 1.00 |
| 0.1 | 36 | 1.22 | 30.5 | 1.03 |
| 0.2 | 41 | 1.39 | 32 | 1.08 |
| 0.3 | 49.5 | 1.68 | 34 | 1.15 |
| 0.5 | 83.5 | 2.83 | 62 | 2.10 |

Fitted: t ∝ (1 − f)^−1.48 for D = 5 and (1 − f)^−1.00 for D = 50. No cliff
anywhere in the range: every run at every churn level converged.

Short outages cost more than long ones at the same down fraction. With
D = 5 the set of running agents turns over fast: agents keep dropping out
mid-exchange and rejoining with values from a few ticks ago. With D = 50
the same fraction is down, but it is a more stable subset, and the running
agents behave like a smaller, slightly sparser network.

### All agents: set by downtime, not churn rate

| f | D = 5: t(10⁻⁴) | D = 50: t(10⁻⁴) (IQR) | stale-agent model |
|---:|---:|---:|---:|
| 0 | 29.5 | 29.5 | – |
| 0.01 | 29.5 | 32 (29–49) | 29.5 |
| 0.05 | 33.5 | 56.5 (30–103) | 61.6 |
| 0.1 | 38.5 | 105 (38–166) | 99.4 |
| 0.2 | 43 | 137 (97–169) | 139.0 |
| 0.3 | 61.5 | 123.5 (107–199) | 164.8 |
| 0.5 | 103.5 | 228 (211–235; 2 of 10 never) | 205.4 |

With D = 50 and f = 0.1, the running agents agree by tick 30, but the whole
system takes until tick 105.

**Why.** An agent that crashes while values are still spread out keeps a
value far from the eventual consensus. One such agent is enough to hold
the all-agent variance above 10⁻⁴ of its initial value, since a single
value off by σ₀ contributes σ₀²/200 = 5×10⁻³ of the initial variance. An
agent that crashes after about tick 10 is already within ~0.1σ₀ of
consensus and doesn't matter. So whole-system agreement waits for the last
agent that crashed before tick ~10 to come back.

**Model.** Crashes before t* are Poisson with rate λ per agent, and
downtimes are exponential with mean D. Agreement comes at max(churn-free
time, last such recovery + 2). t* = 10 is the churn-free time to reach
10⁻² of the initial variance; it is **not** fitted. The model matches the
observed medians within 10% for D = 50 up to f = 0.2, and is 10% low at
f = 0.5 (205 vs 228). It overpredicts f = 0.3 (165 vs 123.5), although 165 is inside
the observed interquartile range; with 10 seeds that point is unresolved.
It doesn't apply to D = 5, where outages are too short to matter and the
running-agent slowdown dominates instead.

The practical reading: **under churn, "has the system converged?" depends
on whether you count crashed nodes.** For them, the answer is governed by
the tail of the downtime distribution.

Once the all-agent variance falls below 10⁻⁴ it stays there in 145 of 150
runs: churn after convergence reinjects values that are already close.

### Accuracy: churn doesn't bias the consensus

| | median \|drift\| (in σ₀) |
|---|---:|
| no churn | 0.033 |
| D = 5, any f | 0.031–0.038 |
| D = 50, any f | 0.018–0.034 |

Push gossip isn't mass-conserving (an agent averages its own value with
whatever arrives), so the consensus drifts about 0.03σ₀ from the true mean
even without churn. Churn doesn't add to it.

### Lost messages match the closed form

Each tick, (1 − f)·n agents each send k = 2 messages, and a fraction f go
to crashed agents, so about f(1 − f)·n·k·T are lost over T ticks. Using the
observed time-averaged f, the median count matches within 4% in
every cell except the sparsest (D = 50, f = 0.01: 1,214 vs 1,360, where
only a handful of failures happen). The observed f is below target for
D = 50 because `RandomChurn` starts with every agent up and takes about D
ticks to reach its stationary fraction.

## Reproduce

```bash
python experiments/churn_convergence_validation/run_churn_sweep.py   # ~5 min, resumable
python experiments/churn_convergence_validation/analyze.py           # tables + model
```

Raw per-run results: [`churn_results.json`](churn_results.json). Analysis
output: [`summary.txt`](summary.txt).

## Limits

- One graph family and size (Erdős–Rényi, n = 200), one protocol (push
  gossip). Pairwise asynchronous gossip conserves the sum and may behave
  differently, especially for drift.
- Exponential downtimes only. Heavier-tailed downtimes should make
  whole-system agreement much slower, if the stale-agent explanation is
  right. That is a direct test of it, not yet run.
- Crashed agents keep their state. Agents that restart from a fresh value
  would be a different, harder case.
