# M/M/1 queue: Simul8 vs. SimPy vs. the closed forms

The standard check for a discrete-event simulator: an M/M/1 queue, whose
mean wait, time in system and number in system are known exactly, run in
Simul8 and in [SimPy](https://simpy.readthedocs.io), the general-purpose
Python DES library, with identical parameters. It exercises Simul8's
event-driven core end to end: Poisson timers, message delivery with
latency, agent wakes and FIFO bookkeeping.

**Result: both tools match the closed forms within ±3% at every load, and
match each other except one borderline cell. SimPy is 5× faster.**

## Setup

- Poisson arrivals at rate λ = ρ, one server with exponential service at
  rate μ = 1, FIFO. ρ ∈ {0.5, 0.8, 0.9}.
- **Simul8:** `QueueBehavior`, one source agent sending customers to one
  server agent as messages with constant latency 0.001 (which shifts every
  arrival equally, so arrivals stay Poisson), event activation,
  `QueueMetric`.
- **SimPy:** the textbook model, with a source process and a `Resource` of
  capacity 1 held for an exponential time.
- Horizon 50,000 time units; the first 5,000 are discarded as warm-up.
  100 seeds per ρ per tool.
- Per run: mean wait in queue Wq and time in system W of customers arriving
  after the warm-up, and the time-average number in system L over the
  measurement window.
- Closed forms: Wq = ρ/(μ − λ), W = 1/(μ − λ), L = ρ/(1 − ρ).
- **Statistics:** mean over seeds with a 95% CI. TOST equivalence within
  ±3% of the closed form, a margin fixed before the first run.

```bash
python run_mm1.py      # ~20 min
python analyze.py      # the tables below
```

Raw output: [`mm1_results.json`](mm1_results.json); analysis output:
[`summary.txt`](summary.txt).

## Results

| ρ | Metric | Closed form | Simul8 | SimPy | Simul8 ≡ theory (TOST p) | SimPy ≡ theory (TOST p) | Simul8 ≡ SimPy (TOST p) |
|---:|---|---:|---:|---:|---:|---:|---:|
| 0.5 | Wq | 1.000 | 1.002 ± 0.007 | 1.000 ± 0.007 | 6×10⁻¹² | 1×10⁻¹⁴ | 3×10⁻⁸ |
| 0.5 | W | 2.000 | 2.004 ± 0.008 | 2.000 ± 0.007 | 1×10⁻²⁵ | 1×10⁻²⁹ | 2×10⁻²⁰ |
| 0.5 | L | 1.000 | 1.002 ± 0.005 | 1.000 ± 0.004 | 7×10⁻²¹ | 4×10⁻²⁶ | 3×10⁻¹⁶ |
| 0.8 | Wq | 4.000 | 4.012 ± 0.051 | 4.047 ± 0.048 | 3×10⁻⁵ | 0.002 | 0.009 |
| 0.8 | W | 5.000 | 5.013 ± 0.052 | 5.048 ± 0.049 | 5×10⁻⁷ | 4×10⁻⁵ | 8×10⁻⁴ |
| 0.8 | L | 4.000 | 4.010 ± 0.044 | 4.044 ± 0.042 | 2×10⁻⁶ | 2×10⁻⁴ | 0.003 |
| 0.9 | Wq | 9.000 | 9.012 ± 0.208 | 9.047 ± 0.193 | 0.008 | 0.012 | 0.051 |
| 0.9 | W | 10.000 | 10.013 ± 0.208 | 10.047 ± 0.193 | 0.004 | 0.005 | 0.032 |
| 0.9 | L | 9.000 | 9.014 ± 0.193 | 9.050 ± 0.180 | 0.005 | 0.009 | 0.040 |

- **Both tools are equivalent to the closed forms within ±3%** for every
  load and metric.
- **Simul8 and SimPy are equivalent within ±3%** everywhere except Wq at
  ρ = 0.9, where it is borderline (p = 0.051). Neither differs from the
  other or from theory significantly anywhere: every CI contains the
  closed form.
- Little's law holds, as it must: L ≈ λW in every row.

### Exact, not just statistical: Lindley's recursion

Averages can hide a bug that happens to cancel out. For a FIFO single
server each customer's wait follows from the draws alone (Lindley, 1952):
W₁ = 0, Wₙ₊₁ = max(0, Wₙ + Sₙ − Aₙ₊₁).
`tests/integration/test_queue_lindley.py` replays the exact random streams
Simul8's source and server consume through this recursion and requires
**every one of ~4,500 recorded waits to match to 10⁻⁹**. It does. Making
the queue LIFO, or restarting service when a customer arrives at a busy
server, fails it.

### Throughput

Customers completed per second of run time (the simulation loop itself,
including Simul8's metric collection and SimPy's equivalent bookkeeping),
median and IQR over 100 runs, same machine:

| ρ | Simul8 | SimPy | SimPy / Simul8 |
|---:|---:|---:|---:|
| 0.5 | 19,381 (18,947–19,806) | 97,968 (94,873–99,674) | 5.1× |
| 0.8 | 18,980 (18,656–19,196) | 95,945 (93,698–96,989) | 5.1× |
| 0.9 | 19,127 (18,799–19,275) | 95,641 (94,143–96,517) | 5.0× |

A profile of a Simul8 run shows no single hotspot; the cost is spread
across what the architecture does per customer:
- Each customer is 4 scheduled events: arrival timer, message delivery,
  agent wake, departure timer. SimPy uses 2–3 generator resumptions.
- About 7 events per customer are dispatched to metrics.
- Agent state is immutable, so each update copies it (about 8 copies per
  customer).
- `portable_math` (platform-independent `log`) accounts for about 3%.

Simul8 trades this speed for a message-level model of agents, a
metric pipeline that never sees agent internals, and bit-identical runs on
every OS and Python version. SimPy's model is a process interaction on one
machine with the platform's `random.expovariate`.

## History

The first full run used 20 seeds. At ρ = 0.9 it gave Simul8 Wq = 8.36 ±
0.36, a CI excluding 9.0, while SimPy matched. 100 fresh seeds gave
9.25 ± 0.21: the first 20 had been a low draw. At ρ = 0.9 per-run means
are strongly right-skewed (rare long congestion episodes), so a small
sample tends to come out low, and a t-interval under-covers. Before
concluding it was noise, the Lindley test above was written to rule out a
bug exactly. The study now uses 100 seeds per point; the ±3% margin is
unchanged.

## What this doesn't cover yet

- Only M/M/1. M/M/c, networks of queues (Jackson networks) and other
  service distributions would need more plugins.
- Ciw, a queueing-network simulator, would be a second independent tool.
- Throughput was measured on one machine; absolute numbers vary with
  hardware, the ratio less so.
