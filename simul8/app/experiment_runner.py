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
from ..ports.behavior import BehaviorPort
from ..ports.communication import CommunicationProtocolPort
from ..ports.metric_collector import MetricCollectorPort
from ..ports.persistence import PersistencePort
from ..ports.topology_generator import TopologyGeneratorPort
from .config_loader import ConfigLoader
from .plugin_loader import PluginLoader

logger = logging.getLogger(__name__)


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

        # --- 7. Register metric collectors ---
        metrics_engine = MetricsEngine()
        for collector in metric_collectors:
            # Optional two-phase init for collectors that need registry access
            # (e.g. future state-snapshotting metrics). Safe to call if not defined.
            if hasattr(collector, "configure"):
                collector.configure(agent_registry=agent_registry)
            metrics_engine.register(collector)

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
        )

        # --- 9. Run ---
        engine.run()

        # --- 10. Export ---
        series = metrics_engine.get_all_series()
        for adapter in persistence_adapters:
            written = adapter.write(series, config, output_path)
            for path in written:
                logger.info("Wrote results: %s", path)
