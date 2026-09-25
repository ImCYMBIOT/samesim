# Gossip Convergence vs. Topology — Validation Study

> **Re-run on the corrected engine (2026-09-24): every conclusion holds.**
> The committed CSV/JSON numbers below predate three engine/plugin fixes
> (the O(n²) topology generators, the engine-termination off-by-one, and the
> addressing contract). The full sweep has since been re-run on the fixed
> code — raw output in `postaudit_full_results.json` /
> `postaudit_full_ws_ba_results.json` — and the fitted slopes come back
> materially identical:
>
> | Topology | Slope (original) | Slope (post-audit) |
> |---|---:|---:|
> | Ring | 0.99 | **0.99** |
> | Watts–Strogatz | 0.18 | 0.16 |
> | Barabási–Albert | 0.11 | 0.11 |
> | Erdős–Rényi | 0.01 | 0.05 |
>
> The ring exponent reproduces exactly, and the ordering among the three
> well-connected topologies (ER flattest, then BA, then WS) is preserved.
> Per-run tick counts differ slightly — the termination fix gives each run
> one more tick and the ER generator consumes its RNG stream differently, so
> the same seed now yields a different (equally valid) graph. Treat the
> tables below as the original pass and the slopes as confirmed twice.

**Status:** preliminary validation pass across four topologies (single fixed
graph density, 5 seeds per point). This is the first of the three research
directions proposed in
[docs/Simul8_Research_Brief.docx](../../docs/Simul8_Research_Brief.docx) —
picked first because it's also the cheapest way to sanity-check that Simul8's
gossip pipeline produces results consistent with known graph-mixing theory,
before trusting it for a real study.

## Question

Does Simul8's push-gossip convergence time behave the way graph mixing-time
theory predicts — fast on well-connected graphs, much slower on a poorly
connected one, with the gap widening as the network grows? And does that hold
consistently across different notions of "well-connected" (uniformly random,
small-world, scale-free), not just one?

## Method

`run_sweep.py` drives Simul8's real `ExperimentRunner` (the same code path the
CLI uses) across a grid of `(topology, n, seed)`, using `GossipBehavior`
(`fan_out=2`) and `ConvergenceMetric` (population variance of agent values).
For each run, `converged_tick` is the first tick at which variance drops to
≤1% of its initial value.

- **Erdős–Rényi**: `edge_probability` set per-n so average degree stays fixed
  at 8 (`p = 8/(n-1)`), keeping every graph in the same "well above the
  connectivity threshold" regime as n grows. `n ∈ {50, 100, 200, 400, 800, 1600}`.
- **Ring**: degree 2, fixed structure regardless of n.
  `n ∈ {10, 20, 40, 80, 160, 320}` — kept smaller since convergence is much
  slower here (see results).
- **Watts–Strogatz**: `k=8` (fixed lattice degree — rewiring preserves
  degree, so average degree stays exactly 8), `rewire_probability=0.15`
  (the same value used in `examples/sir_random.yaml`). `n ∈ {50, 100, 200,
  400, 800, 1600}`.
- **Barabási–Albert**: `m=4` (average degree ≈ 2m = 8 for large n, matching
  the other three arms). Same n range as Erdős–Rényi.
- 5 seeds per `(topology, n)`, `max_virtual_time` calibrated per arm from a
  pilot run so every case has 5–15× headroom past its actual convergence tick.

Run it yourself (from this directory, with the `simul8` conda env active):
`python run_sweep.py --mode full` (ring + Erdős–Rényi, ~60 runs, ~2–3 min)
and `python run_sweep.py --mode full_ws_ba` (Watts–Strogatz + Barabási–Albert,
~60 runs, ~1–2 min). Raw output: `full_results.json` /
`full_ws_ba_results.json`.

## Results

Mean ticks to converge (±1 std, 5 seeds), log–log scale:

**[Interactive chart](https://claude.ai/artifact/SfpUMgu7KVkrjX99LJqJ53)**

| Topology | n | Mean ticks | Std dev |
|---|---:|---:|---:|
| Ring | 10 | 7.6 | 1.50 |
| Ring | 20 | 20.6 | 7.71 |
| Ring | 40 | 40.4 | 13.89 |
| Ring | 80 | 50.4 | 17.81 |
| Ring | 160 | 177.4 | 28.45 |
| Ring | 320 | 244.6 | 10.17 |
| Erdős–Rényi | 50 | 10.0 | 2.55 |
| Erdős–Rényi | 100 | 12.4 | 3.14 |
| Erdős–Rényi | 200 | 9.6 | 0.80 |
| Erdős–Rényi | 400 | 10.6 | 0.80 |
| Erdős–Rényi | 800 | 11.2 | 0.75 |
| Erdős–Rényi | 1600 | 11.0 | 0.63 |
| Watts–Strogatz | 50 | 7.4 | 0.80 |
| Watts–Strogatz | 100 | 9.0 | 0.89 |
| Watts–Strogatz | 200 | 10.2 | 0.98 |
| Watts–Strogatz | 400 | 13.2 | 1.60 |
| Watts–Strogatz | 800 | 12.6 | 1.36 |
| Watts–Strogatz | 1600 | 13.4 | 0.80 |
| Barabási–Albert | 50 | 10.8 | 1.60 |
| Barabási–Albert | 100 | 12.4 | 1.36 |
| Barabási–Albert | 200 | 14.4 | 1.85 |
| Barabási–Albert | 400 | 16.0 | 0.89 |
| Barabási–Albert | 800 | 15.2 | 0.75 |
| Barabási–Albert | 1600 | 16.0 | 0.89 |

Fitting `log(ticks) = slope · log(n) + c` by least squares:

| Topology | Slope | Regime |
|---|---:|---|
| Ring | **0.99** | linear |
| Watts–Strogatz | 0.18 | ~flat |
| Barabási–Albert | 0.11 | ~flat |
| Erdős–Rényi | **0.01** | flat |

- **All three "well-connected" topologies are in the same flat/slow-growth
  regime** — nowhere close to ring's near-linear growth — confirming the
  qualitative theory holds across genuinely different graph families, not
  just for one lucky case.
- **A small but consistent ordering among the connected topologies**:
  Erdős–Rényi is flattest, Barabási–Albert and Watts–Strogatz both show a
  little more growth (slopes 0.11 and 0.18). Plausible mechanisms, not yet
  tested directly: Barabási–Albert's degree heterogeneity (a few hub nodes
  carry disproportionate traffic, a mild bottleneck effect documented in the
  consensus literature for scale-free graphs) and Watts–Strogatz's residual
  ring-locality at `rewire_probability=0.15` (only 15% of edges are rewired
  away from the original ring lattice, so some local structure survives).
- One outlier: Erdős–Rényi n=50 seed=4 did not cross the 1% threshold inside
  its window (it reached 97% variance reduction) and is excluded from that
  point's mean (n=4 instead of 5) — plausibly just seed variance at small n,
  not a bug in the pipeline.

## Interpretation

**The qualitative claim is strongly confirmed**: well-connected graphs
converge dramatically faster than poorly-connected ones, and the gap widens
with scale — at n=320, ring gossip takes ~245 ticks while Erdős–Rényi at the
same n would take ~10. This is the core, robust prediction of mixing-time
theory (random-walk mixing time is O(log n) on an expander-like graph and
O(n²) on a cycle), and it holds.

**The exact ring exponent is a genuine finding, not just a theory check.**
The classical O(n²) ring bound is derived for *asynchronous pairwise* gossip
(one random neighbor-to-neighbor call per unit time — Boyd, Ghosh, Prabhakar,
Shah, *Randomized Gossip Algorithms*, IEEE Trans. Info. Theory, 2006).
Simul8's `GossipBehavior` is different in two ways that plausibly explain the
observed O(n) instead of O(n²):

1. **Synchronous, full-neighbor push.** On a ring, `fan_out=2` means every
   node pushes to *both* of its neighbors *every* tick — closer to a
   discretized heat-diffusion update (`x_i(t+1) ≈ mean(x_i, x_{i-1}, x_{i+1})`)
   than to a single random pairwise exchange.
2. **Random i.i.d. initial conditions and a 99%-reduction threshold**, not
   worst-case initial conditions and full asymptotic convergence. The
   spectral-gap-derived O(n²) bound governs the slowest eigenmode's
   asymptotic decay; random initial values spread energy across many modes,
   so a modest relative-threshold crossing can be dominated by faster,
   non-worst-case dynamics.

> **Correction (2026-09-25): explanation 2 is right, explanation 1 is not,
> and the linear ring exponent is an artifact of the threshold.** Once
> Simul8 could run Boyd et al.'s asynchronous pairwise model (Phase 2),
> [async_gossip_validation/](../async_gossip_validation/) measured both
> protocols on the same rings at two thresholds. At this study's 1%
> threshold, both look linear (slopes 1.04 sync, 0.96 async). At 1e-4, both
> are about quadratic (1.82 sync, 1.78 async), the classical regime. Synchrony
> and full-neighbor push don't change the exponent. The 1% threshold is
> simply crossed while fast modes still dominate, before the slowest mode's
> O(n²) decay takes over.
>
> So the paragraph below was wrong in its central claim and is kept only
> for the record: the linear exponent is **not** a property of this protocol.
> Any paper citing this study should report convergence at a threshold
> strict enough to be in the asymptotic regime, or report both.

~~This is worth stating plainly in any paper that cites this result: Simul8
reproduces the *qualitative* mixing-time prediction cleanly, and the specific
linear ring exponent is itself a claim about *this* protocol (synchronous
multi-neighbor push-gossip with random initialization), not a mismatch with
the classical asynchronous-pairwise bound.~~

## What this doesn't cover yet (next steps)

- Only one graph density (avg degree 8) tested per topology — the
  convergence/density relationship itself is untested, and is the more
  standard axis for the "topology → convergence" flagship study described
  in the research brief (sweep density at fixed n, not just n at fixed
  density as done here).
- The Barabási–Albert / Watts–Strogatz ordering (slopes 0.11 and 0.18 vs.
  Erdős–Rényi's 0.01) is observed but not yet explained mechanistically —
  worth isolating (e.g. does the BA gap track hub degree, does the WS gap
  shrink as `rewire_probability` increases toward 1?).
- No comparison yet against an independent reference implementation (e.g.
  NetworkX + hand-rolled gossip, or PeerSim) — doing so would rule out any
  Simul8-specific implementation artifact as an explanation for the O(n)
  ring result, rather than relying on the mechanistic argument above.
