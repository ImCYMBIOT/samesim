# External Validation — 5 Independent Cross-Checks

**Status:** first pass. Complements
[experiments/gossip_topology_validation/](../gossip_topology_validation/)
(validates against mixing-time *theory*) and
[experiments/scaling_benchmark/](../scaling_benchmark/) (validates
*performance*) with the piece neither of those can catch: comparison
against tools and math that share **no code** with Simul8. This is exactly
the kind of check that catches an implementation bug hiding behind
plausible-looking, theory-consistent numbers — and it did, twice.

## Why external validation, not more internal theory-checking

The topology validation study confirms Simul8's *scaling behavior* matches
mixing-time theory. It would not have caught a bug that inflates every
agent's infection probability by a roughly-constant factor — the epidemic
would still rise, peak, and burn out in the right *shape*, just at the
wrong *magnitude*, and nothing in that study's checks would flag it. That
gap is exactly what this suite is for: put Simul8 next to something that
implements the same math independently, on the identical input, and see if
the numbers actually agree.

## The five checks

| # | Script | Compared against | Result |
|---|---|---|---|
| 1 | `sir_vs_ndlib.py` | [NDlib](https://ndlib.readthedocs.io) (independent epidemiology-on-networks library) | **Found and fixed a real bug** — see below |
| 2 | `gossip_vs_reference.py` | A numpy-based reference gossip implementation, written from the algorithm's spec | Matches (mean 11.3 vs. 12.3 ticks to converge, overlapping distributions) |
| 3 | `topology_vs_networkx.py` | NetworkX's equivalent generators, for all 5 topologies | Near-exact match on every structural statistic |
| 4 | `leader_election_vs_diameter.py` | Graph diameter (computed via NetworkX) — an analytical bound, not another simulator | 15/15 cases within the theoretical bound |
| 5 | `event_count_vs_closed_form.py` | Exact combinatorial arithmetic (`n × fan_out × ticks`) | **Also caught a real bug** — see below |

Run any of them (from this directory, `simul8` conda env active, with
`pip install networkx ndlib six` for the SIR check specifically):
`python sir_vs_ndlib.py`, `python gossip_vs_reference.py`,
`python topology_vs_networkx.py`, `python leader_election_vs_diameter.py`,
`python event_count_vs_closed_form.py`.

`simul8_harness.py` is shared infrastructure: it wires Simul8's real core
(same code path as `ExperimentRunner`) but accepts a pre-built
`TopologyGraph` — usually converted directly from a NetworkX graph — so
Simul8 and the comparison tool run on the **exact same graph object**,
not two separately generated graphs that are merely statistically similar.

## Bug 1 — SIR double fan-out (found by check #1, confirmed by check #5's method)

`SirEpidemicBehavior` addressed one outbound message per neighbor when
infected — correct for a pass-through protocol like `GossipProtocol`, but
it's paired with `BroadcastProtocol`, which *also* fans each message out to
every neighbor of the sender (ignoring the message's addressed recipient).
The combination double-fanned-out: a degree-*d* infected agent delivered
*d* copies to each neighbor instead of 1, inflating the effective
transmission rate far above the configured `beta`.

First signal: peak infection count was **~28% higher** in Simul8 than in
20 matched NDlib runs on the identical graph — completely disjoint
distributions (Simul8 `[457, 472]` vs. NDlib `[353, 378]`), not seed noise.
Confirmed precisely by tracing delivery counts on a 4-agent star: a
degree-3 infected agent was delivering **3 copies to each neighbor**
instead of 1.

**Fixed** in `simul8/plugins/behaviors/sir_behavior.py`: send exactly one
message when infected and let the protocol handle fan-out, matching how
`BroadcastProtocol` is documented to be used. Re-ran the same 20-seed
comparison after the fix: peak infection mean **362.0 (NDlib) vs. 368.3
(Simul8)**, standard deviations 7.2 vs. 6.9, ranges now heavily
overlapping. A small residual difference remains (~1.7%, two-sample
t≈2.8) — plausibly a one-tick difference in when a newly-infected node
starts spreading between the two tools' discrete-time conventions, not
another correctness bug; flagged as an open, low-priority question rather
than asserted as explained. Locked in with
`tests/unit/plugins/test_sir_broadcast_fanout.py`.

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
[docs/plugin_development_guide.md](../../docs/plugin_development_guide.md)
for the addressing contract those tests enforce.

## What this doesn't cover yet

- No comparison against PeerSim specifically (the natural gossip/P2P
  counterpart) — the numpy reference substitutes for it; a real PeerSim
  comparison would mean a Java cross-language integration, flagged as a
  bigger lift than this pass justified.
- The SIR residual ~1.7% gap (see Bug 1) isn't fully explained, just
  bounded and judged small relative to the bug that was fixed.
- No real-world dataset comparison (e.g. a documented epidemic outbreak,
  a real social-network topology) — deliberately out of scope: Simul8 is
  a systems/tools contribution, and matching noisy real data with unknown
  confounding parameters is a different (harder, less relevant) kind of
  validation than checking against a trusted independent implementation.
