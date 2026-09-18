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
   (average degree 8), n = 100 to 100,000. This measures the realistic
   full pipeline most experiments actually use.
3. **`naive_gossip.py`** — a deliberately bare-bones reference
   implementation of the identical push-gossip protocol (same per-agent RNG
   scheme, same topology, same per-tick work) with none of Simul8's event
   queue, dataclass events, ports, or metrics pipeline — just plain Python
   lists and a for-loop. Compared against Simul8 on Ring topology (again to
   avoid the O(n²) confound) to isolate what the clean architecture costs in
   raw speed.

Run them yourself (from this directory, `simul8` conda env active):
`python run_scaling_ring.py`, `python run_scaling.py`,
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

## Result 2 — found and fixed: `ErdosRenyiTopology` was O(n²)

The first pass of this benchmark caught a real bug in the running: local
slope on Erdős–Rényi climbed from 0.89 (small n) to 1.37 (n=10,000→30,000)
— visibly bending toward quadratic, not staying flat like Ring did. The
cause was in the code, not mysterious:
[`ErdosRenyiTopology.generate()`](../../simul8/plugins/topologies/random_graph.py)
checked **every possible pair** of agents (`for i in range(n): for j in
range(i+1, n)`) regardless of `edge_probability` — O(n²) time no matter how
sparse the resulting graph was. At n=30,000 that's ~450 million pair-checks.

**Fixed** using the Batagelj–Brandes algorithm (*"Efficient generation of
large random networks"*, 2005): since each pair is an independent
Bernoulli(p) trial, the gap between consecutive edges follows a geometric
distribution, so the generator can jump straight to the next edge instead of
rejection-sampling every pair — O(n + m) where m is the actual edge count.
Verified: same statistical properties (avg degree 7.99 vs. expected 8.0 at
n=30,000, symmetric, all agents present — see the added cases in
`tests/unit/plugins/test_topologies.py`), topology generation for n=30,000
dropped from being the dominant cost to **0.17s** standalone, and n=100,000
— previously estimated at 20+ minutes just for topology generation — now
takes **0.82s**.

This was a deliberate tradeoff, not a free fix: the new algorithm consumes
the RNG stream differently than the old pair-by-pair version, so **the same
seed now produces a different (but equally valid) Erdős–Rényi graph than it
did before**. Bit-for-bit reproducibility of already-committed results
(`results/`, both prior `experiments/` studies) is broken by this change,
even though the statistical conclusions in those studies remain valid.
`design_manifesto.txt` states reproducibility matters more than raw
performance — this change was made anyway, deliberately, because it fixes
an asymptotic complexity bug rather than trading away determinism itself
(same seed still always produces the same graph, going forward).

With the fix in place, the full n=100–100,000 range now stays in the same
regime as Ring — local slope 0.98 to 1.25, no runaway growth:

| n range | Ring slope | ER slope |
|---|---:|---:|
| 100 → 300 | 0.96 | 0.98 |
| 300 → 1,000 | 1.06 | 1.10 |
| 1,000 → 3,000 | 1.11 | 1.22 |
| 3,000 → 10,000 | 1.13 | 1.24 |
| 10,000 → 30,000 | 1.09 | 1.25 |
| 30,000 → 100,000 | 1.06 | 1.09 |

## Result 3 — a second, smaller finding: degree still costs something, just not asymptotically

Even after the fix, Erdős–Rényi is consistently ~2× slower than Ring at
matched n (324s vs. 163s at n=100,000), despite virtually identical event
counts (9.78M vs. 9.80M). Two plausible explanations were directly tested
and ruled out: a microbenchmark of `sorted(neighbors)` + `rng.sample(...)`
showed no measurable difference between degree-2 and degree-8 neighbor sets
(1.236 vs. 1.239 µs/call), and peak memory is nearly identical between the
two topologies (1,988.8 MB vs. 1,939.8 MB at n=100,000), ruling out a
GC/memory-pressure explanation. A `cProfile` pass pinned it down precisely:
`GossipBehavior.step()`'s own execution time (not the engine — event
dispatch, heap operations, and metrics costs are nearly identical between
the two) is about 50% higher on Erdős–Rényi for the same call count. Most
plausible remaining cause — larger, more variable inbox lists at average
degree 8 vs. Ring's fixed degree 2 — is flagged but not yet isolated
further; this is a real, bounded (not compounding) cost, not another
quadratic bug.

## Result 4 — architecture overhead is real, and roughly constant

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
- The Erdős–Rényi vs. Ring per-tick cost gap (Result 3) is diagnosed down to
  the specific function but not down to the specific line — a next pass
  could compare inbox-size distributions directly rather than inferring
  from profiler output.
- Only gossip was benchmarked for performance; leader election and SIR have
  correctness regression coverage (`tests/regression/`) but no dedicated
  performance sweep.
- The `gossip_topology_validation/` study's committed results predate this
  fix and used the old O(n²) `ErdosRenyiTopology` — their statistical
  conclusions (flat convergence time on ER/WS/BA vs. linear on Ring) aren't
  affected, since that study never depended on generation speed, but a
  from-scratch rerun would now produce different exact CSV values for the
  same seeds.
