# Simul8 Design

Why the engine is built the way it is, what was learned while building it,
and what comes next. How-to material is in the [User Guide](user_guide.md)
and the [Developer Guide](developer_guide.md).

## Contents

1. [Principles](#1-principles)
2. [The time model](#2-the-time-model)
3. [Reproducibility](#3-reproducibility)
4. [What building it taught us](#4-what-building-it-taught-us)
5. [Validation status](#5-validation-status)
6. [Non-goals](#6-non-goals)
7. [Open questions](#7-open-questions)
8. [Roadmap](#8-roadmap)

## 1. Principles

1. **The core never knows what it's simulating.** The engine deals in
   agents, virtual time, events, messages and metrics. Gossip, Raft and
   epidemics are plugins. A new research idea should need new plugins,
   not engine changes.
2. **Reproducibility over raw speed.** The same config and seed give the
   same run, bit for bit, on every supported Python and OS. When speed and
   determinism conflict, determinism wins.
3. **Every experiment is one file.** A YAML config fully specifies a run,
   so experiments can be diffed, versioned and re-run by anyone.
4. **Fail loudly at load time, never silently at run time.** The worst
   failure is a combination that runs, returns plausible numbers and is
   wrong. Incompatible plugins, invalid parameters and impossible delays
   are rejected before the first event.
5. **Contracts are enforced by tests that discover their targets.** A
   guard that lists the plugins it covers stops covering the next one.
   Every contract test walks the package, and every guard is
   mutation-tested: we break the code on purpose and confirm the guard
   fails.
6. **Fix bugs by class.** A bug is evidence that a rule was missing. Fix
   the rule and add a guard for it, not just the one simulation where the
   bug showed up.
7. **Additive change.** New capabilities must leave every existing
   simulation bit-identical. Golden traces make that checkable rather
   than a promise.

These are enforced mechanically where possible:
- The layering (section 1 of the Developer Guide) is checked on every
  import.
- Plugins get configuration only through the port and hold no references
  into the core.
- Configs and messages are frozen dataclasses.
- Metrics see the simulation only through events, never by reading agent
  state.

## 2. The time model

The engine began as a synchronous tick loop on top of a discrete-event
queue. Every agent stepped every tick, every message took exactly one
tick, and the graph never changed. That made three baseline needs of
distributed-systems research impossible:
- latency distributions
- timeouts and asynchronous clocks
- churn

The port contract also promised more than the code allowed. It said a
protocol decides "whether and **when**" a message arrives, but `route()`
had no way to express when.

The model was extended in four phases, each shipped separately and each
leaving all existing golden traces unchanged.

**Phase 0: lock current behavior.** Before touching the core, every
behavior × protocol × topology combination and every example got a
SHA-256 fingerprint of the entire run (`TraceDigestMetric`). This check
immediately found that gossip runs differed between Python 3.11 and 3.12
(section 4).

**Phase 1: per-message latency.** `route()` may return
`Delivery(recipient, message, delay)`, and a bare tuple still means one
tick.
- Delays must be finite and > 0. Zero is excluded so two agents can't
  reply to each other forever without time advancing.
- In synchronous mode a delay rounds up to the next tick. That tick is
  taken from the schedule's own repeated additions rather than
  `now + k*dt`, because at dt = 0.1 the two differ by one ulp and a
  message would silently wait an extra tick.

**Phase 2: event activation and timers.** With `activation: event`,
agents run only at bootstrap, when messages arrive (all messages at one
instant as one batch) and when their timers fire.
- There is one pending timer per (agent, tag), and setting a pending tag
  replaces it, so "reset the election timeout" is just setting it again.
- Batching needs no lookahead. Deliveries have a lower priority number
  than wakes, so the heap has already queued every message for an instant
  before any agent at that instant runs.
- Timers sit after wakes, so a heartbeat beats a timeout due at the same
  instant.
- Behaviors declare their activation modes, and a mismatch is rejected at
  load. Otherwise a tick-driven behavior in event mode would run once and
  report "never converged".

**Phase 3: churn.** An optional `TopologyDynamicsPort` fails, recovers and
joins agents and adds or removes edges while the simulation runs. The
built version departs from the plan in three ways, each forced by a
concrete case:

1. **Liveness is separate from structure.** A crash is `fail`, not
   "remove agent". Neighbors keep the crashed node and find out through
   timeouts, as in real systems. Raft's crash-recovery scenario needs the
   crashed node to come back *as itself*, which remove-then-add can't
   express.
2. **`recover` keeps state, and `on_recover()` drops what a restart
   loses.** Raft's safety depends on this. A node that forgot its vote on
   restart could vote twice in a term.
3. **The port asks *when* (`next_time`) and *what* (`change`)
   separately.** The first plugin written, "crash whoever is leader at
   t=1000", can't be decided at t=0, before there is a leader.

Churn changes apply before anything else at their instant. Metrics see a
change before its consequences. Churn draws from its own RNG stream, so
adding it never shifts the protocol's draws.

## 3. Reproducibility

Determinism rests on four mechanisms:

- **The event order is total:** `(virtual_time, priority, event_id)`.
- **Per-agent RNGs** are seeded `seed XOR agent_id`, so adding an agent or
  reordering work doesn't change anyone else's random numbers. Plugins
  that need their own randomness, such as churn, get named streams.
- **`math.fsum` instead of `sum()`** for floats, because CPython 3.12
  changed `sum()`.
- **`portable_math`** for `log`, `exp`, powers and non-uniform variates.
  - It is built only from IEEE-exact operations, accurate to within 2 ulp,
    at about 0.7 µs per call, and consumes the RNG exactly as CPython
    does.
  - The C math library differs across operating systems in the last bit.
    In event mode those bits are event times, so the runs themselves
    diverged.

CI enforces the result:
- the full suite on Python 3.10–3.13
- golden traces and `portable_math` known-answer tests on macOS and
  Windows
- a lint test that rejects platform-dependent math anywhere in the engine
  or plugins

A run's final `TraceDigestMetric` value serves as a reproducibility
receipt you can publish with a result.

## 4. What building it taught us

Most of these were caught by a guard written for something else, which is
the argument for principle 5.

| Found | How | Fix, by class |
|---|---|---|
| A topology generator was O(n²) | Scaling benchmark | Geometric edge-skipping in Erdős–Rényi and rejection sampling in Watts–Strogatz; a complexity contract test for every generator |
| The final tick was dropped | Closed-form message count | Engine termination fixed; regression test |
| SIR transmission was inflated ~28% by double fan-out | Cross-check against NDlib | The addressing contract, plus a test over every behavior × protocol pair |
| Two metrics imported the core through relative imports | Boundary test rewrite | The boundary test resolves relative imports and fails on unparseable files |
| Experiment scripts hardcoded one developer's home directory | Review | A portability test over every committed script |
| Gossip differed between Python 3.11 and 3.12 | Phase 0 golden traces | `math.fsum` everywhere |
| A reversed inbox order changed no trace | Mutation-testing the golden traces | A probe behavior that pins exactly what the engine delivers |
| Superseded timers leaked to metrics | Mutation testing | Suppressed at dispatch |
| The addressing test skipped every event-driven behavior | Phase 2 | The test follows timers and reads the intended recipients off the messages |
| Event-mode runs differed on macOS and Windows | First cross-OS CI run | `portable_math`, a lint test and known-answer bit patterns |
| Failing an agent paused its timers instead of cancelling them | Mutation testing | A test with a timer due after recovery |
| Unused `plugin_configs` options were silently ignored: an example's `CsvExporter: output_dir` never did anything, and `LossyProtocol` swallowed a removed `mode` option | Documentation audit | Each plugin's section is tracked during setup, and any option never read is rejected, with a suggestion. This works for any plugin without it declaring its keys, and it also catches options for a mode that wasn't chosen. |
| `summary.json` listed config fields by hand and missed every field added later | Documentation audit | The summary serializes the whole `ExperimentConfig`; a test walks its dataclass fields |
| `gossip_1000_agents.yaml` ran 100 agents | Documentation audit | Now 1,000 agents |

Scientific findings are in the README's "By the numbers" section and in
each study under `experiments/`. The one that matters most for how the
tool should be used: the ring's O(n) convergence came from the 1%
threshold, not the protocol. At 1e-4, both synchronous and asynchronous
gossip on a ring are about O(n²), matching Boyd et al.

## 5. Validation status

Each phase was to ship with a result the old engine couldn't produce.

| Phase | Target | Status |
|---|---|---|
| 1 | Delays match their configured distribution; convergence grows linearly with mean latency | Done: KS and χ² tests pass; linear with R² ≥ 0.997, and delay shape matters at equal mean |
| 2 | Asynchronous gossip on a ring is ~O(n²) | Done: slope 1.78 at 1e-4, with synchronous at 1.82 |
| 2 | Raft election time vs. timeout range | Done: reproduces Ongaro & Ousterhout Fig. 16, with zero safety violations in 11,000 trials |
| 3 | Leader crash recovery | Done: 150–300 ms restores a leader in a median of 186 ms (p95 325 ms) |
| 3 | `RandomChurn` down fraction matches λ/(λ+μ) | Done: within 0.01 |
| 3 | Gossip convergence degrades gracefully as the churn rate rises | Done: among running agents, t ∝ (1 − f)^−1.5 (short outages) to (1 − f)^−1.0 (long), no cliff up to half the agents down. Agreement across *all* agents is set by downtime, and a stale-value model predicts it within 10% up to f = 0.2 |
| 3 | Lost messages match the churn rate | Done: f(1 − f)·n·k·T within 4% |

## 6. Non-goals

- **Parallel or distributed execution.** A single ordered queue and
  determinism are worth more here than wall-clock speedups.
- **Packet-level network emulation.** That's ns-3's job. Simul8 models
  latency at the message level, not TCP.
- **Continuous state dynamics (ODE integration).** Simul8 is event-driven
  only.

## 7. Open questions

1. **One activation entry point.** `step()`, `on_timer()` and
   `on_recover()` could become a single `on_activation(ctx)`. That's a
   breaking change, so it belongs at a 1.0 boundary.
2. **Timers in synchronous mode,** quantized to ticks like latency.
   Deferred until someone needs them.
3. **Event-mode performance.** Only active agents run, but every wake costs
   a heap operation. It hasn't been benchmarked against synchronous mode.
4. **Why a run ended.** An event-mode run whose agents all go silent ends
   when the queue empties. `SimulationEndedEvent` should say which
   condition ended it.
5. **`simul8 validate`.** Setup already rejects every bad option before
   the first event. A command that runs setup alone would let a sweep
   check all its configs before committing hours of compute.
6. **Config migration.** `schema_version` is checked but only `"1.0"`
   exists. The first schema change needs a migration path so old configs
   still reproduce.

## 8. Roadmap

**Near term: make it adoptable.**
- a license
- a versioned release on PyPI
- a Python API that builds and runs an experiment without YAML and returns
  results in memory
- a `simul8 validate` command (open question 5)

**Capability gaps.**
- Network partitions and one-way links: messages in flight across a cut
  link should be droppable.
- Raft log replication.

**Publishing.** Publish rather than patent. Ports-and-adapters design and
per-agent seeding are sound engineering but not novel claims. The plan:
1. A tools paper on Simul8 itself (for example in JOSS), built on the
   validation studies: cross-platform determinism, the contract-test
   method, the Raft Fig. 16 reproduction and the ring-threshold
   correction.
2. Results papers that use Simul8 for the studies it already supports:
   - topology vs. convergence
   - failures vs. consensus
   - network structure vs. epidemic spread

**Scale.** The engine runs at about 60k events/s in pure Python and scales
linearly to 10⁵ agents. The ports map directly onto Rust traits (frozen
dataclasses to structs, `EventQueue` to `BinaryHeap`), so the core could
move to Rust via PyO3 in stages:
1. queue and scheduler
2. registry, topology and communication layer
3. the full loop, calling back into Python only for Python-written
   behaviors

This is worth doing only once a study needs more than 10⁵ agents. Any port
must reproduce the golden traces exactly.
