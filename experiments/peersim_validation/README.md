# Push-pull gossip averaging: SameSim vs. PeerSim vs. Jelasity's closed form

Push-pull averaging in SameSim and in [PeerSim](https://peersim.sourceforge.net),
the standard peer-to-peer simulator, on identical graphs, checked against
the closed form of Jelasity, Montresor and Babaoglu (ACM TOCS 2005).

**Result: on the complete graph, both tools are equivalent to the closed
form within ±0.01, and to each other. On a sparse graph, where there is no
closed form, they are equivalent to each other. PeerSim is 9–91× faster,
and the gap grows with network size.**

## The model and the closed form

Each node holds a value, drawn uniformly from [0, 1]. In every cycle, each
node, in a random order, picks a random neighbor, and the two replace their
values with the average of both. The mean never changes; the variance
shrinks. On a complete graph, it shrinks by a factor of
**1/(2√e) ≈ 0.3033 per cycle** in expectation (Jelasity et al. 2005).

## Setup

- **Identical graph per seed.** SameSim's topology generator builds it with
  `random.Random(seed)`, exactly as the experiment runner does, and PeerSim
  loads it with `WireFromFile`.
- **SameSim:** `AsyncGossipBehavior` with `schedule: cycle`. Each agent
  exchanges once per unit of time, at a uniformly random point in it, so
  each cycle runs in a random order. Event activation; `LatencyProtocol`
  with a constant delay of 10⁻⁷, far below the 1/n average gap between
  agents, so each exchange completes before the next one starts.
  `ConvergenceMetric` records the variance.
- **PeerSim 1.0.5, unmodified:** `example.aggregation.AverageFunction` with
  `Shuffle`, `UniformDistribution` and `AverageObserver`. The script
  downloads it and checks its SHA-256.
- **Correctness:** n = 1,000, 15 cycles, 50 seeds per tool, on a complete
  graph and on an Erdős–Rényi graph with average degree 20.
- **Statistics:** per run, the geometric mean of the per-cycle variance
  ratio. Mean with a 95% CI; TOST equivalence within ±0.01, a margin fixed
  before the run.
- **Speed:** Erdős–Rényi, average degree 20, 20 cycles, n = 10³, 10⁴, 10⁵,
  3 runs per tool, median wall time.

```bash
JAVA=$(conda run -n peersim which java) python run_peersim.py    # ~15 min
python analyze.py                                                  # the tables below
```

Raw output: [`peersim_results.json`](peersim_results.json); analysis output:
[`summary.txt`](summary.txt).

## Results

Per-cycle variance reduction factor, mean ± 95% CI over 50 seeds:

| Graph | SameSim | PeerSim | SameSim ≡ theory (TOST p) | PeerSim ≡ theory (TOST p) | SameSim ≡ PeerSim (TOST p) |
|---|---:|---:|---:|---:|---:|
| Complete, n = 1,000 | 0.3026 ± 0.0010 | 0.3022 ± 0.0011 | 5.5 × 10⁻²⁵ | 3.7 × 10⁻²² | 7.6 × 10⁻²⁴ |
| Erdős–Rényi, degree 20, n = 1,000 | 0.3360 ± 0.0013 | 0.3367 ± 0.0015 | – | – | 2.3 × 10⁻¹⁶ |

- **Both tools match the closed form, 0.3033.** Its value falls inside
  SameSim's CI and on the edge of PeerSim's. Both are equivalent to it
  within ±0.01.
- **The tools agree on the sparse graph too.** Averaging is slower there
  (0.336 per cycle), as expected with fewer neighbors to mix with, and
  both tools show the same slowdown.

### Speed

Wall time per run, median of 3. PeerSim's is the whole JVM process,
startup included.

| n | PeerSim | SameSim | SameSim / PeerSim | SameSim exchanges/s | PeerSim exchanges/s |
|---:|---:|---:|---:|---:|---:|
| 1,000 | 0.13 s | 1.21 s | 9× | 16,959 | 148,599 |
| 10,000 | 0.34 s | 14.54 s | 42× | 14,087 | 583,524 |
| 100,000 | 1.91 s | 173.81 s | 91× | 11,836 | 1,046,803 |

**PeerSim is much faster, and the gap grows with n.** That growth is
mostly PeerSim's: JVM startup dominates its small runs, so its throughput
rises 7× from n = 10³ to 10⁵, while SameSim's falls by 30%. The two do
different amounts of work per exchange:

- PeerSim's cycle-driven engine is a compiled loop. An exchange is a
  method call that reads and writes the neighbor's field directly.
- In SameSim, an exchange is a timer event plus a request and a reply,
  each a message through the protocol and the event queue, with latency,
  immutable state and metric dispatch.

That is the price of what PeerSim's cycle mode leaves out: message
latency, asynchronous clocks, churn and loss, and bit-identical results
across operating systems and Python versions (see
[`../determinism_survey/`](../determinism_survey/)). PeerSim's
event-driven mode covers some of these, and was not compared here.

## What this doesn't cover yet

- PeerSim's event-driven engine, against SameSim's Poisson-clock schedule.
- Churn and message loss, which both tools can model, with no closed form
  to check against.
