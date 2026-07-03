# Simul8: Research-Grade Simulation Framework
## Software Architecture Document v0.1

---

> **Status**: Pre-Implementation Design Review  
> **Audience**: Senior Engineers, Research Contributors  
> **Revision**: 2026-07-01

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Design Philosophy](#2-design-philosophy)
3. [Architectural Weaknesses & Mitigations](#3-architectural-weaknesses--mitigations)
4. [Overall System Architecture](#4-overall-system-architecture)
5. [Component Hierarchy](#5-component-hierarchy)
6. [Dependency Graph](#6-dependency-graph)
7. [Package Structure](#7-package-structure)
8. [Module Responsibilities](#8-module-responsibilities)
9. [Interface Definitions](#9-interface-definitions)
10. [Abstract Base Classes](#10-abstract-base-classes)
11. [Data Flow Diagrams](#11-data-flow-diagrams)
12. [Event Lifecycle](#12-event-lifecycle)
13. [Simulation Lifecycle](#13-simulation-lifecycle)
14. [Extension & Plugin System](#14-extension--plugin-system)
15. [Configuration System](#15-configuration-system)
16. [Folder Structure](#16-folder-structure)
17. [Naming Conventions](#17-naming-conventions)
18. [Coding Standards](#18-coding-standards)
19. [Error Handling Strategy](#19-error-handling-strategy)
20. [Testing Strategy](#20-testing-strategy)
21. [Performance Considerations](#21-performance-considerations)
22. [Future Rust Migration Strategy](#22-future-rust-migration-strategy)

---

## 1. Executive Summary

**Simul8** is a research-grade, event-driven, multi-agent simulation platform designed to support a 3–5 year research roadmap spanning multi-agent systems, distributed AI, autonomous networks, cellular automata, federated learning, and emergent communication.

The platform is built on one immutable principle:

> **The simulator core never knows what is being simulated.**

The engine understands only: Nodes, Events, Time, Communication, Topology, Environment, Metrics, and Experiments. Every domain concept — SDN, gossip learning, cellular automata, LLMs — is a plugin.

---

## 2. Design Philosophy

### 2.1 Foundational Principles

| Principle | Application |
|---|---|
| **Domain-Driven Design (DDD)** | The core domain is "simulation". SDN/FL/NCA are separate bounded contexts implemented as plugins |
| **Hexagonal Architecture** | The simulation engine is the hexagon. Communication, persistence, visualization, and domain behavior are external adapters |
| **SOLID** | Every module follows SRP, OCP, LSP, ISP, DIP strictly |
| **Composition over Inheritance** | Nodes, behaviors, and communication are assembled from components, not subclassed |
| **Dependency Inversion** | All core modules depend on abstractions (ports), never on concrete implementations (adapters) |
| **Immutable Configuration** | Experiment configs are frozen dataclasses; no runtime mutation |
| **Pure Functions** | All state transitions are pure functions where possible, enabling deterministic replay |
| **Event Sourcing** | The event queue is the source of truth; state is derivable from events |

### 2.2 The Three Layers

```
┌─────────────────────────────────────────────┐
│              Plugin Layer                   │
│  Behaviors · Comm · Topologies · Envs       │
│  Metrics · Persistence · Visualization      │
├─────────────────────────────────────────────┤
│             Application Layer               │
│   ExperimentRunner · CLI · Config Loader    │
├─────────────────────────────────────────────┤
│              Core Domain Layer              │
│  Engine · Scheduler · NodeManager          │
│  EventQueue · TimeManager · MetricsEngine  │
└─────────────────────────────────────────────┘
```

The core domain layer has **zero** imports from the plugin or application layers. All communication flows inward via dependency injection at startup.

### 2.3 Key Bets

- **Virtual time over wall-clock time**: Enables arbitrarily fast simulation and complete reproducibility.
- **Event-driven over tick-driven**: Tick-driven wastes CPU when nothing happens; event-driven scales to 100k sparse agents. A tick *is* a recurring event — backward compatible.
- **Plugin discovery over static import**: New research extensions never require touching core.
- **Dataclass-based messages**: Typed, serializable, diffable, and trivially portable to Rust structs later.

---

## 3. Architectural Weaknesses & Mitigations

Before committing to the architecture, the following critical design risks are identified and addressed:

### 3.1 ⚠ Risk: Plugin System Creates Implicit Coupling

**Problem**: Loose plugin registration via string names or entry-points creates invisible coupling. A missing plugin causes a runtime error, not a compile-time one. Research code is notoriously fragile in this regard.

**Mitigation**:
- Plugins are registered with **typed manifests** (a dataclass describing the plugin's interface contract).
- The `PluginLoader` validates each manifest at load time against the required port interface.
- Configuration files reference plugins by fully-qualified class path, not magic strings.
- A `--validate` CLI flag runs all manifest checks without executing a simulation.

### 3.2 ⚠ Risk: Event Queue Becomes a God Object

**Problem**: A single global event queue that every module reads/writes to creates hidden coupling and makes testing hard.

**Mitigation**:
- The event queue is a **pure data structure** (`EventQueue`) with no behavior.
- Only the `Scheduler` writes to it; only the `Engine` reads from it.
- Nodes submit events via a **`EventBus` port** — a narrow interface that does NOT expose the full queue.
- This means nodes can never inspect or modify existing events; they can only emit.

### 3.3 ⚠ Risk: NodeManager as God Object

**Problem**: A manager that holds all nodes can easily accumulate responsibilities (routing, state inspection, metric collection) violating SRP.

**Mitigation**:
- `NodeManager` is a **registry only**: create, destroy, lookup by ID. Nothing else.
- Node iteration for metric collection goes through a dedicated `NodeView` (read-only iterator).
- Topology queries go through `TopologyManager`, not `NodeManager`.

### 3.4 ⚠ Risk: Metrics Engine Coupling

**Problem**: Metrics that require access to node state create tight coupling between the metrics layer and the node model.

**Mitigation**:
- Nodes emit **`StateChangedEvent`** whenever their state changes.
- Metrics subscribe to events, never inspect node state directly.
- This keeps metrics fully decoupled and independently testable.

### 3.5 ⚠ Risk: Determinism with Parallel Execution

**Problem**: Future parallelism (multiprocessing for 100k nodes) breaks determinism if not carefully managed.

**Mitigation**:
- Single-threaded by default; determinism is guaranteed.
- Parallel execution is a future **opt-in adapter** that uses a partitioned event queue with a deterministic merge strategy (logical vector clocks).
- The `RandomnessManager` provides per-node seeded PRNGs derived from the global seed, so node-level randomness is reproducible regardless of execution order.

### 3.6 ⚠ Risk: Configuration Versioning Breaks Reproducibility

**Problem**: An experiment run in 2026 should reproduce identically in 2028 even if defaults change.

**Mitigation**:
- Configuration files embed a `schema_version` field.
- Configs are **never mutated**; they are frozen dataclasses.
- The `ConfigLoader` validates the schema version and migrates older configs using registered migration functions.
- Every experiment output includes the full resolved configuration snapshot.

### 3.7 ⚠ Risk: Communication Layer Leaking Domain Knowledge

**Problem**: Even "abstract" communication interfaces can leak domain semantics (e.g., a `gossip_round()` method on the base class).

**Mitigation**:
- The base `CommunicationProtocol` port exposes only two methods: `send(message: Message, recipients: List[NodeId])` and `receive() -> List[Message]`.
- Higher-level semantics (gossip rounds, broadcast flooding) are entirely within the plugin implementation.

### 3.8 ⚠ Risk: Python GIL for CPU-Bound Simulation at Scale

**Problem**: At 10k–100k agents with complex behaviors, the GIL will become a bottleneck before Rust migration.

**Mitigation**:
- The simulation loop is designed to be extracted into a `SimulationWorker` that can be pickled and run in a `multiprocessing.Process`.
- Node behaviors are pure functions, making them safe to parallelize with `ProcessPoolExecutor` partitioned by topology regions.
- NumPy vectorization is supported for batch state updates via the `BatchBehavior` extension interface.

---

## 4. Overall System Architecture

### 4.1 Hexagonal Architecture Diagram

```
                    ┌──────────────────────────────────┐
                    │        External World            │
  ┌─────────────┐   │  ┌──────────┐  ┌─────────────┐  │
  │  YAML/JSON  │───┼─▶│ Config   │  │  CLI / API  │  │
  │  Config     │   │  │ Adapter  │  │  Adapter    │  │
  └─────────────┘   │  └────┬─────┘  └──────┬──────┘  │
                    │       │               │         │
  ┌─────────────┐   │  ┌────▼───────────────▼──────┐  │
  │  CSV/JSON/  │◀──┼──│    Application Layer       │  │
  │  SQLite     │   │  │    ExperimentRunner        │  │
  └─────────────┘   │  │    PluginLoader            │  │
                    │  └────────────┬───────────────┘  │
  ┌─────────────┐   │               │                  │
  │Visualization│◀──┼───────────────┤                  │
  │  Adapter    │   │  ┌────────────▼───────────────┐  │
  └─────────────┘   │  │      CORE DOMAIN           │  │
                    │  │                            │  │
  ┌─────────────┐   │  │  Engine ◀──▶ Scheduler     │  │
  │  Behavior   │───┼─▶│  NodeManager ◀──▶ Topology │  │
  │  Plugins    │   │  │  EventQueue ◀──▶ TimeManager│  │
  └─────────────┘   │  │  MetricsEngine             │  │
                    │  │  RandomnessManager         │  │
  ┌─────────────┐   │  └────────────────────────────┘  │
  │   Comm      │───┼─▶       (Ports/Adapters)         │
  │  Plugins    │   │                                  │
  └─────────────┘   └──────────────────────────────────┘
```

### 4.2 Core Domain Invariants

The following invariants hold at all times in the core domain and are enforced by assertions:

1. **Time is monotonically non-decreasing**: The virtual clock never goes backward.
2. **Event IDs are globally unique**: Guaranteed by the `EventFactory`.
3. **Node IDs are globally unique**: Guaranteed by the `NodeRegistry`.
4. **The global seed is set exactly once**: Before any randomness is consumed.
5. **Configuration is frozen at experiment start**: No runtime mutation of config objects.

---

## 5. Component Hierarchy

```
Simul8
├── Core Domain
│   ├── SimulationEngine          ← Top-level orchestrator
│   ├── Scheduler                 ← Manages event scheduling
│   ├── EventQueue                ← Priority queue, ordered by virtual time
│   ├── TimeManager               ← Virtual clock, tick management
│   ├── NodeManager               ← Node registry (CRUD only)
│   ├── TopologyManager           ← Graph structure, neighbor resolution
│   ├── CommunicationLayer        ← Routes messages via active protocol
│   ├── Environment               ← Global env state, rules evaluation
│   ├── MetricsEngine             ← Aggregates, computes, exports metrics
│   ├── RandomnessManager         ← Seeded PRNG management
│   └── StatisticsEngine          ← Post-run statistical analysis
│
├── Application Layer
│   ├── ExperimentRunner          ← Assembles and runs experiments
│   ├── PluginLoader              ← Discovers and validates plugins
│   ├── ConfigLoader              ← Loads and validates config files
│   └── PersistenceManager        ← Coordinates result export
│
└── Plugin Layer (adapters implementing ports)
    ├── behaviors/
    │   ├── RandomBehavior
    │   └── RuleBasedBehavior
    ├── communication/
    │   ├── BroadcastProtocol
    │   └── GossipProtocol
    ├── topologies/
    │   ├── RingTopology
    │   ├── GridTopology
    │   └── RandomTopology
    ├── metrics/
    │   ├── MessageCountMetric
    │   ├── ConvergenceMetric
    │   └── EntropyMetric
    ├── persistence/
    │   ├── CsvExporter
    │   └── JsonExporter
    └── environments/
        └── NullEnvironment       ← No-op environment for testing
```

---

## 6. Dependency Graph

### 6.1 Core Module Dependencies (Acyclic)

```
ConfigLoader ──────────────────────────────▶ (no deps)
RandomnessManager ──────────────────────────▶ (no deps)
TimeManager ────────────────────────────────▶ (no deps)
EventQueue ─────────────────────────────────▶ TimeManager
NodeManager ────────────────────────────────▶ (no deps)
TopologyManager ────────────────────────────▶ NodeManager
CommunicationLayer ─────────────────────────▶ TopologyManager, EventQueue
Environment ────────────────────────────────▶ NodeManager, TimeManager
MetricsEngine ──────────────────────────────▶ EventQueue (subscribes)
Scheduler ──────────────────────────────────▶ EventQueue, TimeManager
StatisticsEngine ───────────────────────────▶ MetricsEngine
SimulationEngine ───────────────────────────▶ Scheduler, NodeManager, 
                                              CommunicationLayer, Environment,
                                              MetricsEngine, TimeManager
ExperimentRunner ───────────────────────────▶ SimulationEngine, ConfigLoader,
                                              PluginLoader, PersistenceManager
```

### 6.2 Dependency Direction Rule

```
Plugins ──▶ Core Ports
Application ──▶ Core Ports
Core ──▶ Abstractions only

FORBIDDEN:
Core ──▶ Plugins        ✗
Core ──▶ Application    ✗
Plugins ──▶ Application ✗
```

This is enforced via import linting (see testing strategy).

---

## 7. Package Structure

```
simul8/
│
├── core/                          # Core domain — no external dependencies
│   ├── __init__.py
│   ├── engine.py                  # SimulationEngine
│   ├── scheduler.py               # Scheduler
│   ├── time_manager.py            # TimeManager, VirtualClock
│   ├── event_queue.py             # EventQueue
│   ├── node_manager.py            # NodeManager, NodeRegistry
│   ├── topology_manager.py        # TopologyManager
│   ├── communication_layer.py     # CommunicationLayer (uses port)
│   ├── environment.py             # Environment base
│   ├── metrics_engine.py          # MetricsEngine
│   ├── randomness_manager.py      # RandomnessManager
│   └── statistics_engine.py       # StatisticsEngine
│
├── domain/                        # Domain model — pure data, no behavior
│   ├── __init__.py
│   ├── node.py                    # Node dataclass
│   ├── event.py                   # Event dataclass hierarchy
│   ├── message.py                 # Message dataclass
│   ├── topology.py                # TopologyGraph, Edge, Neighbor
│   ├── metric.py                  # MetricRecord, MetricSeries
│   ├── state.py                   # NodeState, EnvironmentState
│   └── experiment.py              # ExperimentConfig (frozen dataclass)
│
├── ports/                         # Abstract interfaces (ports)
│   ├── __init__.py
│   ├── behavior.py                # BehaviorPort (ABC)
│   ├── communication.py           # CommunicationProtocolPort (ABC)
│   ├── topology_generator.py      # TopologyGeneratorPort (ABC)
│   ├── metric_collector.py        # MetricCollectorPort (ABC)
│   ├── persistence.py             # PersistencePort (ABC)
│   ├── environment_rule.py        # EnvironmentRulePort (ABC)
│   ├── event_handler.py           # EventHandlerPort (ABC)
│   └── visualization.py           # VisualizationPort (ABC)
│
├── app/                           # Application layer
│   ├── __init__.py
│   ├── experiment_runner.py       # ExperimentRunner
│   ├── plugin_loader.py           # PluginLoader, PluginManifest
│   ├── config_loader.py           # ConfigLoader, schema validation
│   └── persistence_manager.py     # PersistenceManager
│
├── plugins/                       # Built-in plugin adapters
│   ├── __init__.py
│   ├── behaviors/
│   │   ├── __init__.py
│   │   ├── random_behavior.py
│   │   └── rule_based_behavior.py
│   ├── communication/
│   │   ├── __init__.py
│   │   ├── broadcast.py
│   │   └── gossip.py
│   ├── topologies/
│   │   ├── __init__.py
│   │   ├── ring.py
│   │   ├── grid.py
│   │   ├── random_graph.py
│   │   └── mesh.py
│   ├── metrics/
│   │   ├── __init__.py
│   │   ├── message_count.py
│   │   ├── convergence.py
│   │   └── entropy.py
│   ├── persistence/
│   │   ├── __init__.py
│   │   ├── csv_exporter.py
│   │   └── json_exporter.py
│   └── environments/
│       ├── __init__.py
│       └── null_environment.py
│
├── cli/                           # CLI entry point
│   ├── __init__.py
│   └── main.py
│
├── tests/
│   ├── unit/
│   │   ├── core/
│   │   ├── domain/
│   │   ├── ports/
│   │   └── plugins/
│   ├── integration/
│   │   ├── test_broadcast_experiment.py
│   │   └── test_gossip_experiment.py
│   ├── regression/
│   │   └── test_determinism.py
│   └── fixtures/
│       └── configs/
│           ├── minimal.yaml
│           └── gossip_1000_nodes.yaml
│
├── examples/
│   ├── minimal_broadcast.yaml
│   └── gossip_convergence.yaml
│
├── docs/
│   └── architecture.md
│
├── pyproject.toml
├── README.md
└── CONTRIBUTING.md
```

---

## 8. Module Responsibilities

### 8.1 Core Domain Modules

#### `SimulationEngine`
- **Purpose**: Top-level orchestrator of the simulation loop.
- **Responsibilities**: Pull next event from `Scheduler`, dispatch to registered handlers, advance time, check termination conditions.
- **Lifecycle**: `initialize()` → `run()` → `finalize()`.
- **Dependencies**: `Scheduler`, `NodeManager`, `MetricsEngine`, `TimeManager`, `Environment`.
- **Extension points**: `pre_step_hooks`, `post_step_hooks` for instrumentation.
- **Complexity**: O(E log E) per simulation where E = total events.
- **Does NOT**: Know about behaviors, communication protocols, or topologies.

#### `Scheduler`
- **Purpose**: Manages the ordering and scheduling of events in virtual time.
- **Responsibilities**: Enqueue events with timestamps, dequeue next event, support recurring events (ticks), support cancellation.
- **Dependencies**: `EventQueue`, `TimeManager`.
- **Key invariant**: Events with equal timestamps are processed in a deterministic secondary order (FIFO within same tick by default, configurable to LIFO or priority-weighted).

#### `EventQueue`
- **Purpose**: A pure priority queue ordered by `(virtual_time, sequence_number)`.
- **Responsibilities**: Enqueue, dequeue-min, peek, size query.
- **Dependencies**: None (pure data structure).
- **Implementation note**: Backed by `heapq` in Python MVP; portable to a binary heap in Rust.
- **Does NOT**: Process events, modify nodes, or track time.

#### `TimeManager`
- **Purpose**: Authoritative source of virtual time.
- **Responsibilities**: Get current time, advance time to target, register tick intervals.
- **Dependencies**: None.
- **Key constraint**: Time is read-only to all modules except `Scheduler`.
- **Units**: Dimensionless integer ticks or floating-point virtual seconds — determined by config.

#### `NodeManager`
- **Purpose**: Registry of all nodes in the simulation.
- **Responsibilities**: Create node (returns `NodeId`), destroy node, lookup node by `NodeId`, iterate all nodes (via `NodeView`).
- **Dependencies**: `RandomnessManager` (for node-level seeding).
- **Does NOT**: Route messages, apply behaviors, or collect metrics.

#### `TopologyManager`
- **Purpose**: Manages the graph structure of the network.
- **Responsibilities**: Build topology from a `TopologyGeneratorPort`, query neighbors of a node, query distance between nodes, expose the topology graph.
- **Dependencies**: `NodeManager` (for node ID resolution).
- **Does NOT**: Know what the topology means — that's the environment's job.

#### `CommunicationLayer`
- **Purpose**: Routes messages between nodes using the active `CommunicationProtocolPort`.
- **Responsibilities**: Accept outbound messages from nodes, deliver inbound messages to nodes, track send/receive counts.
- **Dependencies**: `TopologyManager`, `EventQueue` (emits `MessageDeliveredEvent`).
- **Does NOT**: Know what the messages contain.

#### `Environment`
- **Purpose**: Represents global simulation state and rules that are not node-specific.
- **Responsibilities**: Hold global state, apply `EnvironmentRulePort` plugins, respond to `EnvironmentQueryEvent`.
- **Dependencies**: `NodeManager`, `TimeManager`.
- **Extension points**: `EnvironmentRulePort` plugins define domain-specific rules.

#### `MetricsEngine`
- **Purpose**: Subscribes to events and aggregates simulation metrics.
- **Responsibilities**: Register `MetricCollectorPort` plugins, fan-out relevant events to collectors, expose time-series data.
- **Dependencies**: Event subscription (via `EventBus` port).
- **Does NOT**: Access node state directly (receives it via events).

#### `RandomnessManager`
- **Purpose**: Deterministic randomness source.
- **Responsibilities**: Initialize with global seed, provide per-node seeded RNG, provide global RNG for topology generation.
- **Dependencies**: None.
- **Key design**: Each node gets `RNG(seed=global_seed XOR node_id)` ensuring independence and reproducibility.

#### `StatisticsEngine`
- **Purpose**: Post-run statistical analysis.
- **Responsibilities**: Consume `MetricSeries` data, compute summary statistics (mean, std, percentiles, convergence rate), format for export.
- **Dependencies**: `MetricsEngine`.

### 8.2 Application Layer Modules

#### `ExperimentRunner`
- **Purpose**: Assembles and executes experiments from a configuration.
- **Responsibilities**: Load config, load plugins, inject dependencies, run `SimulationEngine`, export results.
- **Lifecycle**: The single entry point for all experiment execution.

#### `PluginLoader`
- **Purpose**: Discovers, validates, and instantiates plugins.
- **Responsibilities**: Load plugin class from config path, validate against required port interface, instantiate with config parameters.
- **Validation**: Checks that the plugin class implements the correct ABC at load time.

#### `ConfigLoader`
- **Purpose**: Loads and validates experiment configurations.
- **Responsibilities**: Parse YAML/JSON, validate schema version, apply defaults, freeze into `ExperimentConfig` dataclass.
- **Error behavior**: Raises `ConfigValidationError` with precise field-level messages.

#### `PersistenceManager`
- **Purpose**: Coordinates metric export to storage backends.
- **Responsibilities**: Route `MetricSeries` data to registered `PersistencePort` adapters.

---

## 9. Interface Definitions

All ports are defined in `simul8/ports/`. These are the **only contracts** that plugins must implement.

### 9.1 `BehaviorPort`

```
Interface: BehaviorPort
Purpose:   Defines how a node decides its next state and messages.

Methods:
  initialize(node_id, config, rng) -> None
    Called once when the node is created.

  step(node_id, current_state, inbox, virtual_time) -> BehaviorResult
    Pure function. Given current state and received messages, returns
    the next state and any messages to send. Must be deterministic.

  on_event(node_id, event, current_state) -> BehaviorResult
    Called when an event targeted at this node is processed.

Contracts:
  - MUST be stateless between calls (state lives in NodeState)
  - MUST NOT import from simul8.core or simul8.app
  - MUST NOT have side effects

BehaviorResult:
  next_state: NodeState
  outbound_messages: List[Message]
  emit_events: List[Event]       # Optional events to schedule
```

### 9.2 `CommunicationProtocolPort`

```
Interface: CommunicationProtocolPort
Purpose:   Defines how messages are propagated through the network.

Methods:
  initialize(topology, config, rng) -> None

  route(message, sender_id, topology) -> List[Tuple[NodeId, Message]]
    Pure function. Given a message and the sender, returns (recipient, message)
    pairs. The engine delivers them.

  on_tick(virtual_time, topology) -> List[Tuple[NodeId, NodeId, Message]]
    Called each tick. Used for protocols that push messages proactively
    (e.g., gossip rounds that trigger on a timer, not a node event).

Contracts:
  - route() MUST be deterministic given identical inputs
  - MUST NOT access node state directly
  - MUST NOT schedule events directly
```

### 9.3 `TopologyGeneratorPort`

```
Interface: TopologyGeneratorPort
Purpose:   Generates the initial topology graph.

Methods:
  generate(node_ids, config, rng) -> TopologyGraph
    Pure function. Given node IDs, returns an immutable graph.

Contracts:
  - MUST be deterministic given identical inputs
  - MUST return a valid graph (no dangling edges)
```

### 9.4 `MetricCollectorPort`

```
Interface: MetricCollectorPort
Purpose:   Subscribes to events and accumulates a single metric.

Methods:
  subscribed_events() -> FrozenSet[Type[Event]]
    Returns the set of event types this collector cares about.

  on_event(event, virtual_time) -> None
    Called when a subscribed event fires.

  get_series() -> MetricSeries
    Returns the accumulated time-series data.

  reset() -> None
    Clears accumulated data (for multi-run experiments).
```

### 9.5 `PersistencePort`

```
Interface: PersistencePort
Purpose:   Exports simulation results to a storage backend.

Methods:
  write(series: List[MetricSeries], experiment_config, output_path) -> None

Contracts:
  - MUST be idempotent (writing twice produces same result)
  - MUST include experiment metadata in output
```

### 9.6 `EnvironmentRulePort`

```
Interface: EnvironmentRulePort
Purpose:   Defines domain-specific rules that govern the environment.

Methods:
  evaluate(env_state, node_states, virtual_time) -> EnvironmentState
    Pure function. Returns the next environment state.
```

---

## 10. Abstract Base Classes

All ABCs live in `simul8/ports/`. Concrete implementations live in `simul8/plugins/`.

### 10.1 Class Hierarchy (Core Domain — No Inheritance)

The core domain uses **composition**, not inheritance. A `Node` is not subclassed; it is assembled from components:

```
Node (dataclass, frozen)
├── node_id: NodeId
├── state: NodeState         ← plugin-defined schema
├── memory: NodeMemory       ← dict-like store
├── behavior: BehaviorPort   ← injected at creation
├── comm: CommInterface      ← thin interface to CommunicationLayer
└── metadata: NodeMetadata
```

### 10.2 Event Hierarchy

Events are pure dataclasses in `simul8/domain/event.py`:

```
Event (frozen dataclass)
├── event_id: EventId
├── virtual_time: VirtualTime
├── source_id: NodeId | None
└── priority: int

├── TickEvent(Event)          ← periodic heartbeat
├── MessageSentEvent(Event)   ← node sent a message
├── MessageDeliveredEvent(Event) ← message reached recipient
├── NodeCreatedEvent(Event)
├── NodeDestroyedEvent(Event)
├── StateChangedEvent(Event)  ← node state changed
├── TopologyChangedEvent(Event)
├── MetricSampledEvent(Event)
├── SimulationStartedEvent(Event)
├── SimulationEndedEvent(Event)
└── CustomEvent(Event)        ← plugins extend this
```

### 10.3 Port ABCs

```python
# Pattern for all ports:
from abc import ABC, abstractmethod

class BehaviorPort(ABC):
    @abstractmethod
    def initialize(self, node_id, config, rng): ...
    
    @abstractmethod
    def step(self, node_id, current_state, inbox, virtual_time): ...
```

Each port ABC is a thin interface — **no default implementations**, no mixin methods. This keeps the contract minimal and maximizes Rust portability (direct trait-to-ABC mapping).

---

## 11. Data Flow Diagrams

### 11.1 Normal Simulation Tick

```
ExperimentRunner
    │
    ▼
SimulationEngine.run()
    │
    ▼
Scheduler.next_event()          ← pops from EventQueue
    │
    ▼
Engine dispatches event to handlers
    │
    ├──▶ MetricsEngine.on_event()     ← always fires first
    │
    ├──▶ Environment.on_event()       ← environment rules
    │
    └──▶ NodeManager.get_node(target)
              │
              ▼
         Node.process_event()
              │
              ├──▶ BehaviorPort.step()        ← pure function
              │         │
              │         ▼
              │    BehaviorResult
              │    ├── next_state ──▶ Node.update_state()
              │    ├── messages   ──▶ CommunicationLayer.send()
              │    └── events     ──▶ Scheduler.schedule()
              │
              └──▶ MetricsEngine.record(StateChangedEvent)
```

### 11.2 Message Flow (Broadcast Example)

```
Node A calls comm.send(message, recipients=ALL)
    │
    ▼
CommunicationLayer.receive(message, sender=A)
    │
    ▼
BroadcastProtocol.route(message, sender=A, topology)
    │   returns [(B, msg), (C, msg), (D, msg), ...]
    ▼
CommunicationLayer schedules MessageDeliveredEvent
    for each recipient at virtual_time + latency
    │
    ▼
EventQueue inserts events
    │
    ▼
At scheduled time, Engine pops MessageDeliveredEvent
    │
    ▼
Node B/C/D receive message in next step() call
```

### 11.3 Metrics Data Flow

```
Any Event fires
    │
    ▼
MetricsEngine.on_event(event)
    │
    ▼
For each registered MetricCollectorPort:
    If event.type in collector.subscribed_events():
        collector.on_event(event, virtual_time)
    │
    ▼
At simulation end:
StatisticsEngine.compute(collector.get_series())
    │
    ▼
PersistenceManager.write(series, config, output_path)
    │
    ▼
CsvExporter / JsonExporter / SQLiteExporter
```

---

## 12. Event Lifecycle

### 12.1 Event States

```
CREATED ──▶ SCHEDULED ──▶ DISPATCHING ──▶ HANDLED ──▶ ARCHIVED
                │
                └──▶ CANCELLED
```

### 12.2 Event ID Uniqueness

Every event is assigned a monotonically increasing `sequence_number` by the `EventFactory`. The sort key for the `EventQueue` is:

```
(virtual_time, priority, sequence_number)
```

This ensures **complete deterministic ordering** even when multiple events share the same virtual timestamp.

### 12.3 Event Cancellation

Events can be cancelled by holding their `EventId` (returned by `Scheduler.schedule()`). A cancelled event is marked in a `cancelled_ids` set; when popped from the queue, it is silently discarded. This avoids expensive deletion from the heap.

### 12.4 Recurring Events (Ticks)

A `TickEvent` is self-rescheduling:

```
Engine pops TickEvent at T
    │
    ▼
Handlers process tick
    │
    ▼
Engine re-schedules TickEvent at T + tick_interval
```

This makes ticks first-class events, not a separate loop — eliminating the distinction between tick-driven and event-driven simulation.

---

## 13. Simulation Lifecycle

```
Phase 1: INITIALIZATION
─────────────────────────────────────────────────────────────
ConfigLoader.load(path)
    └──▶ ExperimentConfig (frozen)

PluginLoader.load_all(config.plugins)
    └──▶ Validates each plugin against its port

RandomnessManager.initialize(config.seed)

NodeManager.create_nodes(config.num_nodes)

TopologyGenerator.generate(node_ids, config, rng)
    └──▶ TopologyManager.set_topology(graph)

For each node:
    BehaviorPort.initialize(node_id, config, rng)

MetricsEngine.register_collectors(config.metrics)

Scheduler.schedule(SimulationStartedEvent, t=0)
If config.tick_interval:
    Scheduler.schedule(TickEvent, t=0, interval=config.tick_interval)

Phase 2: RUNNING
─────────────────────────────────────────────────────────────
Loop until termination condition:
    event = Scheduler.next_event()
    TimeManager.advance(event.virtual_time)
    Engine.dispatch(event)
    
    Check termination:
    - virtual_time >= config.max_time
    - EventQueue is empty
    - TerminationConditionPort evaluates to True

Phase 3: FINALIZATION
─────────────────────────────────────────────────────────────
Engine.dispatch(SimulationEndedEvent)
StatisticsEngine.compute_all()
PersistenceManager.write_all(output_path)
Logger.flush()

Phase 4: POST-RUN (optional multi-run)
─────────────────────────────────────────────────────────────
If config.num_runs > 1:
    Reset state (MetricCollectors, NodeManager, EventQueue)
    Re-seed RandomnessManager(seed=base_seed + run_index)
    Repeat Phase 1–3
```

---

## 14. Extension & Plugin System

### 14.1 Plugin Discovery Strategy

Plugins are referenced by **fully-qualified class path** in configuration:

```yaml
plugins:
  behavior: "simul8.plugins.behaviors.random_behavior.RandomBehavior"
  communication: "simul8.plugins.communication.gossip.GossipProtocol"
  topology: "simul8.plugins.topologies.ring.RingTopology"
  metrics:
    - "simul8.plugins.metrics.message_count.MessageCountMetric"
    - "simul8.plugins.metrics.convergence.ConvergenceMetric"
  persistence:
    - "simul8.plugins.persistence.csv_exporter.CsvExporter"
```

External research plugins live in separate packages (e.g., `simul8_sdn`, `simul8_nca`) and are referenced by their fully-qualified path. No magic entry-point registration needed.

### 14.2 Plugin Validation

At load time:

```
PluginLoader.load(class_path, expected_port)
    1. Import module, resolve class
    2. Assert issubclass(cls, expected_port)
    3. Check cls has all abstract methods implemented
    4. Instantiate with plugin_config
    5. Call cls.validate_config(plugin_config) if defined
    6. Return instance
```

### 14.3 Plugin Configuration

Each plugin receives its own configuration namespace:

```yaml
plugin_configs:
  GossipProtocol:
    fan_out: 3
    round_interval: 10
    loss_probability: 0.0
  RingTopology:
    bidirectional: true
```

Plugins receive their config as a frozen `PluginConfig` dataclass derived from the YAML block.

### 14.4 Writing a New Plugin (Minimal Example)

To add a new communication protocol for a research paper:

1. Create `myresearch/latent_comm.py`
2. Implement `CommunicationProtocolPort`
3. Reference it in YAML: `communication: "myresearch.latent_comm.LatentComm"`
4. Run — **no core code changes required**.

### 14.5 Plugin Dependency Management

External plugins are separate Python packages. They declare `simul8` as a dependency in their `pyproject.toml`. This ensures clean versioning and prevents core contamination.

---

## 15. Configuration System

### 15.1 Schema

```yaml
# Example: gossip_1000_nodes.yaml
schema_version: "1.0"

experiment:
  name: "gossip_convergence_baseline"
  description: "Convergence study with gossip protocol on 1000 nodes"
  seed: 42
  num_runs: 5
  tags: ["gossip", "convergence", "baseline"]

simulation:
  num_nodes: 1000
  max_virtual_time: 10000
  tick_interval: 1           # null = pure event-driven
  time_unit: "ticks"

plugins:
  behavior: "simul8.plugins.behaviors.random_behavior.RandomBehavior"
  communication: "simul8.plugins.communication.gossip.GossipProtocol"
  topology: "simul8.plugins.topologies.random_graph.RandomGraphTopology"
  environment: "simul8.plugins.environments.null_environment.NullEnvironment"
  metrics:
    - "simul8.plugins.metrics.message_count.MessageCountMetric"
    - "simul8.plugins.metrics.convergence.ConvergenceMetric"
    - "simul8.plugins.metrics.entropy.EntropyMetric"
  persistence:
    - "simul8.plugins.persistence.csv_exporter.CsvExporter"

plugin_configs:
  RandomBehavior:
    state_dimensions: 8
    update_probability: 0.1
  GossipProtocol:
    fan_out: 3
    round_interval: 10
  RandomGraphTopology:
    edge_probability: 0.05
  CsvExporter:
    output_dir: "./results"
    include_metadata: true

logging:
  level: "INFO"
  output: "stdout"
  structured: true
```

### 15.2 `ExperimentConfig` Dataclass

```
ExperimentConfig (frozen dataclass)
├── schema_version: str
├── name: str
├── seed: int
├── num_runs: int
├── simulation: SimulationConfig
│   ├── num_nodes: int
│   ├── max_virtual_time: float
│   └── tick_interval: Optional[float]
├── plugins: PluginConfig
│   ├── behavior: str
│   ├── communication: str
│   ├── topology: str
│   ├── environment: str
│   ├── metrics: List[str]
│   └── persistence: List[str]
└── plugin_configs: Dict[str, Dict[str, Any]]
```

All config objects use `@dataclass(frozen=True)`. Mutation raises `FrozenInstanceError`.

### 15.3 Configuration Versioning and Migration

```python
# In config_loader.py
CONFIG_MIGRATIONS = {
    "0.9": migrate_0_9_to_1_0,
    "1.0": identity,
}
```

When loading a config with an older schema version, the loader applies migrations in sequence before validation.

---

## 16. Folder Structure

```
simul8/
│
├── core/                  # Pure domain logic — no I/O
├── domain/                # Data models — pure dataclasses, no behavior
├── ports/                 # ABC interfaces — no implementation
├── app/                   # Application orchestration
├── plugins/               # Built-in adapters
├── cli/                   # Entry points
│
├── tests/
│   ├── unit/              # Test each module in isolation
│   ├── integration/       # Test assembled experiments end-to-end
│   ├── regression/        # Determinism checks
│   └── fixtures/          # Config files and test data
│
├── examples/              # Runnable example configs
├── docs/                  # Architecture and API docs
│
├── pyproject.toml         # PEP 517 build system
├── setup.cfg              # Flake8, isort config
└── .github/
    └── workflows/
        └── ci.yml
```

---

## 17. Naming Conventions

### 17.1 Modules and Files

| Artifact | Convention | Example |
|---|---|---|
| Modules | `snake_case` | `event_queue.py` |
| Packages | `snake_case` | `simul8/plugins/` |
| Classes | `PascalCase` | `EventQueue` |
| ABCs/Ports | `PascalCase` + `Port` suffix | `BehaviorPort` |
| Dataclasses | `PascalCase` | `ExperimentConfig` |
| Functions | `snake_case` | `get_neighbors()` |
| Constants | `UPPER_SNAKE_CASE` | `MAX_NODES` |
| Type aliases | `PascalCase` | `NodeId = str` |
| Private methods | `_snake_case` | `_validate_config()` |

### 17.2 Event Naming

All event class names end with `Event`: `TickEvent`, `MessageDeliveredEvent`.

### 17.3 Plugin Naming

Plugin classes are named after their algorithm, not their role: `GossipProtocol`, not `CommunicationPlugin001`.

---

## 18. Coding Standards

### 18.1 Type System

- **Full type annotations** on all public interfaces (PEP 484).
- `from __future__ import annotations` in all modules for forward references.
- Use `TypeAlias` for domain-specific ID types: `NodeId = NewType('NodeId', str)`.
- No bare `dict` or `list` — always annotated: `Dict[NodeId, NodeState]`.

### 18.2 Immutability

- Domain objects (`Node`, `Event`, `Message`, `ExperimentConfig`) are `@dataclass(frozen=True)`.
- State transitions return **new objects**, never mutate existing ones.
- `BehaviorPort.step()` returns a new `NodeState`, never modifies the input.

### 18.3 Pure Functions

- Topology generation is a pure function: `generate(node_ids, config, rng) -> TopologyGraph`.
- Behavior step is a pure function: `step(state, inbox, time) -> BehaviorResult`.
- Pure functions are explicitly documented with `# PURE FUNCTION` comment.
- Side-effectful functions are documented with `# SIDE EFFECTS: [description]`.

### 18.4 Import Rules (Enforced via CI)

```
# Allowed imports by layer:
domain/      → stdlib, third-party only
ports/       → stdlib, domain/ only
core/        → stdlib, domain/, ports/ only
plugins/     → stdlib, third-party, domain/, ports/ only
app/         → everything
cli/         → app/ only

# Forbidden:
core/        → plugins/   ✗
core/        → app/       ✗
domain/      → core/      ✗
ports/       → core/      ✗
```

Enforced via `import-linter` in CI.

### 18.5 Docstring Standard

```python
class EventQueue:
    """Priority queue of simulation events ordered by virtual time.

    Purpose:
        Stores pending events and provides O(log n) insertion and
        O(log n) minimum extraction.

    Responsibilities:
        - Enqueue events with (virtual_time, sequence_number) keys
        - Dequeue the earliest event
        - Support O(1) peek without dequeue
        - Report queue size

    Lifecycle:
        Created once by SimulationEngine during initialization.
        Cleared between runs in multi-run experiments.

    Dependencies:
        None. Pure data structure.

    Extension points:
        None. Replace via dependency injection if alternative
        implementations are needed.

    Complexity:
        enqueue: O(log n)
        dequeue_min: O(log n)
        peek: O(1)
        size: O(1)

    Future optimizations:
        Consider a Fibonacci heap for O(1) amortized decrease-key
        if event priorities need to change after scheduling.
    """
```

### 18.6 Toolchain

| Tool | Purpose |
|---|---|
| `ruff` | Linting and formatting |
| `mypy` (strict) | Type checking |
| `pytest` | Testing |
| `pytest-cov` | Coverage |
| `import-linter` | Enforce import boundaries |
| `hypothesis` | Property-based testing |

---

## 19. Error Handling Strategy

### 19.1 Error Taxonomy

```
Simul8Error (base)
├── ConfigError
│   ├── ConfigValidationError     ← Invalid config field
│   ├── ConfigVersionError        ← Unknown schema version
│   └── ConfigMigrationError      ← Migration failed
├── PluginError
│   ├── PluginNotFoundError       ← Class path doesn't resolve
│   ├── PluginInterfaceError      ← Doesn't implement required port
│   └── PluginConfigError         ← Plugin config invalid
├── SimulationError
│   ├── TimeViolationError        ← Event scheduled in the past
│   ├── NodeNotFoundError         ← NodeId doesn't exist
│   └── DeterminismError          ← Unexpected non-determinism detected
└── PersistenceError
    └── ExportError               ← Failed to write results
```

### 19.2 Error Handling Principles

- **Fail fast at initialization**: All plugin and config validation happens before the simulation loop starts. A bad config is caught before wasting compute.
- **No silent failures**: Every exception is logged with context before propagation.
- **No bare `except`**: Always catch specific exceptions.
- **Recovery is not attempted**: If the simulation enters an inconsistent state, it halts and saves partial results. Research integrity requires clean data.
- **Errors carry context**: All custom exceptions accept a `context: Dict[str, Any]` parameter for structured logging.

### 19.3 Logging

```python
# Structured logging with context
logger.info("event_dispatched", extra={
    "event_id": event.event_id,
    "event_type": type(event).__name__,
    "virtual_time": event.virtual_time,
    "source_node": event.source_id,
})
```

Logs are structured JSON by default for machine parseability. Human-readable format available via config flag.

---

## 20. Testing Strategy

### 20.1 Test Pyramid

```
         ┌─────────────┐
         │  Regression │  ← Determinism checks (seed + config = identical output)
         │   Tests     │
         └──────┬──────┘
                │
         ┌──────▼──────────┐
         │  Integration    │  ← Full experiments: gossip convergence, etc.
         │     Tests       │
         └──────┬──────────┘
                │
    ┌───────────▼───────────────────┐
    │         Unit Tests            │  ← Every class and pure function
    └───────────────────────────────┘
```

### 20.2 Unit Testing Principles

- Every `core/` module is tested in isolation using mock ports.
- Every `port/` ABC is tested via a **conformance test suite** that all plugins must pass.
- Every `plugin/` is tested against the conformance suite.
- Pure functions are tested with `hypothesis` for property-based testing.

### 20.3 Conformance Tests

```python
# tests/conformance/test_behavior_port.py
class BehaviorPortConformanceTest:
    """Any BehaviorPort implementation must pass these tests."""
    
    plugin_class: Type[BehaviorPort]  # Subclasses set this
    
    def test_step_is_pure(self):
        # Call step() twice with identical inputs; outputs must be identical
        ...
    
    def test_step_returns_valid_behavior_result(self):
        ...
    
    def test_initialize_is_idempotent(self):
        ...
```

Each built-in plugin has a test class that inherits from the conformance suite:

```python
class TestRandomBehavior(BehaviorPortConformanceTest):
    plugin_class = RandomBehavior
```

External plugins can also inherit these conformance tests to validate compliance.

### 20.4 Determinism Tests

```python
def test_determinism(config_path):
    """Run the same experiment twice. Output must be byte-identical."""
    result_a = ExperimentRunner.run(config_path)
    result_b = ExperimentRunner.run(config_path)
    assert result_a == result_b
```

Determinism tests run in CI on every pull request.

### 20.5 Coverage Target

- **Core domain**: ≥ 95% coverage
- **Ports (ABCs)**: 100% (trivial — abstract)
- **Built-in plugins**: ≥ 90% coverage
- **Application layer**: ≥ 85% coverage
- **CLI**: ≥ 70% coverage (integration tested)

---

## 21. Performance Considerations

### 21.1 MVP Performance Profile

At MVP (1,000 nodes, 10,000 ticks):
- Target: < 30 seconds wall-clock on a single core
- Memory target: < 500MB

### 21.2 Known Bottlenecks and Mitigations

| Bottleneck | Root Cause | Mitigation |
|---|---|---|
| Event queue at 100k events | `heapq` is efficient but Python overhead accumulates | Profile first; consider `sortedcontainers.SortedList` or C extension |
| Per-node Python function call overhead | Dynamic dispatch for `BehaviorPort.step()` | `BatchBehavior` extension interface for vectorized NumPy updates |
| Message delivery at broadcast scale | O(N) deliveries per message | Cap broadcast via topology; use gossip as default at scale |
| Metric collection | Event fan-out to all collectors | Collector subscription filtering at dispatch time |
| Node state serialization (for export) | Deep copy of `NodeState` per tick | Incremental delta export; only serialize on state change |

### 21.3 Scalability Path

```
MVP (1k nodes)     → Single-threaded Python, heapq
Scale 1 (10k)      → BatchBehavior + NumPy vectorization
Scale 2 (100k)     → Partitioned multiprocessing, async message delivery
Scale 3 (1M+)      → Rust core (see §22)
```

### 21.4 Profiling Infrastructure

The `MetricsEngine` tracks wall-clock CPU time per simulation phase as a built-in metric. This is always on at `DEBUG` level, enabling performance regression detection across versions.

---

## 22. Future Rust Migration Strategy

### 22.1 Migration Philosophy

Python and Rust share the same **conceptual architecture**. The Rust migration is a **reimplementation**, not a redesign. The Python codebase is the reference implementation and continues to be maintained for prototyping.

The target is a **hybrid model**:
- Python: experiment configuration, plugin authoring, visualization, analysis
- Rust: simulation hot loop, event queue, node state updates, message routing

### 22.2 Architectural Alignment

| Python Concept | Rust Equivalent |
|---|---|
| `@dataclass(frozen=True)` | `struct` + `#[derive(Clone)]` |
| `BehaviorPort (ABC)` | `trait Behavior` |
| `EventQueue (heapq)` | `BinaryHeap<Event>` |
| `NodeId = NewType(str)` | `struct NodeId(u64)` (more efficient) |
| `Dict[NodeId, Node]` | `HashMap<NodeId, Node>` |
| `Optional[T]` | `Option<T>` |
| `List[T]` | `Vec<T>` |
| `FrozenSet[T]` | `HashSet<T>` |

### 22.3 Design Decisions Made Now for Rust Compatibility

1. **No default method implementations in ports**: Python ABCs with default methods map poorly to Rust traits. Keep all port methods abstract.

2. **No multiple inheritance**: Python `mixin` patterns don't exist in Rust. Use composition exclusively.

3. **Explicit ownership semantics**: Python code is written as if ownership matters — nodes don't share references to the same state object.

4. **No dynamic typing**: Full type annotations everywhere. `Any` types in plugin configs are isolated at the boundary.

5. **Integer IDs**: `NodeId` is typed as `int` internally (not `str`). String names are metadata only.

6. **Message passing, not shared state**: Nodes communicate only via messages. No shared `Environment` pointer in node behavior — only via `EnvironmentQueryEvent`.

### 22.4 Python-Rust Interface Strategy

When Rust core is introduced:

```
Python Research Code
    │  (via PyO3 bindings)
    ▼
Rust Core Engine
├── EventQueue
├── NodeManager
├── Scheduler
└── CommunicationLayer

Python Plugin Callbacks
    │  (PyO3 function calls back into Python)
    ▼
BehaviorPort.step() — still in Python for flexibility
```

This allows compute-critical paths to move to Rust while keeping research-facing behavior logic in Python where iteration speed matters more than execution speed.

### 22.5 Migration Phases

```
Phase A (Year 1–2): Pure Python, full architecture in place
Phase B (Year 2–3): Rust EventQueue + Scheduler (drop-in via PyO3)
Phase C (Year 3–4): Rust NodeManager + CommunicationLayer
Phase D (Year 4+):  Full Rust core; Python for plugins and analysis only
```

---

## Appendix A: Type Aliases Reference

```python
NodeId       = NewType('NodeId', int)
EventId      = NewType('EventId', int)
VirtualTime  = NewType('VirtualTime', float)
MessageId    = NewType('MessageId', int)
MetricName   = NewType('MetricName', str)
PluginPath   = NewType('PluginPath', str)   # fully qualified class path
Seed         = NewType('Seed', int)
```

---

## Appendix B: Glossary

| Term | Definition |
|---|---|
| **Port** | An abstract interface (ABC) defined in the core domain that plugins implement |
| **Adapter** | A concrete implementation of a Port, living in `simul8/plugins/` |
| **Event** | An immutable record of something that happened or will happen at a virtual time |
| **BehaviorResult** | The output of `BehaviorPort.step()` — next state + outbound messages + scheduled events |
| **Virtual Time** | Dimensionless simulation time that advances only when the engine processes events |
| **Tick** | A recurring `TickEvent` used to simulate periodic behavior in otherwise event-driven simulations |
| **Experiment** | A fully-specified simulation run: config + seed + plugins |
| **Run** | One execution of an Experiment (multiple runs per experiment for statistical validity) |
| **Conformance Test** | A test suite that any plugin implementing a given Port must pass |
| **Determinism** | Identical seed + config + plugins → identical output, always |

---

*Document end. Next steps: implement MVP skeleton with core/, domain/, ports/ directories and CI pipeline.*
