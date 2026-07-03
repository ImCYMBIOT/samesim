# Simul8

Modular event-driven simulation platform for distributed systems research.

The core engine is domain-agnostic and manages only agents, virtual time, event scheduling, communication routing, and metric dispatch. All domain-specific details (agent behaviors, network topologies, routing protocols, and metric collection) are implemented as pluggable adapters.

## Features

- **Clean Hexagonal Architecture**: Strictly separated domain, ports, core engine, and application layers.
- **Deterministic and Reproducible**: Built-in seedable randomness per agent (`seed XOR agent_id`) ensures 100% reproducible runs regardless of concurrency or scale.
- **Pluggable Architecture**: Easily swap behaviors, communication protocols, network topologies, metrics, and persistence exporters.
- **High Performance & Lean**: Native Python with zero heavy dependencies (YAML library only). Built with future Rust portability in mind.

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

For a deep dive into the architecture, component design, simulation loop lifecycle, and a guide on how to extend Simul8 by writing your own plugins, see the [Extended Documentation & Developer Guide](docs/extended_documentation.md).


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
