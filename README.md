# Simul8

Modular event-driven simulation platform for distributed systems research.

The core engine is domain-agnostic and manages only agents, virtual time, event scheduling, communication routing, and metric dispatch. All domain-specific details (agent behaviors, network topologies, routing protocols, and metric collection) are implemented as pluggable adapters.

## Features

- **Clean Hexagonal Architecture**: Strictly separated domain, ports, core engine, and application layers. Plugins cannot import the core; a test enforces it.
- **Deterministic and Reproducible**: Every agent gets its own seeded RNG (`seed XOR agent_id`), and events are ordered by `(virtual_time, priority, event_id)`, so the same seed produces the same run, bit for bit, on Python 3.10 through 3.13 and across Linux, macOS and Windows. CI checks this on every push. `TraceDigestMetric` gives each run a SHA-256 fingerprint you can publish with a result as a reproducibility receipt.
- **Pluggable Architecture**: Swap behaviors, communication protocols, network topologies, metrics, and exporters from YAML. No core changes needed.
- **Lean**: Pure Python with a single runtime dependency (PyYAML). Built with a future Rust port in mind. See [By the numbers](#by-the-numbers) for what that costs in speed.

## Directory Structure

```
simul8/
├── domain/        # Opaque data models (Agent, Event, Message, State)
├── ports/         # Abstract port contracts (Behavior, Communication, Topology, Metrics, Persistence)
├── core/          # Simulation engine internals (Scheduler, EventQueue, Registry)
├── app/           # Application orchestration (ConfigLoader, PluginLoader, ExperimentRunner)
├── plugins/       # Concrete plugins (Gossip, Ring, Random Graph, CSV Exporter)
└── cli/           # CLI command line interface
```

## Documentation

For a deep dive into the architecture, component design, and simulation loop lifecycle, see the [Extended Documentation & Developer Guide](docs/extended_documentation.md). For step-by-step instructions on writing your own plugins (behaviors, topologies, protocols, metrics, exporters), see the [Plugin Development Guide](docs/plugin_development_guide.md).


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
| Behaviors | Gossip averaging, leader election (max-id flooding), SIR epidemic, asynchronous pairwise gossip (Boyd et al.), Raft leader election |
| Protocols | Gossip (point-to-point), broadcast, lossy (configurable drop rate), latency (constant, uniform, exponential or lognormal per-message delay, plus loss) |
| Topologies | Ring, 2-D grid (optional wrap), Erdős–Rényi, Watts–Strogatz, Barabási–Albert |
| Metrics | Convergence variance, message count, S/I/R counts, leader-consensus fraction, full per-agent state trace, topology edge list, run fingerprint (SHA-256 per tick), Raft elections and election-safety violations |
| Exporters | CSV |

All five example configs in `examples/` finish in under 0.4 s each.

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
| SIR epidemic, 500 agents, 20 seeds: peak infected | 368.3 ± 6.9 | 362.0 ± 7.2 ([NDlib](https://ndlib.readthedocs.io)) | Within 1.7% |
| SIR: final recovered | 499.1 | 498.9 (NDlib) | Match |
| Gossip ticks to converge, 300 agents, 15 seeds | 11.3 ± 1.6 | 12.3 ± 1.8 (independent numpy impl.) | Distributions overlap |
| Watts–Strogatz clustering / avg. path | 0.4164 / 4.094 | 0.4164 / 4.094 ([NetworkX](https://networkx.org)) | Exact |
| Ring and grid diameter / avg. path | 250 / 125.25, 20 / 10.03 | Identical (NetworkX) | Exact |
| Erdős–Rényi, Barabási–Albert structure | avg. degree, diameter, clustering | NetworkX | Within single-sample noise |
| Leader election consensus time | ≤ diameter in 15/15 cases (n = 50–1,000) | Graph diameter (analytical bound) | Always within bound |
| Total messages delivered | n × fan-out × ticks | Closed-form count | Exact |

These checks found three real bugs, which are fixed and have regression tests: an O(n²) topology generator, a dropped final tick, and a double fan-out that inflated SIR transmission by ~28%. Details: [`experiments/external_validation/`](experiments/external_validation/).

### Reproducing theory

Gossip convergence time vs. network size (5 seeds per point, average degree 8), fitted log-log slope:

| Topology | Slope | Meaning |
|---|---:|---|
| Ring | 0.99 | Grows linearly with n *at this threshold* (see below) |
| Watts–Strogatz | 0.16 | Nearly flat |
| Barabási–Albert | 0.11 | Nearly flat |
| Erdős–Rényi | 0.05 | Flat |

This matches mixing-time theory qualitatively: well-connected graphs converge in roughly constant time, and a cycle doesn't. The study was re-run end to end on the current engine, and every slope reproduced. Details: [`experiments/gossip_topology_validation/`](experiments/gossip_topology_validation/).

The ring's linear slope is an artifact of the 1% convergence threshold. At a 1e-4 threshold the ring is about quadratic (fitted slope 1.82 for synchronous push gossip, 1.78 for Boyd et al.'s asynchronous pairwise gossip), which matches the classical O(n²) result. Details: [`experiments/async_gossip_validation/`](experiments/async_gossip_validation/).

Raft leader election reproduces the qualitative findings of the Raft paper (Ongaro & Ousterhout 2014, Fig. 16). Without timeout randomization no leader is ever elected. A 150–300 ms range elects in the first term every time. Timeouts near the network delay cause about 26 unnecessary re-elections per 5 seconds. Election Safety (at most one leader per term) held in all 5,500 trials. Details: [`experiments/raft_election_validation/`](experiments/raft_election_validation/).

With per-message latency, gossip convergence time grows linearly with mean delay (R² ≥ 0.997). At equal mean, exponential delays converge 23% faster than constant ones at mean 16 but slower at mean 1, so the shape of the delay distribution matters, not just its average. Details: [`experiments/latency_validation/`](experiments/latency_validation/).

### Tests

**678 passing on each of Python 3.10, 3.11, 3.12 and 3.13** (unit, integration, regression). Five of the suites are *contract tests that discover their targets automatically*, so they also cover plugins and files that don't exist yet:
- every behavior × protocol pairing delivers exactly once per intended recipient
- no topology generator scales quadratically
- every module respects the layering (`plugins` → `domain`, `ports` only), with relative imports resolved
- no committed script hardcodes a machine-specific path
- **golden traces**: every behavior × protocol × topology is fingerprinted, so any change that alters a single delivered message fails the build and names the first tick that diverged

## What it can't do yet

The network is fixed for the whole run: nodes can't join, leave or fail, and links can't break. That rules out churn, fault-tolerance and crash-recovery studies (including Raft's leader-crash scenario) until Phase 3. Per-message latency (Phase 1) and event-driven agents with timers (Phase 2) have landed. The design is in [docs/design/event_model.md](docs/design/event_model.md).

## Getting Started

### Installation

Clone the repository and install it in editable dev mode:

```bash
pip install -e ".[dev]"
```

### Running an Experiment

To run the default 1,000-agent gossip convergence experiment:

```bash
simul8 run examples/gossip_1000_agents.yaml --output ./results
```

This will run the simulation and export results (convergence variance and message count) to the `./results` directory.

### Running Tests

Execute the test suite (unit, integration, and regression tests) using pytest:

```bash
pytest
```
