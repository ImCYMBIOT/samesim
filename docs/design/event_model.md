# Design: Latency, Asynchronous Activation, and Churn

**Status:** Phase 0 **done**. Phases 1–3 are proposals; nothing in
`simul8/core` has changed for them yet.
**Scope:** the engine's time model. Three capabilities that the core cannot
express today, delivered in four independently shippable phases.

## 1. Why

Simul8 calls itself event-driven, but its agents run on a synchronous tick:

- [`engine.py` `_handle_tick`](../../simul8/core/engine.py) steps **every
  agent on every tick**, in creation order.
- Every message is delivered **exactly one tick later**
  (`delivery_time = T + tick_interval`), whatever the protocol wants.
- `TopologyGraph` is built once and never changes.

The event queue underneath is a real discrete-event scheduler
(`(virtual_time, priority, event_id)` min-heap), but only two kinds of event
ever enter it: `TickEvent` and `MessageDeliveredEvent`. As a result, three things that
distributed-systems research needs as a baseline can't be expressed:

| Capability | Why it matters | Blocked by |
|---|---|---|
| **Per-message latency** | Latency distributions, stragglers, partial synchrony | `route()` returns `(recipient, message)` with no time |
| **Asynchronous activation** | Raft/Paxos timeouts, heartbeats, Poisson-clock gossip, continuous-time epidemics | Agents run only on the global tick; they can't set timers |
| **Churn** | P2P membership, fault tolerance, link failure | Immutable topology, fixed agent set |

The first one is also a **spec/code contradiction**, the same kind of problem as the
addressing bug. [`ports/communication.py`](../../simul8/ports/communication.py)
says a protocol "decides whether **and when** a message arrives" and "may
drop a message, **delay it**, or deliver it", but no protocol can actually
delay a message. The contract promises more than the signature allows.

The scientific cost is concrete. The classical O(n²) averaging-time
bound for gossip on a ring (Boyd et al., 2006) is stated for *asynchronous
pairwise* gossip. Simul8 measured O(n) on a ring (slope 0.99). That result is
correct for the synchronous protocol it actually ran, but the tool can't run
the protocol the bound describes, so the theory can't be checked
directly. Phase 2 makes that check possible (see §7).

## 2. Design principles

These carry over the rules the audit established:

1. **Additive and backward compatible.** Every existing behavior, protocol,
   and YAML config must produce **bit-identical output** after each phase.
   Phase 0 exists to make that claim checkable instead of just stated.
2. **Incompatibility fails loudly at load time, never silently at run time.**
   A behavior that can't work under a given activation mode must be rejected
   by config validation with a message naming both plugins. The failure mode
   to avoid is the one that bit us before: a combination that runs, returns
   plausible numbers, and is wrong.
3. **Every new contract gets a contract test that discovers plugins by
   walking the package**, so the guard also covers plugins written later.
4. **Determinism is untouched.** All new randomness comes from the existing
   per-agent (`seed XOR agent_id`) or per-plugin RNG streams. The ordering key
   `(virtual_time, priority, event_id)` stays the only thing that sequences
   events.

## 3. Phase 0: lock current behavior (prerequisite)

Before any core change, record a **golden trace hash** for every config in
`examples/` plus the regression configs: a SHA-256 over every metric CSV and
the final agent states. `tests/regression/test_golden_traces.py` asserts
the hashes match.

Without this, "backward compatible" is a hope. With it, any refactor that
changes a single delivered message fails CI. The phase costs about a day, and
every later phase relies on it.

Regenerating the hashes is a deliberate act (`--update-golden`) that shows up
in review. It shouldn't happen as a side effect.

### As built

- **Fingerprint:** `TraceDigestMetric` (`simul8/plugins/metrics/trace_digest.py`)
  folds the topology, initial states, every delivered message and every
  state change into a running SHA-256, recorded per tick. Engine event ids
  are excluded so a pure refactor that renumbers events isn't flagged.
- **Coverage:** every behavior × protocol × topology (discovered, so new
  plugins are included automatically) at tick intervals 1.0 and 0.5, plus
  every file written by every example. 120 matrix cells + 5 examples, ~9 s.
- **A probe behavior** (`tests/regression/probes.py`) records its exact
  inbox (sender, message id, send time, addressing mode, in order) into
  its state. It was added after mutation-testing the guard. Reversing the
  engine's inbox order changed *no* trace, because no shipped behavior is
  order-sensitive on CPython 3.12. The guard's sensitivity can't depend on
  which plugins happen to exist, so the probe pins what the engine controls
  directly.
- **Mutation-tested:** reversed inbox order → 30 probe cells fail at
  t=1.0. Latency doubled only when `tick_interval != 1` → exactly the 45
  dt=0.5 cells fail and no dt=1.0 cell does.

### What Phase 0 found

Running the golden traces on Python 3.11 failed **every gossip run** (30
cells + 3 examples), while everything else matched. The cause is CPython 3.12
changing builtin `sum()` of floats to compensated summation.
`GossipBehavior` and `ConvergenceMetric` now use `math.fsum`, which is
correctly rounded and so identical on all versions. It also reproduces the
3.12 results exactly, so no recorded trace had to change. The full suite now
passes bit-identically on 3.10, 3.11, 3.12 and 3.13, and CI enforces that on
every push. The first CI run also confirmed the Linux-recorded golden
traces reproduce bit-for-bit on macOS and Windows, so that job is now
required too.

## 4. Phase 1: per-message latency

### API

`route()` may return a delay with each delivery:

```python
@dataclass(frozen=True)
class Delivery:
    recipient_id: AgentId
    message: Message
    delay: float | None = None   # virtual-time units; None = one tick_interval

def route(self, message, sender_id, topology) -> list[Delivery | tuple[AgentId, Message]]:
```

The engine normalizes a bare `(recipient, message)` tuple to
`Delivery(recipient, message, None)`, so **every existing protocol keeps
working unmodified**, and `None` reproduces today's timing exactly.

### Rules

- `delay` must be **finite and strictly positive**. A message can't
  arrive at the instant it was sent. That rules out zero-time livelock (two
  agents replying to each other forever without virtual time advancing) and
  removes a whole class of same-instant ordering questions. The engine
  raises `ValueError` naming the protocol on violation.
- In synchronous mode, a message sent at tick `T` with delay `d` is in the
  inbox at the **first tick ≥ `T + d`**. With the default `d =
  tick_interval`, that's the next tick, the current behavior. A delay of 2.5
  ticks lands at tick `T+3`, which is the documented quantization cost of
  synchronous activation.

### New plugin

`LatencyProtocol` with `distribution: constant | uniform | exponential |
lognormal` and its parameters, composed with a loss rate so it replaces
`LossyProtocol` as the general case. Delays are drawn from the protocol's
seeded RNG in delivery order, which is deterministic.

### Contract test

`test_delivery_contract.py` sweeps every protocol × a set of messages and
asserts every returned delay is `None` or finite and > 0, and that the
addressing contract still holds for the recipient set. It extends the
existing addressing sweep rather than duplicating it.

## 5. Phase 2: asynchronous activation and timers

### Activation modes

```yaml
simulation:
  activation: synchronous   # default: today's behavior, unchanged
  # activation: event       # agents wake on delivery or timer only
```

**`synchronous`** is the current semantics exactly.

**`event`**: agents don't run on the tick. An agent's behavior runs when:

1. **Bootstrap**: `step()` is called once per agent at `t=0` with an empty
   inbox, in agent-id order. This is where a behavior sets its first timers.
2. **Delivery**: messages arrive. All messages reaching one agent at the
   **same virtual instant** are batched into a single `step()` call.
3. **Timer**: a timer the agent set fires, which calls `on_timer()`.

`TickEvent` keeps firing every `tick_interval` in event mode, but only as a
**metric sampling clock**. Agents don't step on it, which keeps
`ConvergenceMetric` and other tick-sampled metrics working unchanged.

### Same-instant batching, using the existing ordering key

When a `MessageDeliveredEvent` for agent `a` at time `t` is dispatched in
event mode, the engine appends to `a`'s pending inbox and, unless one is
already pending, schedules an `AgentWakeEvent(a, t)` with **priority 1**.
Deliveries have priority 0, so the heap guarantees every delivery at `t`
is processed before any wake at `t`. The batch is complete by
construction, with no lookahead and no new ordering rules. That's the
reason the queue was built with a priority field.

### Timers

`BehaviorResult` gains two optional fields:

```python
@dataclass
class BehaviorResult:
    next_state: AgentState
    outbound_messages: list[Message] = field(default_factory=list)
    set_timers: list[Timer] = field(default_factory=list)       # new
    cancel_timers: frozenset[str] = frozenset()                  # new

@dataclass(frozen=True)
class Timer:
    tag: str        # e.g. "election", "heartbeat"
    delay: float    # finite, > 0
```

and `BehaviorPort` gains one non-abstract method:

```python
def on_timer(self, agent_id, current_state, tag, neighbors, virtual_time) -> BehaviorResult:
    raise NotImplementedError  # only reachable if the behavior set a timer
```

**At most one pending timer per `(agent, tag)`. Setting a tag that is
already pending replaces it.** Raft's "reset the election timeout on every
heartbeat" becomes "set `election` again", with no bookkeeping in the
plugin. Replacement uses the scheduler's existing `cancel(event_id)` (lazy
deletion), so it stays O(log n).

Timers are **rejected in synchronous mode** with a load-time error. Mixing
a global tick with sub-tick timers raises semantic questions this design
doesn't need to answer yet.

### Declaring compatibility

```python
class BehaviorPort(ABC):
    activation_modes: frozenset[str] = frozenset({"synchronous"})
```

`ConfigLoader` rejects a config whose `activation` isn't in the
behavior's `activation_modes`, with a message naming the behavior. The
default is `{"synchronous"}` because every existing behavior assumes it:
`GossipBehavior` in event mode would never send anything, since nothing
wakes it. Without the declaration it would run silently to completion and
report "no convergence", which is exactly the plausible-but-wrong
failure mode principle 2 rules out.

### New plugins

- `AsyncGossipBehavior`: each agent wakes on a Poisson clock (exponential
  timer, per-agent RNG), averages with one random neighbor. This is the
  protocol Boyd et al. analyze.
- `RaftElectionBehavior`: randomized election timeouts, heartbeats,
  terms. It's the canonical timer-driven algorithm and a recognizable
  benchmark for reviewers.

### Contract tests

- **Activation compatibility sweep**: every behavior × every mode it
  declares runs a short experiment to completion. Every mode it doesn't
  declare is rejected at config load, not at run time.
- **Event-mode determinism sweep**: every event-capable behavior, run twice
  with the same seed, produces identical golden-style trace hashes.
- **Batching**: N messages to one agent at one instant produce exactly one
  `step()` call with all N in the inbox.

## 6. Phase 3: churn

### Source of changes: a new optional port

```python
class TopologyDynamicsPort(ABC):
    def initialize(self, topology, config, rng) -> None: ...
    def next_change(self, topology, virtual_time) -> tuple[float, TopologyChange] | None:
        """Delay until the next change and the change itself, or None to stop."""

@dataclass(frozen=True)
class TopologyChange:
    add_agents: frozenset[AgentId] = frozenset()
    remove_agents: frozenset[AgentId] = frozenset()
    add_edges: frozenset[tuple[AgentId, AgentId]] = frozenset()
    remove_edges: frozenset[tuple[AgentId, AgentId]] = frozenset()
```

The engine keeps one `TopologyChangeEvent` in flight at a time. It asks
for the next change after applying the current one, so dynamics can react
to the evolving graph. The plugin is optional: omitted means a static
topology, which is today's behavior.

### Semantics

- **Departure**: the agent stops stepping and its timers are cancelled.
  **Messages in flight to it are dropped at delivery time and counted**
  (`messages_dropped_departed`), never silently discarded. Messages
  already sent *by* it still arrive, which matches real networks.
- **Arrival**: `behavior.initialize()` runs with the usual
  `seed XOR agent_id` RNG, so a joining agent is as reproducible as one
  present from the start. In event mode it gets a bootstrap `step()`.
- **Edges**: `neighbors` passed to `step()` is always the current set.
- **Protocols** gain a no-op-by-default hook `on_topology_changed(topology)`.
  The port contract is amended: a protocol that caches topology-derived
  data in `initialize()` must refresh it there. The alternative, silently
  routing on a stale graph, is exactly the class of bug to avoid.

### Cost

`TopologyGraph` stays immutable, and each change produces a new graph
(copy-on-write). The simple version copies the adjacency dict, which is
O(n) per change batch. That's fine for periodic churn and too slow for a
change every event at 10⁵ agents. Measure it before optimizing. If it
matters, switch to structural sharing (copy only touched adjacency sets)
behind the same interface.

### Contract tests

- **No delivery to a departed agent**, swept across every protocol.
- **Join reproducibility**: an agent added at `t=50` has the same initial
  state as the same id present from `t=0`.
- **Topology generators** stay covered by the existing complexity sweep.

## 7. How we'll know it worked

Each phase ships only when both conditions hold:

1. **Golden traces unchanged** for every pre-existing config.
2. **A validation result the old engine couldn't produce:**

| Phase | Validation target |
|---|---|
| 1 | Message delay histograms match the configured distribution (KS test). Gossip convergence time grows linearly with mean latency. |
| 2 | `AsyncGossipBehavior` on a ring shows averaging time **~O(n²)**, the Boyd et al. regime, next to the existing synchronous O(n). Getting both in one tool is itself a publishable figure. Raft election time distribution vs. timeout range. |
| 3 | Gossip convergence degrades gracefully under increasing churn rate. In-flight drop counts match the departure rate. |

## 8. Non-goals

- **Parallel or distributed execution.** Determinism and a single event
  queue are worth more here than wall-clock speedups. Revisit after the
  compiled-core work.
- **Packet-level network emulation.** That's ns-3's job. Simul8 models
  message-level latency, not TCP.
- **Continuous state dynamics (ODE integration).** Event-driven only.

## 9. Open questions

1. **`step()` signature.** This design adds `on_timer()` next to `step()`
   to avoid breaking every plugin. The cleaner long-term API is one
   `on_activation(ctx)` taking a context object (`ctx.inbox`,
   `ctx.fired_timer`, `ctx.neighbors`, `ctx.time`). That's a breaking change and
   belongs at a 1.0 boundary, not in this refactor.
2. **Should timers be allowed in synchronous mode**, quantized to ticks
   like latency? Deferred until someone needs it.
3. **Event-mode performance.** It can be much cheaper (only active agents
   run) or much more expensive (one heap operation per wake). Benchmark
   both before claiming either.
4. **`max_virtual_time` with no ticks.** An event-mode run whose agents all go
   silent ends when the queue empties. That's correct, but `SimulationEndedEvent`
   should record which condition ended it.
