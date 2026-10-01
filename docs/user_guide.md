# Simul8 User Guide

How to run experiments with the plugins that ship with Simul8: the config
file, the two activation modes, latency, churn, every plugin's options, and
what a run writes. To write your own plugins, see the
[Developer Guide](developer_guide.md).

## Contents

1. [Install](#1-install)
2. [Run an experiment](#2-run-an-experiment)
3. [The config file](#3-the-config-file)
4. [Activation: synchronous or event-driven](#4-activation-synchronous-or-event-driven)
5. [Latency and loss](#5-latency-and-loss)
6. [Churn: failures, recoveries, joins, rewiring](#6-churn-failures-recoveries-joins-rewiring)
7. [Plugin reference](#7-plugin-reference)
8. [What a run writes](#8-what-a-run-writes)
9. [Reproducibility](#9-reproducibility)
10. [Examples](#10-examples)

## 1. Install

Python 3.10–3.13. One runtime dependency (PyYAML).

```bash
git clone https://github.com/ImCYMBIOT/Simul8.git
cd Simul8
pip install -e ".[dev]"      # editable, with pytest
pytest                        # optional: ~90 s, 975 tests
```

## 2. Run an experiment

```bash
simul8 run examples/sir_random.yaml --output ./results
simul8 visualize ./results            # writes ./results/dashboard.html
```

`simul8 run` options:

| Option | Default | Meaning |
|---|---|---|
| `--output`, `-o` | `./results` | Directory for result files |
| `--log-level` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |

`simul8 visualize [DIR]` builds a self-contained HTML dashboard from a
results directory: a chart per metric, plus a network animation when the run
included `StateTraceMetric` and `TopologyMetric`. The page loads its charting
libraries from public CDNs, so it needs a network connection to view.

From Python:

```python
from simul8.app.experiment_runner import ExperimentRunner
ExperimentRunner().run("examples/sir_random.yaml", output_dir="./results")
```

## 3. The config file

An experiment is one YAML file. Everything that affects the result is in it.

```yaml
schema_version: "1.0"            # required; only "1.0" exists

experiment:
  name: "sir_random"             # required; prefixes every output file
  seed: 9876                     # required; determines all randomness

simulation:
  num_agents: 500                # required
  max_virtual_time: 100          # required; the run stops here
  tick_interval: 1               # default 1.0
  activation: synchronous        # or "event"; default synchronous (section 4)

plugins:                         # fully qualified class paths
  behavior: "simul8.plugins.behaviors.sir_behavior.SirEpidemicBehavior"          # required
  communication: "simul8.plugins.communication.gossip.GossipProtocol"           # required
  topology: "simul8.plugins.topologies.random_graph.ErdosRenyiTopology"         # required
  dynamics: "simul8.plugins.dynamics.random_churn.RandomChurn"                  # optional (section 6)
  metrics:                                                                       # optional, any number
    - "simul8.plugins.metrics.sir_metrics.SirInfectedMetric"
  persistence:                                                                   # optional, any number
    - "simul8.plugins.persistence.csv_exporter.CsvExporter"

plugin_configs:                  # options per plugin, keyed by CLASS name
  SirEpidemicBehavior:
    transmission_rate: 0.2
  ErdosRenyiTopology:
    edge_probability: 0.02
```

Before the first event, a config is rejected if:

- a required field is missing, or `activation` isn't a known mode;
- the behavior doesn't support the requested activation mode (section 4);
- a `plugin_configs` section names a class that isn't in the experiment
  (e.g. `GossipBehaviour`), or gives options to a metric or exporter,
  which never receive any;
- **an option had no effect**, because the plugin never read it. That
  covers a misspelling (`fanout` for `fan_out`) and an option that doesn't
  apply to the chosen mode (`mean` with `distribution: constant`). The
  error names the plugin and the option it most likely meant:

  ```
  plugin_configs.GossipBehavior: option(s) ['fanout'] had no effect --
  GossipBehavior never read them, so it ran on its defaults instead.
  Did you mean 'fan_out'?
  ```

- a value is invalid for its plugin (a negative delay, an unknown
  distribution, a churn event in the past).

An empty section (`GossipProtocol: {}`) is fine.

Time is in abstract **virtual-time units**. Pick a meaning and use it
consistently: the Raft examples use milliseconds, the gossip examples use
rounds.

## 4. Activation: synchronous or event-driven

**`synchronous`** (default). Every agent steps on every tick, in id order,
with the messages that arrived since its last step. This is a round-based
simulator: gossip rounds, epidemic days, flooding.

**`event`**. Agents run only when something happens to them:

- once at t=0 (bootstrap), where they typically set their first timers;
- when messages reach them (all messages arriving at the same instant are
  handed over as one batch);
- when a timer they set fires.

Ticks keep happening in event mode, but only to sample metrics. Use event
mode for timeouts, heartbeats, Poisson clocks and anything else that
depends on *when* things happen.

Each behavior declares the modes it supports, and a config asking for any
other mode is rejected at load:

| Behavior | synchronous | event |
|---|:-:|:-:|
| `GossipBehavior`, `LeaderElectionBehavior`, `SirEpidemicBehavior` | ✓ | |
| `AsyncGossipBehavior`, `RaftElectionBehavior`, `QueueBehavior` | | ✓ |

At a single instant the order is always: churn changes → message
deliveries → agent wakes → timers → the metric tick. So a heartbeat
arriving exactly when an election timer is due is processed first and can
cancel it, and an agent that fails at time t never receives messages
arriving at t.

## 5. Latency and loss

Without a latency protocol every message takes exactly one
`tick_interval`. `LatencyProtocol` gives every delivery its own delay:

```yaml
plugins:
  communication: "simul8.plugins.communication.latency.LatencyProtocol"
plugin_configs:
  LatencyProtocol:
    distribution: exponential    # constant | uniform | exponential | lognormal
    mean: 4.0
    loss_probability: 0.05
```

- **Event mode:** messages arrive at exactly send time + delay, so they can
  arrive out of order.
- **Synchronous mode:** a message is seen at the first tick at or after it
  arrives, so delays round **up** to whole ticks (2.5 ticks → the third
  tick). The distribution is exact inside the protocol and quantized in
  the run.

Messages due after `max_virtual_time` are never delivered.

## 6. Churn: failures, recoveries, joins, rewiring

Add `plugins.dynamics` to change the network while the simulation runs.

| Change | What happens |
|---|---|
| **fail** | A silent crash. The agent stops running and loses its inbox and timers. Messages reaching it are lost and counted. Neighbors are *not* told; they find out through timeouts, as in real systems. |
| **recover** | The agent returns with the state it had when it failed. In event mode the behavior's `on_recover` runs (Raft comes back as a follower but keeps its term and vote). In synchronous mode it simply steps again at the next tick. |
| **join** | A new agent, initialized exactly as it would have been at t=0 (same seed-derived RNG). |
| **add_edges / remove_edges** | Undirected links appear or disappear. |

A graceful leave is `fail` plus `remove_edges` in the same event.

**Scripted faults** (`ScheduledChurn`). Selectors are resolved at the
event's time, so you can target an agent by its state:

```yaml
plugin_configs:
  ScheduledChurn:
    events:
      - {at: 1000, fail: {where: {role: leader}}}   # whoever leads at t=1000
      - {at: 2500, recover: all}
      - {at: 3000, join: [5, 6], add_edges: [[5, 0], [6, 1]]}
```

**Random faults** (`RandomChurn`). Each running agent fails at
`failure_rate` and each failed one recovers at `recovery_rate`, as
independent Poisson processes. In the long run a fraction
`failure_rate / (failure_rate + recovery_rate)` is down.

Add `ChurnMetric` to record how many agents are running and how many
messages were lost, and `ConsensusMetric` to tell "the running agents
agree" apart from "every agent agrees" for averaging behaviors. Churn draws from its own random stream, so adding it
never changes the protocol's random draws.

Churn does **not** yet model network partitions or one-way links:
`remove_edges` cuts a link, but messages already in flight across it still
arrive.

## 7. Plugin reference

All paths start with `simul8.plugins.`. Options go under
`plugin_configs.<ClassName>`; defaults are in parentheses.

### Behaviors (`behaviors.*`)

| Class | Model | Options |
|---|---|---|
| `gossip_behavior.GossipBehavior` | Synchronous push gossip: each tick, average own value with received values, push to `fan_out` random neighbors. State: `value`. | `initial_value_range` ([0, 1]), `fan_out` (3) |
| `async_gossip.AsyncGossipBehavior` | Boyd et al. (2006) randomized pairwise averaging on Poisson clocks. Event mode. State: `value`. | `clock_rate` (1.0), `initial_value_range` ([0, 1]) |
| `leader_election.LeaderElectionBehavior` | Max-id flooding: adopt and rebroadcast the largest candidate id seen. | none |
| `raft_election.RaftElectionBehavior` | Raft leader election (§5.2): terms, randomized timeouts, votes, heartbeats. No log replication. Event mode. Needs a complete graph (`ErdosRenyiTopology` with `edge_probability: 1.0`). State: `role`, `term`, `voted_for`, `votes`, `leader_id`. | `election_timeout_min` (150), `election_timeout_max` (300), `heartbeat_interval` (50), `initial_leader` (none: cold start) |
| `queue.QueueBehavior` | Single-server FIFO queue: agent `server` serves customers for exponential times; each of its neighbors sends customers as a Poisson process. With constant latency this is the M/M/1 queue. Event mode. | `arrival_rate` per source (0.8), `service_rate` (1.0), `server` (0) |
| `sir_behavior.SirEpidemicBehavior` | SIR epidemic. S→I with probability 1−(1−β)^k for k infected neighbors; I→R with probability γ per tick. State: `status`. | `transmission_rate` β (0.2), `recovery_rate` γ (0.1), `initial_infected` (1) |

### Communication protocols (`communication.*`)

| Class | Delivery | Options |
|---|---|---|
| `gossip.GossipProtocol` | Lossless, one tick. | none |
| `broadcast.BroadcastProtocol` | Identical to `GossipProtocol`; kept so older configs load. | none |
| `lossy.LossyProtocol` | One tick, each delivery dropped independently. | `loss_probability` (0.1). The old `mode` option is rejected: recipients come from the message. |
| `latency.LatencyProtocol` | Per-delivery random delay, plus loss (section 5). | `distribution` (`constant`); `delay` for constant (one tick); `low`, `high` for uniform; `mean` for exponential; `mu`, `sigma` for lognormal (median = e^mu); `loss_probability` (0.0) |

Protocols never decide *who* receives a message, only whether and when. So
any behavior works with any protocol.

### Topologies (`topologies.*`)

| Class | Graph | Options |
|---|---|---|
| `ring.RingTopology` | Cycle, degree 2. | none |
| `grid.GridTopology` | 2-D grid, ⌊√n⌋ columns, 4-neighborhood. | `wrap` (true: torus) |
| `random_graph.ErdosRenyiTopology` | G(n, p). `1.0` gives a complete graph. | `edge_probability` (0.01) |
| `watts_strogatz.WattsStrogatzTopology` | Small world: ring lattice of degree k, rewired. | `k` (4, even), `rewire_probability` (0.1) |
| `barabasi_albert.BarabasiAlbertTopology` | Scale-free, preferential attachment. | `m` (2) |

### Metrics (`metrics.*`)

None take options. The series name is the file suffix in the output.

| Class | Series | Records |
|---|---|---|
| `message_count.MessageCountMetric` | `message_count` | Cumulative messages delivered |
| `convergence.ConvergenceMetric` | `convergence_variance` | Variance of agents' `value` at each tick |
| `consensus.ConsensusMetric` | `consensus` | Under churn: variance of `value` among running agents, tagged with the variance among all agents (crashed ones at their frozen value), the running mean, and its drift from the true initial mean |
| `sir_metrics.SirSusceptibleMetric` / `SirInfectedMetric` / `SirRecoveredMetric` | `sir_susceptible` / `sir_infected` / `sir_recovered` | Count per state at each tick |
| `leader_metrics.LeaderConsensusMetric` | `leader_consensus_fraction` | Fraction of agents that know the true maximum id |
| `raft_metrics.RaftElectionMetric` | `raft_elections` | One row per election at its exact time (value = term); an extra `SAFETY_VIOLATION` row if a term ever gets two leaders |
| `churn_metrics.ChurnMetric` | `churn` | Agents running at each tick, tagged with messages lost and agents down |
| `state_trace.StateTraceMetric` | `state_trace` | Every agent's state at every change (large; used by `visualize`) |
| `state_trace.TopologyMetric` | `topology` | The edge list (used by `visualize`) |
| `queue_metrics.QueueMetric` | `queue` | For `QueueBehavior`: each customer's wait in queue (with time in system), and per tick the integral of the number in system, so any window's time-average can be computed |
| `trace_digest.TraceDigestMetric` | `trace_digest` | SHA-256 fingerprint of the whole run so far, per tick (section 9) |

### Churn (`dynamics.*`)

| Class | Options |
|---|---|
| `scheduled.ScheduledChurn` | `events`: list of `{at, fail, recover, join, add_edges, remove_edges}`. `at` > 0 and strictly increasing. A selector is a list of ids, `{where: {key: value}}`, or `all`. A selector matching nobody does nothing. |
| `random_churn.RandomChurn` | `failure_rate` (0.01), `recovery_rate` (0.1; 0 = permanent), `max_failed` (no limit), `start_after` (0) |

### Persistence (`persistence.*`)

| Class | Output |
|---|---|
| `csv_exporter.CsvExporter` | One CSV per metric, into the `--output` directory |

## 8. What a run writes

Into the output directory:

- **`{experiment}_{metric}.csv`** for each metric. Each file is
  self-describing: a `#` comment header records the experiment name, seed,
  schema version and metric name.

  ```
  # experiment: sir_random
  # seed: 9876
  # schema_version: 1.0
  # metric: sir_infected
  virtual_time,value
  0.0,2.0
  1.0,5.0
  ```

- **`summary.json`** and **`summary.md`**: the complete resolved config
  (every simulation setting with defaults filled in, every plugin, every
  plugin option), plus wall-clock runtime and the list of files written.
  The summary alone is enough to re-run the experiment.

## 9. Reproducibility

The same config and seed produce the **same run, bit for bit**, on Python
3.10–3.13 and on Linux, macOS and Windows. CI checks this on every push.

To prove a result is reproducible, add `TraceDigestMetric` and publish the
final digest with it. Anyone who re-runs your config gets the same digest
only if every delivered message and every state change was identical. If
two runs differ, the first tick where their digest series differ is where
they diverged.

## 10. Examples

All in `examples/`. Each finishes in a few seconds at most.

| File | What it shows |
|---|---|
| `gossip_1000_agents.yaml` | Gossip averaging, 1,000 agents on Erdős–Rényi |
| `gossip_random.yaml`, `gossip_ring.yaml` | Gossip on a random graph vs. a ring |
| `async_gossip_ring.yaml` | Boyd et al.'s asynchronous gossip, event mode, with latency |
| `leader_random.yaml` | Max-id flooding election |
| `sir_random.yaml` | SIR epidemic on a random graph |
| `raft_election.yaml` | Raft election on a 5-node cluster |
| `raft_leader_crash.yaml` | Raft Fig. 16 scenario: crash the leader at t=1000, restart it at t=2500 |

For studies built from these, with their data and scripts, see
[`experiments/`](../experiments/) and the "By the numbers" section of the
[README](../README.md#by-the-numbers).
