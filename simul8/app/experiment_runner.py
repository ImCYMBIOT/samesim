"""
ExperimentRunner — assembles and executes a simulation experiment.

This is the single entry point for all experiment execution.
It wires together all core modules and plugins, runs the engine,
and exports results. Nothing in core/ or plugins/ knows this module exists.

Assembly order (strict — each step depends on previous):
    1. Load config (frozen)
    2. Initialize randomness (seed)
    3. Load all plugins (validate interfaces)
    4. Create agents + initialize behavior states
    5. Build topology
    6. Initialize communication protocol
    7. Register metric collectors
    8. Assemble core modules (EventQueue, TimeManager, Scheduler, Engine)
    9. engine.run()
   10. Export results via persistence adapters
"""
from __future__ import annotations

import dataclasses
import difflib
import json
import logging
import time
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ..core.agent_registry import AgentRegistry
from ..core.communication_layer import CommunicationLayer
from ..core.engine import SimulationEngine
from ..core.event_queue import EventQueue
from ..core.metrics_engine import MetricsEngine
from ..core.randomness_manager import RandomnessManager
from ..core.scheduler import Scheduler
from ..core.time_manager import TimeManager
from ..core.topology_manager import TopologyManager
from ..domain.experiment import ExperimentConfig
from ..domain.ids import AgentId
from ..domain.topology import TopologyGraph
from ..ports.behavior import BehaviorPort
from ..ports.communication import CommunicationProtocolPort
from ..ports.metric_collector import MetricCollectorPort
from ..ports.persistence import PersistencePort
from ..ports.topology_dynamics import TopologyDynamicsPort
from ..ports.topology_generator import TopologyGeneratorPort
from .config_loader import ConfigLoader, ConfigValidationError
from .plugin_loader import PluginLoader

logger = logging.getLogger(__name__)


def check_activation_compatible(behavior: BehaviorPort, config: ExperimentConfig) -> None:
    """Refuse to run a behavior under an activation mode it wasn't written for.

    Shared by ExperimentRunner and the validation harness. The failure mode
    it prevents is silent: a tick-driven behavior under event activation
    runs once at t=0 and never again, and the experiment "completes" with
    numbers that look like a protocol that never converged.

    Raises:
        ConfigValidationError: naming the behavior, the requested mode and
            the modes it supports.
    """
    mode = config.simulation.activation
    supported = getattr(behavior, "activation_modes", frozenset({"synchronous"}))
    if mode not in supported:
        raise ConfigValidationError(
            f"{type(behavior).__name__} does not support simulation.activation="
            f"'{mode}' (it supports: {sorted(supported)}). A behavior written for "
            f"one mode would run incorrectly -- not fail -- under another."
        )


class TrackedConfig(dict):
    """One plugin's plugin_configs section, recording which keys it looked at.

    Behaves exactly like the plain dict it wraps. Any access that looks a key
    up (``[]``, get, ``in``) marks that key read; any access that walks the
    whole mapping (iteration, keys/items/values, copy, ``**`` unpacking)
    marks every key read, since the plugin could have used any of them.
    """

    def __init__(self, data: dict[str, Any]) -> None:
        super().__init__(data)
        self.read: set[str] = set()

    def _all(self) -> None:
        self.read.update(dict.keys(self))

    def __getitem__(self, key):
        self.read.add(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        self.read.add(key)
        return super().get(key, default)

    def __contains__(self, key) -> bool:
        self.read.add(key)
        return super().__contains__(key)

    def __iter__(self):
        self._all()
        return super().__iter__()

    def keys(self):
        self._all()
        return super().keys()

    def items(self):
        self._all()
        return super().items()

    def values(self):
        self._all()
        return super().values()

    def copy(self) -> dict[str, Any]:
        self._all()
        return dict(super().items())

    def unread(self) -> list[str]:
        return sorted(k for k in dict.keys(self) if k not in self.read)


def _class_name(class_path: str) -> str:
    return class_path.rsplit(".", 1)[-1]


def _did_you_mean(name: str, candidates) -> str:
    close = difflib.get_close_matches(name, sorted(candidates), n=1)
    return f" Did you mean '{close[0]}'?" if close else ""


def plugin_config_sections(config: ExperimentConfig) -> dict[str, TrackedConfig]:
    """Check plugin_configs' section names; return a tracked section per configurable plugin.

    A plugin_configs section that nothing reads would be silently ignored,
    and the plugin would quietly run on its defaults -- a run that looks
    fine and isn't the experiment that was asked for. So a section must
    name a behavior, protocol, topology or dynamics plugin in this
    experiment. Metrics and exporters receive no configuration at all, so a
    non-empty section for one of them is an error too.

    Raises:
        ConfigValidationError: naming the section, and the closest plugin
            name when there is one.
    """
    plugins = config.plugins
    configurable = {_class_name(p) for p in
                    (plugins.behavior, plugins.communication, plugins.topology, plugins.dynamics) if p}
    unconfigurable = {_class_name(p) for p in (*plugins.metrics, *plugins.persistence)}
    for name, section in config.plugin_configs.items():
        if section is not None and not isinstance(section, dict):
            raise ConfigValidationError(
                f"plugin_configs.{name} must be a mapping of option: value, got {section!r}"
            )
        if name in configurable:
            continue
        if name in unconfigurable:
            if section:
                raise ConfigValidationError(
                    f"plugin_configs.{name} has options {sorted(section)}, but {name} "
                    f"takes no configuration: metrics and exporters are never passed "
                    f"plugin_configs, so these would be silently ignored."
                )
            continue
        raise ConfigValidationError(
            f"plugin_configs.{name} does not match any plugin in this experiment, "
            f"so it would be silently ignored.{_did_you_mean(name, configurable)} "
            f"Configurable plugins here: {sorted(configurable)}."
        )
    return {name: TrackedConfig(config.plugin_configs.get(name) or {}) for name in configurable}


def check_plugin_configs_read(sections: dict[str, TrackedConfig]) -> None:
    """After setup, reject any option its plugin never looked at.

    An unread option had no effect: a misspelled key (the plugin used its
    default instead), or one that doesn't apply to the mode chosen (a
    'mean' with distribution: constant). Plugins read all their options
    during setup (initialize/generate), so by then every option that will
    ever matter has been read.

    Raises:
        ConfigValidationError: naming the plugin, each unused option, and
            the option the plugin did ask for that it most resembles.
    """
    for name, section in sections.items():
        unread = section.unread()
        if not unread:
            continue
        asked_for = section.read - set(dict.keys(section))
        hints = "".join(_did_you_mean(k, asked_for) for k in unread)
        raise ConfigValidationError(
            f"plugin_configs.{name}: option(s) {unread} had no effect -- {name} never "
            f"read them, so it ran on its defaults instead.{hints} Options {name} "
            f"read in this configuration: {sorted(section.read)}."
        )


def register_metric_collectors(
    collectors: list[MetricCollectorPort],
    agent_registry: AgentRegistry,
    topology: TopologyGraph,
) -> MetricsEngine:
    """Hand each collector its starting picture and register it.

    The one place collectors are set up, shared by ExperimentRunner and the
    external-validation harness so the two cannot drift apart again.

    Collectors only ever see immutable domain data: the TopologyGraph and a
    read-only snapshot of every agent's initial state. Never the registry or
    topology manager themselves -- those are core objects with mutating
    methods, and handing them to plugins is what the architecture forbids.

    Raises:
        TypeError: If a collector still defines the removed configure()
            hook. It would otherwise silently never be called, and the
            metric would quietly report nothing -- a plausible-looking
            wrong answer rather than an error.
    """
    initial_states = MappingProxyType({
        agent.agent_id: MappingProxyType(agent.state.to_dict())
        for agent in agent_registry.iter_agents()
    })
    engine = MetricsEngine()
    for collector in collectors:
        if hasattr(collector, "configure"):
            raise TypeError(
                f"{type(collector).__name__} defines configure(), which is no "
                f"longer called. Override on_setup(topology, initial_states) "
                f"instead -- see MetricCollectorPort."
            )
        collector.on_setup(topology, initial_states)
        engine.register(collector)
    return engine


class ExperimentRunner:
    """Assembles and runs a simulation experiment from a YAML config file.

    Usage:
        runner = ExperimentRunner()
        runner.run("examples/gossip_1000_agents.yaml", output_dir="./results")
    """

    def __init__(
        self,
        config_loader: ConfigLoader | None = None,
        plugin_loader: PluginLoader | None = None,
    ) -> None:
        self._config_loader = config_loader or ConfigLoader()
        self._plugin_loader = plugin_loader or PluginLoader()

    def run(
        self,
        config_path: Path | str,
        output_dir: Path | str | None = None,
    ) -> None:
        """Execute a full simulation experiment end-to-end.

        Args:
            config_path: Path to the YAML experiment config file.
            output_dir:  Directory for result files (default: ./results).
        """
        # --- 1. Load config ---
        config = self._config_loader.load(config_path)
        output_path = Path(output_dir) if output_dir else Path("./results")
        output_path.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Loaded config '%s' | seed=%d | agents=%d",
            config.name, config.seed, config.simulation.num_agents,
        )

        # --- 2. Randomness ---
        rng_manager = RandomnessManager()
        rng_manager.initialize(config.seed)

        # --- 3. Load plugins ---
        behavior: BehaviorPort = self._plugin_loader.load(
            config.plugins.behavior, BehaviorPort
        )
        topology_generator: TopologyGeneratorPort = self._plugin_loader.load(
            config.plugins.topology, TopologyGeneratorPort
        )
        comm_protocol: CommunicationProtocolPort = self._plugin_loader.load(
            config.plugins.communication, CommunicationProtocolPort
        )
        check_activation_compatible(behavior, config)
        dynamics: TopologyDynamicsPort | None = (
            self._plugin_loader.load(config.plugins.dynamics, TopologyDynamicsPort)
            if config.plugins.dynamics else None
        )
        metric_collectors: list[MetricCollectorPort] = [
            self._plugin_loader.load(cp, MetricCollectorPort)
            for cp in config.plugins.metrics
        ]
        persistence_adapters: list[PersistencePort] = [
            self._plugin_loader.load(cp, PersistencePort)
            for cp in config.plugins.persistence
        ]

        sections = plugin_config_sections(config)

        # --- 4. Create agents + initialize behavior ---
        agent_registry = AgentRegistry()
        behavior_class_name = _class_name(config.plugins.behavior)
        behavior_config = sections[behavior_class_name]

        logger.info("Initializing %d agents...", config.simulation.num_agents)
        agent_ids: list[AgentId] = []
        for i in range(config.simulation.num_agents):
            agent_id = AgentId(i)
            agent_rng = rng_manager.get_agent_rng(agent_id)
            initial_state = behavior.initialize(agent_id, behavior_config, agent_rng)
            created_id = agent_registry.create_agent(initial_state=initial_state)
            agent_ids.append(created_id)

        # --- 5. Build topology ---
        topology_manager = TopologyManager()
        topology_class_name = _class_name(config.plugins.topology)
        logger.info("Building topology (%s)...", topology_class_name)
        topology_manager.build(
            topology_generator, agent_ids, sections[topology_class_name], rng_manager.global_rng
        )

        # --- 6. Initialize communication protocol ---
        comm_protocol.initialize(topology_manager.topology,
                                 sections[_class_name(config.plugins.communication)],
                                 rng_manager.global_rng)

        # --- 6b. Churn (optional) ---
        # Its own RNG stream, so adding churn never shifts the protocol's or
        # the topology generator's draws.
        if dynamics is not None:
            dynamics.initialize(topology_manager.topology,
                                sections[_class_name(config.plugins.dynamics)],
                                rng_manager.stream("dynamics"))

        # Every plugin has now done its setup, so every option that will ever
        # matter has been read. (With no agents, the behavior never ran.)
        if not agent_ids:
            sections.pop(behavior_class_name)
        check_plugin_configs_read(sections)

        def join_agent(agent_id: AgentId):
            # A joining agent is initialized exactly as it would have been
            # at t=0: same behavior config, same per-agent RNG (seed XOR id).
            return behavior.initialize(agent_id, behavior_config, rng_manager.get_agent_rng(agent_id))

        # --- 7. Register metric collectors ---
        metrics_engine = register_metric_collectors(
            metric_collectors, agent_registry, topology_manager.topology
        )

        # --- 8. Assemble core ---
        event_queue = EventQueue()
        time_manager = TimeManager()
        scheduler = Scheduler(event_queue, time_manager)
        comm_layer = CommunicationLayer(comm_protocol)

        engine = SimulationEngine(
            scheduler=scheduler,
            time_manager=time_manager,
            agent_registry=agent_registry,
            topology_manager=topology_manager,
            communication_layer=comm_layer,
            metrics_engine=metrics_engine,
            behavior=behavior,
            config=config,
            dynamics=dynamics,
            join_agent=join_agent,
        )

        # --- 9. Run with wall-clock timing ---
        start_wall_time = time.perf_counter()
        engine.run()
        elapsed_wall_time = time.perf_counter() - start_wall_time

        # --- 10. Export ---
        series = metrics_engine.get_all_series()
        written_paths = []
        for adapter in persistence_adapters:
            written = adapter.write(series, config, output_path)
            for path in written:
                written_paths.append(str(path))
                logger.info("Wrote results: %s", path)

        # --- 11. Write summaries ---
        self._write_summaries(config, elapsed_wall_time, written_paths, output_path)

    def _write_summaries(
        self,
        config: ExperimentConfig,
        elapsed_wall_time: float,
        written_paths: list[str],
        output_dir: Path,
    ) -> None:
        # The complete resolved config (defaults filled in), so the summary
        # alone is enough to re-run the experiment. Built from the dataclass
        # fields rather than listed by hand: a hand-written list silently
        # misses every field added after it was written, which is how
        # activation, dynamics, metrics and plugin_configs went unrecorded.
        resolved = dataclasses.asdict(config)
        summary_data = {
            # Flat keys: read by `simul8 visualize`, kept stable.
            "experiment_name": config.name,
            "seed": config.seed,
            "num_agents": config.simulation.num_agents,
            "max_virtual_time": config.simulation.max_virtual_time,
            "tick_interval": config.simulation.tick_interval,
            "behavior_plugin": config.plugins.behavior,
            "communication_plugin": config.plugins.communication,
            "topology_plugin": config.plugins.topology,
            "schema_version": config.schema_version,
            "wall_clock_runtime_seconds": elapsed_wall_time,
            "output_files": written_paths,
            "config": resolved,
        }

        json_path = output_dir / "summary.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=2, default=str)
        logger.info("Wrote summary: %s", json_path)

        md_path = output_dir / "summary.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(f"# Experiment Summary: {config.name}\n\n")
            f.write(f"- **Seed**: {config.seed}\n")
            for section in ("simulation", "plugins"):
                for key, value in resolved[section].items():
                    if value in (None, [], ()):
                        continue
                    shown = ", ".join(f"`{v}`" for v in value) if isinstance(value, (list, tuple)) else f"`{value}`"
                    f.write(f"- **{section}.{key}**: {shown}\n")
            f.write(f"- **Wall-clock Runtime**: {elapsed_wall_time:.4f} seconds\n\n")
            if config.plugin_configs:
                f.write("## Plugin configs\n\n```json\n")
                f.write(json.dumps(config.plugin_configs, indent=2, default=str))
                f.write("\n```\n\n")
            f.write("## Output Files\n")
            for path in written_paths:
                f.write(f"- `{path}`\n")
        logger.info("Wrote summary: %s", md_path)

