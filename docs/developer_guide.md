# Simul8 Developer Guide

How Simul8 works inside, and how to extend it: writing plugins, the rules
they must follow, and the tests that enforce those rules. To run
experiments with existing plugins, see the [User Guide](user_guide.md). For
why the engine is built this way, see [Design](design.md).

## Contents

1. [Architecture](#1-architecture)
2. [How a run executes](#2-how-a-run-executes)
3. [Determinism rules](#3-determinism-rules)
4. [Writing a plugin](#4-writing-a-plugin)
5. [The ports](#5-the-ports)
6. [Testing](#6-testing)
7. [Before opening a PR](#7-before-opening-a-pr)

## 1. Architecture

> **The core never knows what it's simulating.**

Simul8 uses a hexagonal (ports-and-adapters) architecture. The engine
handles agents, virtual time, events, message routing and metric dispatch.
Everything domain-specific is a plugin behind an abstract port.

```
simul8/
├── domain/    Data only: Agent, Message, Event, AgentState, TopologyGraph,
│              Delivery, Timer, TopologyChange, MetricSeries, portable_math
├── ports/     Abstract contracts: BehaviorPort, CommunicationProtocolPort,
│              TopologyGeneratorPort, MetricCollectorPort, PersistencePort,
│              TopologyDynamicsPort
├── core/      The engine: SimulationEngine, Scheduler, EventQueue,
│              TimeManager, AgentRegistry, TopologyManager,
│              CommunicationLayer, MetricsEngine, RandomnessManager
├── app/       Orchestration: ConfigLoader, PluginLoader, ExperimentRunner
├── plugins/   behaviors/ communication/ topologies/ metrics/
│              persistence/ dynamics/
└── cli/       simul8 run, simul8 visualize
```

**Allowed imports**, enforced by `tests/unit/test_architecture_boundaries.py`
(absolute and relative imports, every file):

| Layer | May import |
|---|---|
| `domain` | nothing in `simul8` |
| `ports` | `domain` |
| `core` | `domain`, `ports` |
| `plugins` | `domain`, `ports` |
| `app` | `domain`, `ports`, `core` |
| `cli` | `app`, `domain` |

### Core components

| Component | Responsibility |
|---|---|
| `SimulationEngine` | The event loop: pops events, advances time, runs behaviors, routes their messages, manages timers and churn, dispatches events to metrics. |
| `Scheduler` / `EventQueue` | A min-heap ordered by `(virtual_time, priority, event_id)`, with lazy cancellation. Scheduling in the past is an error. |
| `TimeManager` | Virtual time, which only moves forward. |
| `AgentRegistry` | Which agents exist and their current state. |
| `TopologyManager` | The current graph. Churn replaces it copy-on-write, and graphs are never mutated. |
| `CommunicationLayer` | Calls the protocol, normalizes and validates what it returns, and counts messages sent, delivered and lost. |
| `MetricsEngine` | Sends each event only to the collectors that subscribed to its type. |
| `RandomnessManager` | Per-agent RNGs (`Random(f"{seed}/agent/{id}")`) and named streams (`Random(f"{seed}/stream/{name}")`) for plugins such as churn. |

## 2. How a run executes

`ExperimentRunner.run(config_path, output_dir)`:

1. `ConfigLoader` parses and validates the YAML into a frozen `ExperimentConfig`.
2. `PluginLoader` imports each class path, checks it subclasses the right
   port and instantiates it with no arguments.
3. The behavior must list the configured activation mode in its
   `activation_modes`, or the run stops here.
4. Agents are created in id order, and `behavior.initialize()` runs with
   each agent's RNG.
5. The topology is generated, the protocol is initialized with it and
   metrics get `on_setup(topology, initial_states)`.
6. The dynamics plugin, if any, is initialized with its own RNG stream.
   Each plugin gets its `plugin_configs` section as a `TrackedConfig`.
   After setup, an option no plugin read is an error, as is a section that
   names no plugin in the run.
7. The engine runs until the queue is empty or `max_virtual_time` is passed.
8. Metric series go to the persistence plugins, then `summary.json` and
   `summary.md` are written.

### Event priorities

When events share a virtual time, the lower priority number runs first:

| Priority | Event | Why this position |
|---:|---|---|
| −1 | Topology change (churn) | An agent failing at t must not receive messages or run at t. |
| 0 | Message delivery | Every message due at t is in the inbox before anyone runs. |
| 1 | Agent wake (event mode) | One `step()` per agent per instant, with the complete batch. |
| 2 | Timer | Messages beat timers: a heartbeat at t can cancel a timeout due at t. |
| 3 | Tick | Synchronous mode steps every agent here; in event mode ticks only sample metrics. |

`event_id` breaks the remaining ties in scheduling order, so the whole
order is deterministic.

### Synchronous mode

At each tick every running agent's `step()` runs in id order with its
inbox. Messages it sends are scheduled for the first tick at or after
send time + delay. That tick time comes from the engine's own list of
generated tick times, never computed as `now + k*dt`, so float rounding
can't delay a message by an extra tick.

### Event mode

- **Bootstrap:** `step()` once per agent at t=0 with an empty inbox.
- **Delivery:** the message joins the agent's pending inbox and a wake is
  scheduled for that instant, unless one already is. The wake runs
  `step()` with the whole batch.
- **Timers:** `BehaviorResult.set_timers` / `cancel_timers`. There is at
  most one pending timer per (agent, tag). Setting a pending tag replaces
  it, and cancels apply before sets. Superseded timers never fire and are
  never shown to metrics.
- A delay that doesn't advance virtual time (for example `5.0 + 1e-20 ==
  5.0`) is rejected, because it would make an effect simultaneous with its
  cause.

### Churn

The engine asks the dynamics plugin `next_time()`, schedules a topology
change event then, and calls `change()` at that moment with read-only agent
states. A failed agent's inbox and timers are dropped, and messages to it
are reported as `MessageLostEvent`. Metrics see a change before its
consequences: a recovering agent is reported recovered before it runs.
Protocols are told about edge changes through `on_topology_changed()`.

## 3. Determinism rules

The same seed must give the same run, bit for bit, on every supported
Python and OS. These rules apply to all code in `domain`, `core` and
`plugins`:

- **Use only the RNG you're given.** Never use the global `random` module,
  `time.time()` or any other unseeded source. Don't reseed.
- **Sort sets before iterating** when order affects the outcome. For
  example, `sorted(neighbors)` comes before `rng.sample`.
- **Reduce floats with `math.fsum`, never `sum()`.** CPython 3.12 changed
  `sum()` of floats, and every gossip run used to differ between 3.11 and
  3.12. `fsum` is correctly rounded, so it gives the same answer on every
  version and for any input order. Integer sums are fine.
- **Use `simul8.domain.portable_math` for transcendental math:** `log`,
  `exp`, `ipow`, `expovariate(rng, rate)`, `normalvariate`,
  `lognormvariate`. IEEE 754 fixes only `+ − × ÷ √`. `math.log`, `exp`,
  `pow`, float `**`, and `rng.expovariate` or `gauss` come from each OS's C
  library, and their last bits differ. In event mode those bits are event
  times, which is how golden traces recorded on Linux first failed on
  macOS and Windows. `rng.random`, `uniform`, `choice`, `sample` and
  `shuffle` are portable. Mark genuinely integer `**` with
  `# portable: int`.
- **Values in state and payloads need a deterministic `repr`**, because
  `TraceDigestMetric` serializes them.

## 4. Writing a plugin

A plugin is a class in `simul8/plugins/<category>/` that subclasses one
port. A config references it by dotted path. There is nothing to register.

1. **Import only `simul8.domain` and `simul8.ports`.** If you need something
   the port doesn't give you, the port is missing a feature; raise it rather
   than reaching into `core`. (Two metrics once did `from ...core import`
   to get the live agent registry, and the boundary test at the time
   didn't see relative imports. It does now.)
2. **Zero-argument `__init__`.** Configuration arrives later as
   `config: dict` in `initialize()` or `generate()`, from
   `plugin_configs.<ClassName>`. Missing keys fall back to defaults in code.
   **Read every option during that call**, not later: the runner records
   which options each plugin reads during setup and rejects any it never
   read (a typo, or an option for another mode). Only read the options
   that apply, too. A plugin that did `config.get("mean")` even with
   `distribution: constant` would stop that mistake being caught. Reject
   invalid values with a `ValueError` that names your plugin, so a run
   never fails partway through.
3. **Follow the determinism rules** in section 3.
4. **Document the plugin in its module docstring:** what it models, which
   activation modes it supports, and each `plugin_configs` key with its
   default. Copy the format of any existing plugin.

A minimal behavior:

```python
from simul8.domain.ids import MessageId
from simul8.domain.message import Message
from simul8.domain.state import AgentState
from simul8.ports.behavior import BehaviorPort, BehaviorResult

class CounterBehavior(BehaviorPort):
    """Each agent adds up what it receives and tells one neighbor its total.

    Configuration (plugin_configs.CounterBehavior):
        start: initial count (default 0)
    """

    def __init__(self) -> None:
        self._rngs = {}
        self._next_id = 0

    def initialize(self, agent_id, config, rng):
        self._rngs[agent_id] = rng
        return AgentState(data={"count": int(config.get("start", 0))})

    def step(self, agent_id, current_state, inbox, neighbors, virtual_time):
        count = current_state.get("count", 0) + sum(m.get("count", 0) for m in inbox)
        out = []
        if neighbors:
            target = self._rngs[agent_id].choice(sorted(neighbors))
            self._next_id += 1
            out.append(Message(MessageId(self._next_id), agent_id, target, {"count": count}))
        return BehaviorResult(next_state=current_state.with_value("count", count),
                              outbound_messages=out)
```

## 5. The ports

The docstrings in `simul8/ports/*.py` are the specification. What follows
summarizes each port.

### BehaviorPort: what an agent does

```python
activation_modes: frozenset[str] = frozenset({"synchronous"})    # or {"event"}, or both
initialize(agent_id, config, rng) -> AgentState
step(agent_id, current_state, inbox, neighbors, virtual_time) -> BehaviorResult
on_timer(agent_id, current_state, tag, neighbors, virtual_time) -> BehaviorResult  # event mode
on_recover(agent_id, current_state, neighbors, virtual_time) -> BehaviorResult    # event mode
```

- One instance serves every agent. Per-agent data lives in the `AgentState`
  you return, and per-agent RNGs go in a dict keyed by agent id.
- `BehaviorResult(next_state, outbound_messages=[], set_timers=[],
  cancel_timers=frozenset())`. Timers are `Timer(tag, delay)` from
  `simul8.domain.timer`, and a delay must be finite and > 0. Setting a timer
  in synchronous mode is an error.
- `on_timer` raises by default, so implement it if you set timers.
- `on_recover` defaults to a bootstrap step (`step()` with an empty
  inbox). Override it to drop whatever a real restart loses.
  `RaftElectionBehavior` keeps its term and vote but comes back as a
  follower, because forgetting a vote could elect two leaders in one term.

**Declare only the modes you were written for.** A tick-driven behavior run
in event mode wouldn't crash. It would step once at t=0, never again, and
report "never converged". The loader rejects it instead.

### CommunicationProtocolPort: whether and when a message arrives

```python
initialize(topology, config, rng) -> None
route(message, sender_id, topology) -> list[Delivery | tuple[AgentId, Message]]
on_topology_changed(topology) -> None     # churn changed the edges; refresh caches
```

**The addressing contract.** The behavior decides who a message is for,
and the protocol only decides whether and when it arrives:

| `Message.broadcast` | Protocol may deliver to |
|---|---|
| `False` (default) | `recipient_id`, or nobody |
| `True` | any subset of `neighbors(sender_id)` |

A behavior that picks its own targets sends one addressed message per
target. A behavior that wants the whole neighborhood sends **one** message
with `broadcast=True`. Never do both. That multiplies deliveries by the
degree without crashing, and it inflated SIR transmission by about 28%
until a cross-check against NDlib caught it.

**Latency.** Return `Delivery(recipient_id, message, delay)` from
`simul8.domain.delivery`. `None`, or a bare tuple, means one tick. A delay
must be finite and > 0, and the engine rejects anything else with an error
naming your protocol. Draw delays from the protocol's `rng`, in a fixed
order.

### TopologyGeneratorPort: the initial graph

```python
generate(agent_ids, config, rng) -> TopologyGraph
```

Must be pure and must include every agent in the adjacency, with an empty
set for isolated agents. It must not be quadratic; see section 6.

### MetricCollectorPort: one measured series

```python
subscribed_events() -> frozenset[type[Event]]     # stable across calls
on_setup(topology, initial_states) -> None         # optional; once, before the first event
on_event(event, virtual_time) -> None              # must never raise
get_series() -> MetricSeries
reset() -> None
```

Subscribe to as few event types as you need. The event types are in
`simul8/domain/event.py`: ticks, deliveries, state changes, timer firings,
topology changes and lost messages. `on_setup` gives read-only copies,
never the core objects.

### TopologyDynamicsPort: churn

```python
initialize(topology, config, rng) -> None                  # rng: a dedicated stream
next_time(topology, virtual_time, failed) -> float | None   # when to act next (> now), or never
change(topology, virtual_time, states, failed) -> TopologyChange
```

`TopologyChange(fail, recover, join, add_edges, remove_edges)` lives in
`simul8.domain.topology_change`. Edges are undirected. The constructor
rejects self-loops, an agent in more than one of fail, recover and join,
and an edge that is both added and removed. The engine rejects changes
that don't fit the current state, such as failing a failed agent or adding
an existing edge. Both errors name your plugin.

The port asks *when* and *what* separately, so that a change can depend on
the state at that moment ("crash whoever is leader now").

### PersistencePort: writing results

```python
write(series, config, output_dir) -> list[Path]
```

Must be idempotent and must embed the experiment name, seed and schema
version in its output, as `CsvExporter`'s comment header does.

## 6. Testing

```bash
pytest                    # everything, ~70 s
pytest -m "not slow"      # skip the slow scale tests
pytest tests/regression/test_golden_traces.py --update-golden   # re-record fingerprints
```

| Directory | Contents |
|---|---|
| `tests/unit/` | One component or plugin in isolation. No engine, no YAML. |
| `tests/integration/` | Real engine runs, with probe behaviors (`event_probes.py`, `latency_probes.py`) that record what they observe. |
| `tests/regression/` | Golden traces and 1,000-agent regression runs. |

Unit-test a plugin by calling its port methods directly with a seeded
`random.Random`:

```python
def test_every_agent_has_two_neighbors():
    ids = [AgentId(i) for i in range(10)]
    g = RingTopology().generate(ids, {}, random.Random(0))
    assert all(g.degree(a) == 2 for a in ids)
```

### Contract tests

Your plugin is covered by these suites without you listing it anywhere.
They discover plugins by walking the package.

| Test | Checks | Usual cause of failure |
|---|---|---|
| `tests/unit/plugins/test_addressing_contract.py` | Every behavior × protocol: each intended recipient gets exactly one delivery; delays are valid. Follows timers for event-driven behaviors. | Enumerating neighbors *and* setting `broadcast=True`. |
| `tests/unit/plugins/test_topology_complexity.py` | Generation time grows slower than n^1.7. | An O(n) scan inside a per-node loop. |
| `tests/integration/test_churn_contract.py` | Every behavior × mode × protocol under random churn: failed agents never run or receive messages. | Wrong `on_recover` for a timer-driven behavior. |
| `tests/regression/test_golden_traces.py` | Every behavior × protocol × topology × tick interval × activation mode, plus churn cells and every example, has a pinned SHA-256 fingerprint. | New plugin: not recorded yet, so run `--update-golden` and commit the JSON. Existing plugin: your change altered someone's simulation, and the failure names the first tick that differs. |
| `tests/unit/test_architecture_boundaries.py` | The import table in section 1. | Importing `core` from a plugin. |
| `tests/unit/test_portable_math_usage.py` | No `math.log`, `exp`, `pow`, float `**`, `rng.expovariate` or similar in core, domain or plugins. | Use `portable_math`. |
| `tests/unit/test_experiment_script_portability.py` | No committed `.py` file hardcodes an absolute path. | Build paths from `Path(__file__)`. |
| `tests/integration/test_plugin_configs.py` | For every configurable plugin role in `PluginsConfig`, a misspelled option is rejected; `summary.json` records every `ExperimentConfig` field. | Reading config outside setup; adding a config field the summary doesn't serialize. |

**Every guard is mutation-tested.** When you add a guard, break the code on
purpose and check that the guard fails. Several gaps were found this way:
- A reversed inbox order went unnoticed until the probe behavior was added.
- Superseded timers leaked to metrics.
- A failure paused timers instead of cancelling them.

**Fix bugs by class.** When you find a bug, fix the rule it broke and add a
guard that discovers future instances. Don't patch just the one simulation
where it showed up.

CI (`.github/workflows/tests.yml`) runs the full suite on Python
3.10–3.13 on Linux. A separate, required job runs the golden traces and
the `portable_math` known-answer tests on macOS and Windows.

## 7. Before opening a PR

- [ ] The module docstring says what the plugin models, which activation
      modes it supports and every config key with its default.
- [ ] Zero-argument `__init__`, and imports come only from `domain` and `ports`.
- [ ] All randomness comes from the given `rng`. Sets are sorted before
      order-dependent use. Float sums use `fsum`, and math goes through
      `portable_math`.
- [ ] Unit tests in `tests/unit/plugins/`. Behaviors with real dynamics
      also get an integration test.
- [ ] `pytest` passes. New plugins have their golden traces recorded, and
      the JSON diff contains only additions.
- [ ] New experiment types get an example in `examples/`.
- [ ] New experiment scripts go under `experiments/<study>/`, with a README
      and raw results next to them.
