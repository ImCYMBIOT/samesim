# External Validation — 5 Independent Cross-Checks

**Status:** first pass. Complements
[experiments/gossip_topology_validation/](../gossip_topology_validation/)
(validates against mixing-time *theory*) and
[experiments/scaling_benchmark/](../scaling_benchmark/) (validates
*performance*) with the piece neither of those can catch: comparison
against tools and math that share **no code** with SameSim. This is exactly
the kind of check that catches an implementation bug hiding behind
plausible-looking, theory-consistent numbers — and it did, twice.

## Why external validation, not more internal theory-checking

The topology validation study confirms SameSim's *scaling behavior* matches
mixing-time theory. It would not have caught a bug that inflates every
agent's infection probability by a roughly-constant factor — the epidemic
would still rise, peak, and burn out in the right *shape*, just at the
wrong *magnitude*, and nothing in that study's checks would flag it. That
gap is exactly what this suite is for: put SameSim next to something that
implements the same math independently, on the identical input, and see if
the numbers actually agree.

## The five checks

| # | Script | Compared against | Result |
|---|---|---|---|
| 1 | `sir_vs_ndlib.py` | [NDlib](https://ndlib.readthedocs.io) (independent epidemiology-on-networks library), plus a transcribed reference | **Found two real bugs** (double fan-out; correlated seeds) — see below. Now equivalent within ±1% to the reference |
| 2 | `gossip_vs_reference.py` | A numpy-based reference gossip implementation, written from the algorithm's spec | Equivalent within ±0.5 tick over 200 seeds (10.91 vs. 10.89, TOST p = 0.001). The old 1-tick gap was an indexing off-by-one in the reference |
| 3 | `topology_vs_networkx.py` | NetworkX's equivalent generators, for all 5 topologies | Near-exact match on every structural statistic |
| 4 | `leader_election_vs_diameter.py` | Graph diameter (computed via NetworkX) — an analytical bound, not another simulator | 15/15 cases within the theoretical bound |
| 5 | `event_count_vs_closed_form.py` | Exact combinatorial arithmetic (`n × fan_out × ticks`) | **Also caught a real bug** — see below |

Run any of them (from this directory, `samesim` conda env active, with
`pip install networkx ndlib six` for the SIR check specifically):
`python sir_vs_ndlib.py`, `python gossip_vs_reference.py`,
`python topology_vs_networkx.py`, `python leader_election_vs_diameter.py`,
`python event_count_vs_closed_form.py`.

`samesim_harness.py` is shared infrastructure: it wires SameSim's real core
(same code path as `ExperimentRunner`) but accepts a pre-built
`TopologyGraph` — usually converted directly from a NetworkX graph — so
SameSim and the comparison tool run on the **exact same graph object**,
not two separately generated graphs that are merely statistically similar.

## Bug 1 — SIR double fan-out (found by check #1, confirmed by check #5's method)

`SirEpidemicBehavior` addressed one outbound message per neighbor when
infected — correct for a pass-through protocol like `GossipProtocol`, but
it's paired with `BroadcastProtocol`, which *also* fans each message out to
every neighbor of the sender (ignoring the message's addressed recipient).
The combination double-fanned-out: a degree-*d* infected agent delivered
*d* copies to each neighbor instead of 1, inflating the effective
transmission rate far above the configured `beta`.

First signal: peak infection count was **~28% higher** in SameSim than in
20 matched NDlib runs on the identical graph — completely disjoint
distributions (SameSim `[457, 472]` vs. NDlib `[353, 378]`), not seed noise.
Confirmed precisely by tracing delivery counts on a 4-agent star: a
degree-3 infected agent was delivering **3 copies to each neighbor**
instead of 1.

**Fixed** in `samesim/plugins/behaviors/sir_behavior.py`: send exactly one
message when infected and let the protocol handle fan-out, matching how
`BroadcastProtocol` is documented to be used. Re-ran the same 20-seed
comparison after the fix: peak infection mean **362.0 (NDlib) vs. 368.3
(SameSim)**, standard deviations 7.2 vs. 6.9, ranges now heavily
overlapping. Locked in with
`tests/unit/plugins/test_sir_broadcast_fanout.py`.

## The residual gap, resolved: correlated seeds (2026-09-28)

That "~1.7%" was reported here as a small residual, "plausibly a one-tick
convention difference". An outside review recomputed it from the raw JSON:
Welch t = 2.82, p = 0.008 -- a detectable difference, not a match. Reading
NDlib's `SIRModel.iteration` side by side with ours found the formulas
identical in distribution. The cause was elsewhere:

**SameSim's seeds weren't independent.** Agent streams were seeded
`seed XOR agent_id`. For seeds below the agent count, XOR only permutes
ids, so seeds 1 and 2 used the *identical set* of 500 agent streams,
assigned to different agents. The 20 "independent" replicates were partly
copies of each other, which understated their spread (sd 7.6 against 10.8
for NDlib over 60 seeds) and made a small difference look significant.
This affected every study that averages over seeds, not only this one.

Fixed by class: streams are now hashed from `"<seed>/agent/<id>"`
(`samesim/core/randomness_manager.py`), and
`tests/unit/core/test_randomness_manager.py` checks that no two of
64 seeds x 1,024 agents share a stream and that named streams never
coincide with agent streams. It fails for XOR, for seed + id and for
separator-free concatenation. Every study in `experiments/` was re-run.

The same investigation found one real, smaller convention difference: the
initially infected took a recovery draw before exposing anyone, an expected
infectious period 10% shorter than every other agent's. The first
synchronous step is now an announcement round, so SameSim's state at time t
is exactly iteration t of the standard discrete-time SIR.

**Re-run, three ways, 200 seeds** (`sir_vs_ndlib.py`). A third
implementation referees: NDlib's iteration transcribed into plain Python
with its own RNG. Means with 95% CIs; Welch's t-test for a difference;
TOST for equivalence within ±1% of the reference mean.

| | NDlib | SameSim | Reference |
|---|---:|---:|---:|
| peak infected | 362.3 ± 1.5 | 360.4 ± 1.5 | 361.6 ± 1.6 |
| final recovered | 498.75 ± 0.13 | 498.77 ± 0.13 | 498.65 ± 0.15 |
| extinction tick | 70.0 ± 1.4 | 69.7 ± 1.5 | 70.8 ± 1.6 |

- No pair differs significantly on any metric (all Welch p > 0.07).
- **Final size:** all three pairs equivalent within ±1% (TOST p < 10⁻¹⁶⁰).
- **Peak:** SameSim is equivalent to the reference (TOST p = 0.015), and
  so is NDlib (p = 0.005). SameSim vs. NDlib directly is not quite shown
  equivalent at ±1% (difference −1.95, TOST p = 0.065).
- **Extinction tick:** ±1% is 0.7 ticks against a standard deviation of
  ~10; no pair, including NDlib vs. the reference, can be shown equivalent
  that tightly at this sample size. No pair differs significantly either.

## Bug 2 — engine silently dropped the final tick (found designing check #5)

While designing the closed-form message-count check, `SimulationEngine.run()`
turned out to break its dispatch loop immediately after processing the
*first* event whose `virtual_time` reached `max_virtual_time`, rather than
draining every event scheduled at that same instant — silently dropping the
tick AT `max_virtual_time` and most of the final message batch. See the
fix commit and `tests/integration/test_engine_termination.py` for the full
writeup; noted here because it's the same "closed-form check catches a real
bug" story, one level lower in the stack (the engine itself, not a
behavior plugin).

## Everything else: clean matches — within the coverage these checks have

Checks #2, #3, and #4 turned up no discrepancies beyond expected stochastic
variation between independently-seeded implementations. Notably, #3
(topology structure) matches NetworkX almost to the decimal — Ring and Grid
exactly (deterministic constructions), Erdős–Rényi/Watts–Strogatz/
Barabási–Albert within statistical noise of a single-realization
comparison. #4 (leader election) never once exceeded its theoretical bound
across 15 cases spanning n=50 to n=1,000.

**Read that with the coverage in mind, though.** Each check exercises one
behavior paired with one protocol — check #2 covers `GossipBehavior` +
`GossipProtocol`, check #1 covers `SirEpidemicBehavior` +
`BroadcastProtocol`. That is 2 cells of a 3×3 behavior×protocol matrix, and
a later audit found **6 of the then-12 combinations broken** — including one
the SIR fix itself introduced. Passing these five checks means the paths
they touch are right; it never meant the whole matrix was.

That gap is now closed structurally rather than by adding more one-off
comparisons: `tests/unit/plugins/test_addressing_contract.py` sweeps every
behavior × protocol pair, and `test_topology_complexity.py` sweeps every
topology generator. Both discover plugins by walking the package, so they
cover plugins that don't exist yet. See the root-cause writeup in
[docs/developer_guide.md](../../docs/developer_guide.md)
for the addressing contract those tests enforce.

## What this doesn't cover yet

- No comparison against PeerSim specifically (the natural gossip/P2P
  counterpart) — the numpy reference substitutes for it; a real PeerSim
  comparison would mean a Java cross-language integration, flagged as a
  bigger lift than this pass justified.
- Peak infected, SameSim vs. NDlib directly: equivalence within ±1% is
  borderline (TOST p = 0.065) at 200 seeds, although each is equivalent to
  the independent reference.
- No real-world dataset comparison (e.g. a documented epidemic outbreak,
  a real social-network topology) — deliberately out of scope: SameSim is
  a systems/tools contribution, and matching noisy real data with unknown
  confounding parameters is a different (harder, less relevant) kind of
  validation than checking against a trusted independent implementation.

## Postscript — the "run it yourself" instructions were false

Every README in `experiments/` tells the reader to run the scripts
themselves. Until 2026-09-24 that was not true of a single one of them: ten
scripts hardcoded an absolute repo root under one developer's home
directory, and five wrote their results into an agent session's scratchpad
directory whose path contained a UUID. On a fresh clone they would have
failed on import, or silently written their output somewhere other than
where these READMEs say to look.

Nothing caught it because the scripts worked perfectly on the one machine
they were written on — the same shape as the other bugs documented here:
correct-looking behavior that was never exercised outside its original
context. It is fixed (paths now derive from `Path(__file__)`; intermediate
work goes to a gitignored `_work/` overridable via `SAMESIM_EXPERIMENT_WORK`)
and guarded by `tests/unit/test_experiment_script_portability.py`, which
sweeps every committed `.py` file rather than the five that happened to be
wrong.

All five checks above have been re-verified from a foreign working
directory on the post-audit engine: topology matches NetworkX, leader
election stays within the diameter bound, the closed-form event count now
agrees **exactly** (it was short by one tick before the engine fix), gossip
matches the numpy reference, and SIR matches NDlib. (The gossip and SIR
numbers in that re-verification were later superseded: see "The residual
gap, resolved" above for the 200-seed, independently seeded comparison.)
