"""
ExperimentConfig — the immutable specification of a simulation experiment.

Every field is frozen at load time. No runtime mutation is permitted.
This guarantees that two runs with the same ExperimentConfig and seed
produce identical outputs.

The configuration is loaded from YAML/JSON by ConfigLoader (app layer)
and passed into SimulationEngine and all plugins as a read-only record.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SimulationConfig:
    """Parameters that control the simulation loop."""

    num_agents: int
    max_virtual_time: float
    tick_interval: float = 1.0


@dataclass(frozen=True)
class PluginsConfig:
    """Fully-qualified class paths for all active plugins.

    Each path is resolved by PluginLoader at experiment start.
    Example: "simul8.plugins.communication.gossip.GossipProtocol"
    """

    behavior: str
    communication: str
    topology: str
    metrics: tuple[str, ...] = ()
    persistence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExperimentConfig:
    """Complete, immutable specification of a simulation experiment.

    Frozen at load time. All plugins and the engine receive this
    as a read-only reference. Never mutate after construction.

    Attributes:
        schema_version:  Config file schema version for migration checks.
        name:            Human-readable experiment identifier.
        seed:            Global random seed. Determines all randomness.
        simulation:      Core simulation loop parameters.
        plugins:         Plugin class paths.
        plugin_configs:  Per-plugin configuration dicts keyed by class name.
                         Example key: "GossipBehavior", "ErdosRenyiTopology".
    """

    schema_version: str
    name: str
    seed: int
    simulation: SimulationConfig
    plugins: PluginsConfig
    # Note: dict is technically mutable inside the frozen container.
    # Treat as read-only. Future: wrap in types.MappingProxyType if needed.
    plugin_configs: dict[str, dict[str, Any]] = field(
        default_factory=dict, hash=False, compare=False
    )
