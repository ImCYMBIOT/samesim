# Simul8

Modular event-driven simulation platform for distributed systems research.

The core engine is domain-agnostic and manages only agents, virtual time, event scheduling, communication routing, and metric dispatch. All domain-specific details (agent behaviors, network topologies, routing protocols, and metric collection) are implemented as pluggable adapters.

## Features

- **Clean Hexagonal Architecture**: Strictly separated domain, ports, core engine, and application layers. Plugins cannot import the core; a test enforces it.
- **Deterministic and Reproducible**: Every agent gets its own RNG stream, hashed from the seed and its id, and events are ordered by `(virtual_time, priority, event_id)`, so the same seed produces the same run, bit for bit, on Python 3.10 through 3.13 and across Linux, macOS and Windows. CI checks this on every push. `TraceDigestMetric` gives each run a SHA-256 fingerprint you can publish with a result as a reproducibility receipt.
- **Pluggable Architecture**: Swap behaviors, communication protocols, network topologies, metrics, and exporters from YAML. No core changes needed.
- **Lean**: Pure Python with a single runtime dependency (PyYAML). Built with a future Rust port in mind. See [By the numbers](#by-the-numbers) for what that costs in speed.

## Documentation

| Document | For |
|---|---|
| [User Guide](docs/user_guide.md) | Running experiments: the config file, activation modes, latency, churn, every plugin's options, output files |
| [Developer Guide](docs/developer_guide.md) | Writing plugins: architecture, the event loop, determinism rules, the ports, contract tests |
| [Design](docs/design.md) | Why it's built this way: principles, the time model, lessons learned, validation status, roadmap |

Each study under [`experiments/`](experiments/) has its own README next to its scripts and raw data.

## Directory Structure

```
simul8/
├── domain/        # Data: Agent, Message, Event, State, Topology, Delivery, Timer, TopologyChange, portable_math
├── ports/         # Contracts: Behavior, Communication, TopologyGenerator, MetricCollector, Persistence, TopologyDynamics
├── core/          # Engine: SimulationEngine, Scheduler, EventQueue, AgentRegistry, TopologyManager, ...
├── app/           # Orchestration: ConfigLoader, PluginLoader, ExperimentRunner
├── plugins/       # behaviors/ communication/ topologies/ metrics/ persistence/ dynamics/
└── cli/           # simul8 run, simul8 visualize
examples/          # Ready-to-run YAML configs
experiments/       # Validation studies: scripts, raw results, write-ups
tests/             # unit/ integration/ regression/
```


## Two ways to run agents

- **Synchronous** (default): every agent steps on every tick, like a round-based simulator. Message delays round up to whole ticks.
- **Event-driven** (`simulation.activation: event`): agents act only when a message reaches them or a timer they set fires. Delays are exact. This is how you model timeouts, heartbeats and Poisson clocks.

A behavior declares which modes it supports, and a config asking for any other mode is rejected when it loads, before it can run and produce misleading numbers.

## What a run produces

Each experiment writes self-describing CSV time series (a comment header carries the experiment name, seed, and schema version) plus a `summary.json` / `summary.md` with the config and wall-clock runtime:

```
# experiment: sir_random
# seed: 9876
# schema_version: 1.0
# metric: sir_infected
virtual_time,value
0.0,2.0
1.0,5.0
...
```

| Plugin type | Included |
|---|---|
| Behaviors | Gossip averaging, leader election (max-id flooding), SIR epidemic, asynchronous pairwise gossip (Boyd et al.), Raft leader election, single-server queue (M/M/1) |
| Protocols | Gossip (point-to-point), broadcast, lossy (configurable drop rate), latency (constant, uniform, exponential or lognormal per-message delay, plus loss) |
| Topologies | Ring, 2-D grid (optional wrap), Erdős–Rényi, Watts–Strogatz, Barabási–Albert |
| Metrics | Convergence variance, message count, S/I/R counts, leader-consensus fraction, full per-agent state trace, topology edge list, run fingerprint (SHA-256 per tick), Raft elections and election-safety violations, running agents and lost messages under churn, consensus among running vs. all agents, queue waits and occupancy |
| Exporters | CSV |
| Churn (optional) | Scheduled faults with state-based targeting ("crash whoever is leader at t=1000"), random Poisson failure/recovery |

All eight example configs in `examples/` finish in under 3 seconds each (seven of them in under a second), including interpreter startup.

## By the numbers

Everything below comes from committed scripts under [`experiments/`](experiments/) with raw JSON next to them. Re-run any of it with the commands in each study's README.

### Scale

Gossip (fan-out 2), 50 ticks, one core, pure Python:

| Agents | Events processed | Wall time | Throughput | Peak memory |
|---:|---:|---:|---:|---:|
| 1,000 | 100,052 | 1.3 s | ~77k events/s | 38 MB |
| 10,000 | 1,000,052 | 16.5 s | ~60k events/s | 216 MB |
| 30,000 | 3,000,052 | 57 s | ~53k events/s | 612 MB |
| 100,000 | 10,000,052 | 172 s | ~58k events/s | 2.0 GB |

- **The engine scales linearly.** On a ring, the local log-log slope of runtime vs. agents stays between 0.92 and 1.13 from 100 to 100,000 agents. On Erdős–Rényi (average degree 8) it's 0.81–1.35, mildly superlinear in the middle of the range: runtime is 1.0× Ring's at 300 agents and 1.7× at 100,000. The extra cost has been traced to `GossipBehavior.step()`, not the engine, but not yet to a specific line.
- **No topology generator is quadratic.** Erdős–Rényi with 100,000 agents builds in 0.82 s. A contract test fails the build if any generator, including future ones, grows quadratically.
- **The architecture costs about an order of magnitude.** A bare-loop implementation of the same gossip protocol runs 6–12× faster across our measurements, and the ratio stops growing above ~1,000 agents. That overhead pays for the event queue, determinism, and plugin isolation.

*All rows are from the current engine. Timings were taken on a developer laptop and vary about ±10% run to run. Slopes and event counts are the reliable figures.*

### Correctness against independent tools

Simul8 was checked against software and math it shares no code with, on the identical input graph:

| Check | Simul8 | Reference | Verdict |
|---|---|---|---|
| SIR epidemic, 500 agents, 200 seeds: peak infected (mean ± 95% CI) | 360.4 ± 1.5 | 362.3 ± 1.5 ([NDlib](https://ndlib.readthedocs.io)); 361.6 ± 1.6 (independent reference) | Equivalent to the reference within ±1% (TOST p = 0.015); vs. NDlib no significant difference (p = 0.07), equivalence borderline (TOST p = 0.065) |
| SIR: final recovered | 498.77 ± 0.13 | 498.75 ± 0.13 (NDlib) | Equivalent within ±1% (TOST p < 10⁻¹⁶⁰) |
| Gossip ticks to converge, 300 agents, 200 seeds | 10.91 ± 0.21 | 10.89 ± 0.21 (independent numpy impl.) | Equivalent within ±0.5 tick (TOST p = 0.001) |
| Watts–Strogatz clustering / avg. path | 0.4164 / 4.094 | 0.4164 / 4.094 ([NetworkX](https://networkx.org)) | Exact |
| Ring and grid diameter / avg. path | 250 / 125.25, 20 / 10.03 | Identical (NetworkX) | Exact |
| Erdős–Rényi, Barabási–Albert structure | avg. degree, diameter, clustering | NetworkX | Within single-sample noise |
| Leader election consensus time | ≤ diameter in 15/15 cases (n = 50–1,000) | Graph diameter (analytical bound) | Always within bound |
| Total messages delivered | n × fan-out × ticks | Closed-form count | Exact |

These checks found three real bugs, which are fixed and have regression tests: an O(n²) topology generator, a dropped final tick, and a double fan-out that inflated SIR transmission by ~28%. An outside review of the NDlib comparison then found a fourth: runs with different seeds shared the same agent random streams (`seed XOR agent_id`), so replicates were partly copies of each other and a 0.3% difference looked significant. Streams are now hashed per (seed, agent), a guard test covers it, and every study was re-run. Details: [`experiments/external_validation/`](experiments/external_validation/).

### Reproducing theory

Gossip convergence time vs. network size (20 seeds per point, average degree 8, time to 1% of the initial variance), fitted log-log slope with a bootstrap 95% CI:

| Topology | Slope (95% CI) | Meaning |
|---|---:|---|
| Ring | 1.37 (1.24–1.49) | Superlinear at this threshold; about quadratic at a strict one (below) |
| Barabási–Albert | 0.11 (0.09–0.12) | Nearly flat |
| Watts–Strogatz | 0.11 (0.08–0.14) | Nearly flat |
| Erdős–Rényi | 0.08 (0.05–0.10) | Nearly flat |

This matches mixing-time theory: well-connected graphs converge in roughly constant time, and a cycle doesn't. Details: [`experiments/gossip_topology_validation/`](experiments/gossip_topology_validation/).

The ring's exponent depends on the threshold. At 1e-4 it is about quadratic (1.83, CI 1.78–1.87, for synchronous push gossip; 1.80, CI 1.75–1.84, for Boyd et al.'s asynchronous pairwise gossip), matching the classical O(n²) result; at 1% it is about 1.35 for both. An earlier version reported "linear at 1%" (slope 0.99); with independent seeds that didn't hold. Details: [`experiments/async_gossip_validation/`](experiments/async_gossip_validation/).

Raft leader election reproduces the qualitative findings of the Raft paper (Ongaro & Ousterhout 2014, Fig. 16). From a cold start without timeout randomization, no leader is ever elected. A 150–300 ms range elects in the first term in almost every trial (mean winning term 1.01). Timeouts near the network delay cause about 27 unnecessary re-elections per 5 seconds. In the paper's actual scenario, crashing the leader of a running cluster, a 150–300 ms range restores a leader in a median of 185 ms (95% CI 183–188, p95 335 ms), and at every range a crash needs a second election round more often than a cold start does. Election Safety (at most one leader per term) held in all 11,000 trials across both studies. Details: [`experiments/raft_election_validation/`](experiments/raft_election_validation/).

With per-message latency, gossip convergence time grows linearly with mean delay (R² ≥ 0.997). At equal mean, exponential delays converge 19% faster (95% CI 16–23%) than constant ones at mean 16 but slower at mean 1, so the shape of the delay distribution matters, not just its average. Details: [`experiments/latency_validation/`](experiments/latency_validation/).

Under churn, gossip degrades gracefully: with half the agents down at any moment, the running agents still converge, 3–3.5× slower, with no cliff anywhere in between (t ∝ (1 − f)^−1.5 to (1 − f)^−1.8, 40 seeds per point). Agreement across *every* agent, crashed ones included, is a different matter: with long outages it waits for agents that crashed before consensus formed to come back, and at 10% down takes about twice as long as the running agents do. Churn doesn't bias the consensus value, and lost messages match f(1 − f)·n·k·T within 2.5%. Details: [`experiments/churn_convergence_validation/`](experiments/churn_convergence_validation/).

### Tests

**906 passing on each of Python 3.10, 3.11, 3.12 and 3.13** (unit, integration, regression). Seven of the suites are *contract tests that discover their targets automatically*, so they also cover plugins and files that don't exist yet:
- every behavior × protocol pairing delivers exactly once per intended recipient
- no topology generator scales quadratically
- every module respects the layering (`plugins` → `domain`, `ports` only), with relative imports resolved
- no committed script hardcodes a machine-specific path
- under random churn, no failed agent ever runs or receives a message, for every behavior × activation mode × protocol
- no `plugin_configs` option can be silently ignored, for every configurable plugin role: a misspelled or inapplicable option is rejected before the run
- **golden traces**: every behavior × protocol × topology is fingerprinted, so any change that alters a single delivered message fails the build and names the first tick that diverged

## What it can't do yet

All three phases of the time-model design are in: per-message latency, event-driven agents with timers, and churn (nodes that fail, recover and join, and links that change). See [Design](docs/design.md). Still missing:

- **Network partitions and asymmetric links.** Churn fails nodes, not links in one direction. A partition can be modeled with `remove_edges`, but the messages already in flight across it still arrive.
- **Log replication.** `RaftElectionBehavior` is Raft's leader election only.
- **Scale beyond ~10⁵ agents.** It's pure Python at about 60k events/s.

## Getting Started

### Installation

Clone the repository and install it in editable dev mode:

```bash
pip install -e ".[dev]"
```

### Running an Experiment

```bash
simul8 run examples/raft_leader_crash.yaml --output ./results
simul8 visualize ./results        # interactive dashboard.html
```

This crashes a Raft cluster's leader at t=1000 ms and restarts it at 2500 ms, and writes the elections, running-agent counts and message counts as CSV to `./results`. The [User Guide](docs/user_guide.md) covers writing your own configs.

### Running Tests

```bash
pytest                  # ~70 s
pytest -m "not slow"    # skip the scale tests
```

## License

MIT. See [LICENSE](LICENSE).
