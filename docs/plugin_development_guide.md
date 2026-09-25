# Writing Plugins for Simul8

This is the guide for adding new research code to Simul8 — a new behavior, network
topology, communication model, metric, or exporter. If you're extending the
*engine* itself, see [extended_documentation.md](extended_documentation.md) instead;
this document assumes the core is off-limits and you're working entirely in
`simul8/plugins/`.

## The one rule

> **The core never knows what it's simulating.**

Everything domain-specific — what an agent does, how messages travel, what the
network looks like, what gets measured, where results go — is a plugin behind
one of five abstract ports in `simul8/ports/`. A plugin implements exactly one
port, lives in `simul8/plugins/<category>/`, and is referenced from a YAML
config by its fully-qualified class path. That's the entire extension
mechanism — there are no entry points, registries, or decorators to remember.

## The plugin contract

Every plugin, regardless of which port it implements, must follow these rules.
They're not stylistic preferences — the first two are enforced by tests that
will fail your PR if violated.

1. **No imports from `simul8.core` or `simul8.app`. No exceptions.**
   Checked automatically by
   [`tests/unit/test_architecture_boundaries.py`](../tests/unit/test_architecture_boundaries.py),
   which resolves every import (absolute *and* relative) in every file under
   `simul8/` and enforces the full layering: plugins may use only `domain`
   and `ports`. This is what keeps the core portable (including the
   planned Rust port) and keeps a bad research idea from being able to touch
   the scheduler. If your plugin needs something the port doesn't give it,
   that is a missing port feature — raise it, don't reach around it. (An
   earlier version of this test only matched absolute imports, and two
   metrics used `from ...core import` to receive the live, mutable agent
   registry for months without it noticing.)

2. **Zero-argument `__init__`.**
   `PluginLoader` (`simul8/app/plugin_loader.py`) instantiates every plugin
   class with no constructor arguments — `cls()`. Configuration is *never*
   passed to `__init__`; it arrives later through the port's `initialize()` (or
   `route()`/`generate()`) method as a `config: dict[str, Any]` sourced from
   `plugin_configs.<ClassName>` in the YAML file.

3. **Determinism.** Same seed + same inputs must always produce the same
   output, regardless of scale or concurrency. Concretely:
   - Only use the `rng: random.Random` instance the engine hands you. Never call
     the global `random` module, `time.time()`, or any other non-seeded source.
   - When iterating a `set` or `frozenset` (e.g. `neighbors`), sort it first.
     Python's set iteration order is not guaranteed across runs — `GossipBehavior`
     does this (`sorted_neighbors = sorted(neighbors)`) before sampling.
   - Per-agent randomness is already seeded correctly for you by
     `RandomnessManager` as `seed XOR agent_id` — don't re-seed it yourself.
   - Reduce floats with `math.fsum`, never builtin `sum()`. CPython 3.12
     changed `sum()` of floats to a compensated algorithm, so the same code
     gives different last bits on 3.11 and 3.12 — and in an iterated
     simulation those bits compound into a different run. `fsum` is
     correctly rounded, hence identical on every version and for any input
     order. This isn't hypothetical: every `GossipBehavior` run used to
     differ between 3.11 and 3.12 with the same seed. Integer sums (counts)
     are exact and fine with `sum()`.

4. **Referenced by dotted path.** A plugin is wired into an experiment purely
   by its import path as a string, e.g.
   `simul8.plugins.behaviors.gossip_behavior.GossipBehavior`. There's no
   separate registration step — if the class exists, is importable, and
   subclasses the right port, it works.

5. **Behaviors and protocols: respect the addressing contract.**
   A behavior either addresses each message itself (`broadcast=False`) *or*
   asks for its whole neighborhood (`broadcast=True`) — never both. A
   protocol decides *whether and when* a message arrives, never *who else*
   receives it. Full rules and the reasoning are in
   [CommunicationProtocolPort](#communicationprotocolport--how-a-sent-message-actually-gets-delivered)
   below; `tests/unit/plugins/test_addressing_contract.py` enforces it
   across every behavior × protocol pair automatically, including yours.

## The five ports

| Port | Directory | One instance per... | Existing examples |
|---|---|---|---|
| `BehaviorPort` | `simul8/plugins/behaviors/` | experiment (shared across all agents) | `GossipBehavior`, `LeaderElectionBehavior`, `SirEpidemicBehavior` |
| `CommunicationProtocolPort` | `simul8/plugins/communication/` | experiment | `GossipProtocol`, `BroadcastProtocol`, `LossyProtocol` |
| `TopologyGeneratorPort` | `simul8/plugins/topologies/` | experiment (called once) | `RingTopology`, `ErdosRenyiTopology`, `GridTopology`, `BarabasiAlbertTopology`, `WattsStrogatzTopology` |
| `MetricCollectorPort` | `simul8/plugins/metrics/` | metric, per experiment | `MessageCountMetric`, `ConvergenceMetric`, `SirInfectedMetric`, `LeaderConsensusMetric`, `StateTraceMetric` |
| `PersistencePort` | `simul8/plugins/persistence/` | experiment | `CsvExporter` |

Full method signatures and contracts are documented in each port file's
docstring (`simul8/ports/*.py`) — read the port before implementing it, the
docstrings are the actual spec. Summary of what each one is for:

### BehaviorPort — what an agent does

```python
initialize(agent_id, config, rng) -> AgentState   # once per agent, at t=0
step(agent_id, current_state, inbox, neighbors, virtual_time) -> BehaviorResult
```

One shared instance handles every agent — per-agent state lives in the
`AgentState` you return, not on `self`. Per-agent RNGs, if you need to reuse
them in `step()`, should be stored in a `dict[AgentId, Random]` during
`initialize()` (see `GossipBehavior._agent_rngs`).

#### Activation modes and timers

By default an experiment is **synchronous**: every agent's `step()` runs on
every tick. Set `simulation.activation: event` and agents instead run only
when something happens to them:

- **bootstrap:** `step()` once per agent at t=0 with an empty inbox, in id order;
- **messages:** `step()` with every message that reached the agent at that
  instant, as one batch in delivery order;
- **timers:** `on_timer(agent_id, state, tag, neighbors, time)` when a timer
  the agent set expires.

Ticks keep happening in event mode, but only to pace metric sampling.

A behavior declares which modes it was written for:

```python
class MyBehavior(BehaviorPort):
    activation_modes = frozenset({"event"})   # default: {"synchronous"}
```

An experiment that asks for any other mode is **rejected when it loads**. A
tick-driven behavior run under event activation wouldn't crash. It would
step once at t=0, never run again, and report a protocol that "never
converged", so the loader refuses rather than letting that happen.

Timers go in the `BehaviorResult`:

```python
return BehaviorResult(
    next_state=state,
    set_timers=[Timer("election", rng.uniform(150, 300))],  # simul8.domain.timer
    cancel_timers=frozenset({"heartbeat"}),
)
```

- **One pending timer per (agent, tag).** Setting a pending tag replaces it,
  so "reset the election timeout" is just setting it again. Cancels are
  applied before sets, so cancelling and setting a tag in one result
  restarts it.
- **Messages beat timers at the same instant.** A heartbeat arriving exactly
  when an election timeout is due is processed first and can cancel it.
- A timer delay must be finite and > 0, and large enough to actually
  advance virtual time. Timers under synchronous activation are an error.
- Timers and messages due after `max_virtual_time` are never delivered.

### CommunicationProtocolPort — how a sent message actually gets delivered

```python
initialize(topology, config, rng) -> None      # once, after topology is built
route(message, sender_id, topology) -> list[tuple[AgentId, Message]]
```

The behavior decides *what* to send and *who it's addressed to*; the protocol
decides whether and when it arrives — loss, latency, duplication. Crucially,
**a protocol never invents recipients**:

| `Message.broadcast` | Behavior says | Protocol may deliver to |
|---|---|---|
| `False` (default) | "send this to *this* neighbor" | `recipient_id`, or nobody (dropped) |
| `True` | "expose my whole neighborhood" | any subset of `neighbors(sender_id)` |

This one flag is what makes **any behavior safe to pair with any protocol**.
Pick the mode that matches your algorithm:

- **Enumerating neighbors yourself** (you choose *which* ones — gossip's
  random fan-out, leader election's flood): emit one message per target with
  `broadcast=False`. `GossipBehavior` and `LeaderElectionBehavior` do this.
- **Wanting the whole neighborhood** without caring who's in it (epidemic
  exposure): emit **one** message with `broadcast=True` and let the protocol
  enumerate. `SirEpidemicBehavior` does this.

> **Do not do both.** Enumerating neighbors *and* relying on protocol fan-out
> multiplies deliveries by the sender's degree. It doesn't crash — it silently
> inflates effective rates. This exact bug shipped in `SirEpidemicBehavior`
> and skewed an epidemic curve ~28% before an external cross-check against
> NDlib caught it. `tests/unit/plugins/test_addressing_contract.py` now sweeps
> every behavior × protocol pair and will fail if it returns.

**Latency.** Return `Delivery(recipient_id, message, delay)` instead of a
bare `(recipient_id, message)` tuple to choose each copy's delay, in
virtual-time units. `None` means the default of one tick. A delay must be
finite and strictly greater than zero; the engine rejects anything else with
an error naming your protocol. Under synchronous activation delays round
**up** to whole ticks, so 2.5 arrives at the third tick after sending.
`LatencyProtocol` covers the common distributions, so check it before
writing your own.

### TopologyGeneratorPort — the agent network graph

```python
generate(agent_ids, config, rng) -> TopologyGraph
```

Must be a pure function and must place every agent ID in the returned
adjacency (even isolated agents, with an empty neighbor set). Called once, the
result is immutable for the run.

### MetricCollectorPort — one measurement, collected over time

```python
subscribed_events() -> frozenset[type[Event]]   # must be stable across calls
on_event(event, virtual_time) -> None            # must never raise
get_series() -> MetricSeries
reset() -> None
```

Plus one optional hook:

```python
on_setup(topology, initial_states) -> None       # once, before the first event
```

Override it when a metric needs something no event carries — the graph
structure (`TopologyMetric`) or a value derived from every agent's starting
state (`LeaderConsensusMetric` finds the true maximum id this way). You get
the immutable `TopologyGraph` and a read-only `{agent_id: state}` mapping,
never the core objects behind them. A collector that still defines the old
`configure()` hook is rejected at startup with an error, rather than being
silently skipped.

`MetricsEngine` only delivers events you subscribe to, so declare the
narrowest set that gives you what you need. `on_event` must not raise —
log and continue instead of throwing, or you can silently stop the whole
metrics pipeline mid-run.

### PersistencePort — where results go after the run

```python
write(series, config, output_dir) -> list[Path]
```

Must be idempotent (safe to call twice) and must embed experiment metadata
(name, seed, schema_version) in the output so a result file is
self-describing without its originating config. `CsvExporter` writes this as
a comment header — follow that convention for new exporters.

## Wiring a new plugin into an experiment

Nothing beyond the YAML config changes. If you added
`simul8/plugins/behaviors/random_walk.py` with class `RandomWalkBehavior`:

```yaml
schema_version: "1.0"

experiment:
  name: "random_walk_demo"
  seed: 7

simulation:
  num_agents: 50
  max_virtual_time: 100
  tick_interval: 1

plugins:
  behavior: "simul8.plugins.behaviors.random_walk.RandomWalkBehavior"
  communication: "simul8.plugins.communication.broadcast.BroadcastProtocol"
  topology: "simul8.plugins.topologies.grid.GridTopology"
  metrics:
    - "simul8.plugins.metrics.state_trace.StateTraceMetric"
  persistence:
    - "simul8.plugins.persistence.csv_exporter.CsvExporter"

plugin_configs:
  RandomWalkBehavior:
    step_size: 1.0
  GridTopology:
    width: 10
    height: 5
```

`plugin_configs.<ClassName>` is looked up by class name and handed to your
plugin's `initialize()`/`generate()`/`route()` as a plain `dict`. Missing keys
should fall back to sane defaults in code (see `GossipBehavior.initialize`) —
`ConfigLoader` only validates the top-level required fields
(`experiment.name`, `experiment.seed`, `simulation.num_agents`,
`simulation.max_virtual_time`, `plugins.behavior/communication/topology`), not
the contents of `plugin_configs`. Run it with:

```bash
simul8 run examples/random_walk_demo.yaml --output ./results
```

## Testing your plugin

Plugin unit tests live in `tests/unit/plugins/test_<name>.py` and construct
the plugin directly — no engine, no YAML, no experiment runner involved.
Instantiate the class, call its port methods with hand-built domain objects
and a seeded `random.Random(<seed>)`, and assert on the result. See
`tests/unit/plugins/test_topologies.py` and `test_lossy_communication.py` for
the pattern:

```python
import random
from simul8.domain.ids import AgentId
from simul8.plugins.topologies.ring import RingTopology

def test_every_agent_has_two_neighbors():
    ids = [AgentId(i) for i in range(10)]
    g = RingTopology().generate(ids, {}, random.Random(0))
    for aid in ids:
        assert g.degree(aid) == 2
```

For anything with real dynamics (a new behavior or full experiment), add an
integration or regression test alongside the existing
`tests/integration/test_gossip_experiment.py` /
`tests/regression/test_gossip_1000_agents.py` — run a small experiment
end-to-end through `ExperimentRunner` and assert on the resulting metrics,
not just on isolated method calls.

## Before opening a PR

- [ ] Module docstring states what the plugin does and documents its
      `plugin_configs` keys with defaults (see any existing plugin for the format).
- [ ] Zero-argument `__init__`; no imports from `simul8.core` or `simul8.app`.
- [ ] All randomness goes through the `rng` argument; any set/frozenset
      iteration is sorted first.
- [ ] Unit tests added under `tests/unit/plugins/`.
- [ ] `python -m pytest -q` passes; `python -m pytest -m "not slow"` if you
      only want the fast subset.
- [ ] If it's a new experiment type worth demonstrating, add an example config
      under `examples/`.

Two contract tests pick up your plugin automatically — you don't register it
anywhere, but you do have to pass them:

- [ ] **Behaviors and protocols:** `test_addressing_contract.py` pairs your
      plugin with every counterpart and asserts each intended neighbor gets
      exactly one delivery under a lossless protocol. A failure here usually
      means you enumerated neighbors *and* set `broadcast=True`.
- [ ] **Topologies:** `test_topology_complexity.py` asserts generation doesn't
      scale quadratically. A failure here usually means an O(n) scan over
      `agent_ids` nested inside a per-node loop — reach for rejection sampling
      or direct edge sampling instead.
- [ ] **Behaviors, protocols, topologies:** `tests/regression/test_golden_traces.py`
      runs every behavior × protocol × topology and pins a fingerprint of
      the entire run. A *new* plugin fails it until recorded — run
      `pytest tests/regression/test_golden_traces.py --update-golden` and
      commit the JSON diff. An *existing* plugin failing it means your change
      altered someone's simulation; the failure names the first tick that
      diverged.
- [ ] **Any committed `.py` file:** `test_experiment_script_portability.py`
      fails on a hardcoded absolute path (`/home/...`, `/tmp/...`, a Windows
      drive). Derive the repo root from `Path(__file__)`, write outputs next
      to the script, and make scratch locations overridable by environment
      variable. This one exists because ten committed experiment scripts
      hardcoded one developer's home directory while their READMEs told
      readers to "run it yourself" — they ran fine on the machine they were
      written on, which is precisely why it went unnoticed.
