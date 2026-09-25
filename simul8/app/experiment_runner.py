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

import logging
from pathlib import Path
from types import MappingProxyType

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

        # --- 4. Create agents + initialize behavior ---
        agent_registry = AgentRegistry()
        behavior_class_name = config.plugins.behavior.rsplit(".", 1)[-1]
        behavior_config = config.plugin_configs.get(behavior_class_name, {})

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
        topology_class_name = config.plugins.topology.rsplit(".", 1)[-1]
        topology_config = config.plugin_configs.get(topology_class_name, {})
        logger.info("Building topology (%s)...", topology_class_name)
        topology_manager.build(
            topology_generator, agent_ids, topology_config, rng_manager.global_rng
        )

        # --- 6. Initialize communication protocol ---
        comm_class_name = config.plugins.communication.rsplit(".", 1)[-1]
        comm_config = config.plugin_configs.get(comm_class_name, {})
        comm_protocol.initialize(topology_manager.topology, comm_config, rng_manager.global_rng)

        # --- 6b. Churn (optional) ---
        # Its own RNG stream, so adding churn never shifts the protocol's or
        # the topology generator's draws.
        if dynamics is not None:
            dyn_name = config.plugins.dynamics.rsplit(".", 1)[-1]
            dynamics.initialize(topology_manager.topology,
                                config.plugin_configs.get(dyn_name, {}),
                                rng_manager.stream("dynamics"))

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
        import time
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
        import json
        
        summary_data = {
            "experiment_name": config.name,
            "seed": config.seed,
            "num_agents": config.simulation.num_agents,
            "max_virtual_time": config.simulation.max_virtual_time,
            "tick_interval": config.simulation.tick_interval,
            "behavior_plugin": config.plugins.behavior,
            "communication_plugin": config.plugins.communication,
            "topology_plugin": config.plugins.topology,
            "wall_clock_runtime_seconds": elapsed_wall_time,
            "output_files": written_paths,
            "schema_version": config.schema_version,
        }

        # Write summary.json
        json_path = output_dir / "summary.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=2)
        logger.info("Wrote summary: %s", json_path)

        # Write summary.md
        md_path = output_dir / "summary.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(f"# Experiment Summary: {config.name}\n\n")
            f.write(f"- **Seed**: {config.seed}\n")
            f.write(f"- **Agents**: {config.simulation.num_agents}\n")
            f.write(f"- **Max Virtual Time**: {config.simulation.max_virtual_time}\n")
            f.write(f"- **Behavior**: `{config.plugins.behavior}`\n")
            f.write(f"- **Communication**: `{config.plugins.communication}`\n")
            f.write(f"- **Topology**: `{config.plugins.topology}`\n")
            f.write(f"- **Wall-clock Runtime**: {elapsed_wall_time:.4f} seconds\n\n")
            f.write("## Output Files\n")
            for path in written_paths:
                f.write(f"- `{path}`\n")
        logger.info("Wrote summary: %s", md_path)

