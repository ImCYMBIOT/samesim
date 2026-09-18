# Scaling & Performance Benchmark

**Status:** first performance-validation pass, alongside the correctness
validation in [experiments/gossip_topology_validation/](../gossip_topology_validation/).
That study asked "does Simul8 produce trustworthy numbers?" — this one asks
"can it actually run at scale, and what does the clean architecture cost?"

**[Interactive chart](https://claude.ai/artifact/Wmy1hyBGx2rcxe23uxFnP4)**

## What was measured

Three things, each isolating a different question:

1. **`run_scaling_ring.py`** — wall-clock time, throughput, and peak memory
   for a fixed-tick (50 ticks, no early stopping) gossip experiment at
   n = 100 to 100,000 agents, on **Ring** topology. Ring is deliberately
   chosen because `RingTopology.generate()` is O(n) — this isolates the
   *engine's own* scaling behavior from any one plugin's cost.
2. **`run_scaling.py`** — the same sweep on **Erdős–Rényi** topology
   (average degree 8), capped at n = 30,000. This measures the realistic
   full pipeline most experiments actually use.
3. **`naive_gossip.py`** — a deliberately bare-bones reference
   implementation of the identical push-gossip protocol (same per-agent RNG
   scheme, same topology, same per-tick work) with none of Simul8's event
   queue, dataclass events, ports, or metrics pipeline — just plain Python
   lists and a for-loop. Compared against Simul8 on Ring topology (again to
   avoid the O(n²) confound) to isolate what the clean architecture costs in
   raw speed.

Run them yourself (from this directory, `simul8` conda env active):
`python run_scaling_ring.py`, `python run_scaling.py --ns 100,300,1000,3000,10000,30000`,
`python naive_gossip.py --ns 100,1000,10000,100000`.

## Result 1 — the engine itself scales linearly

Fitting local (segment-to-segment) log-log slopes on Ring topology:

| n range | local slope |
|---|---:|
| 100 → 300 | 0.96 |
| 300 → 1,000 | 1.06 |
| 1,000 → 3,000 | 1.11 |
| 3,000 → 10,000 | 1.13 |
| 10,000 → 30,000 | 1.09 |
| 30,000 → 100,000 | 1.06 |

Consistently ~1.0–1.13 across three orders of magnitude of n — genuinely
linear, not something that degrades as the simulation grows. 100,000 agents
for 50 ticks (9.8M events) completed in 163 seconds at ~60,000 events/sec,
using ~1.9 GB peak memory (also roughly linear in n — see the full table in
the chart).

## Result 2 — an honest limitation: `ErdosRenyiTopology` is O(n²)

The same sweep on Erdős–Rényi shows local slope climbing from 0.89 (small n,
dominated by fixed overhead) to 1.37 (at n=10,000→30,000) — visibly bending
toward quadratic, not staying flat like Ring did. The cause is in the code,
not mysterious: [`simul8/plugins/topologies/random_graph.py`](../../simul8/plugins/topologies/random_graph.py)
checks **every possible pair** of agents (`for i in range(n): for j in
range(i+1, n)`) regardless of `edge_probability` — O(n²) time no matter how
sparse the resulting graph is. At n=30,000 that's ~450 million pair-checks,
and it already dominates total runtime (100.4s total vs. Ring's 45.7s at the
same n, despite doing *less* topology-relevant work per agent since Ring is
degree-2 and ER here is degree-8).

This is a real, fixable limitation, not a fundamental one: the standard fix
for generating sparse Erdős–Rényi graphs is to sample the *number* of edges
directly (or use the fact that inter-edge gaps follow a geometric
distribution) and only iterate over edges that actually get created — O(n +
m) instead of O(n²), where m is the edge count. Worth a follow-up PR before
running any topology-validation-style sweep past roughly n=30,000–50,000 on
Erdős–Rényi. n=100,000 on this topology was not run — extrapolating the
observed trend, that single data point would take on the order of 20+
minutes by itself, which is why it's reported as a bounded estimate rather
than a measurement.

## Result 3 — architecture overhead is real, and roughly constant

| n | naive (bare loop) | Simul8 (full engine) | ratio |
|---:|---:|---:|---:|
| 100 | 0.018s | 0.101s | 5.6× |
| 1,000 | 0.144s | 1.039s | 7.2× |
| 10,000 | 1.673s | 13.759s | 8.2× |
| 100,000 | 20.338s | 163.357s | 8.0× |

The event queue (heap operations, O(log n) per event), frozen dataclass
event objects, port indirection, and the metrics-dispatch pipeline cost
roughly an **order of magnitude in raw throughput** versus the simplest
possible equivalent script. The ratio climbs slightly then **plateaus around
8×** — it's a roughly constant multiplier, not a tax that compounds with
scale. That's the honest price of determinism (§3 of
[the Simul8 explainer](https://claude.ai/artifact/5LqUn79Xu9AgHtnZ16PkiW)),
reproducibility, and a plugin architecture that can't be broken by a bad
research idea — and it's worth being able to state precisely rather than
either hiding it or overselling raw speed.

## What this doesn't cover yet

- No comparison against an existing simulation tool (PeerSim, Mesa) at
  matched scale — same gap flagged in the topology validation study.
- The O(n²) `ErdosRenyiTopology` fix described above hasn't been
  implemented; this benchmark only diagnosed it.
- Only gossip was benchmarked for performance; leader election and SIR have
  correctness regression coverage (`tests/regression/`) but no dedicated
  performance sweep.
