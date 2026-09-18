"""
Shared harness for external validation scripts.

Wires Simul8's real core (AgentRegistry, TopologyManager, CommunicationLayer,
MetricsEngine, EventQueue, TimeManager, Scheduler, SimulationEngine) exactly
as ExperimentRunner.run() does -- same code paths, same determinism
guarantees -- but accepts a pre-built TopologyGraph (e.g. constructed from a
NetworkX graph) instead of generating one from a plugin + config, and
returns MetricSeries objects in memory instead of writing CSVs.

This lets the external-validation scripts run Simul8 on the EXACT SAME graph
object as the comparison tool (NetworkX, NDlib), rather than two separately
generated graphs that are only statistically similar.
"""
from __future__ import annotations

import random
import sys
from typing import Any

sys.path.insert(0, "/home/agnivesh/Desktop/simul8")

from simul8.core.agent_registry import AgentRegistry  # noqa: E402
from simul8.core.communication_layer import CommunicationLayer  # noqa: E402
from simul8.core.engine import SimulationEngine  # noqa: E402
from simul8.core.event_queue import EventQueue  # noqa: E402
from simul8.core.metrics_engine import MetricsEngine  # noqa: E402
from simul8.core.randomness_manager import RandomnessManager  # noqa: E402
from simul8.core.scheduler import Scheduler  # noqa: E402
from simul8.core.time_manager import TimeManager  # noqa: E402
from simul8.core.topology_manager import TopologyManager  # noqa: E402
from simul8.domain.experiment import ExperimentConfig, PluginsConfig, SimulationConfig  # noqa: E402
from simul8.domain.ids import AgentId  # noqa: E402
from simul8.domain.topology import TopologyGraph  # noqa: E402
from simul8.ports.behavior import BehaviorPort  # noqa: E402
from simul8.ports.communication import CommunicationProtocolPort  # noqa: E402
from simul8.ports.metric_collector import MetricCollectorPort  # noqa: E402
from simul8.ports.topology_generator import TopologyGeneratorPort  # noqa: E402


class FixedTopology(TopologyGeneratorPort):
    """Wraps a pre-built TopologyGraph so it can be injected via the normal
    TopologyManager.build() call, bypassing on-the-fly generation entirely.
    Validation-only utility -- not part of the shipped plugin set."""

    def __init__(self, graph: TopologyGraph) -> None:
        self._graph = graph

    def generate(self, agent_ids, config, rng) -> TopologyGraph:  # noqa: D102
        return self._graph


def networkx_to_topology_graph(nx_graph, agent_ids: list[AgentId]) -> TopologyGraph:
    """Convert a NetworkX graph (nodes 0..n-1) into a Simul8 TopologyGraph."""
    adjacency: dict[AgentId, frozenset[AgentId]] = {}
    for i, aid in enumerate(agent_ids):
        adjacency[aid] = frozenset(AgentId(j) for j in nx_graph.neighbors(i))
    return TopologyGraph(agent_ids=frozenset(agent_ids), adjacency=adjacency)


def run_simul8(
    graph: TopologyGraph,
    behavior: BehaviorPort,
    behavior_config: dict[str, Any],
    comm_protocol: CommunicationProtocolPort,
    comm_config: dict[str, Any],
    metric_collectors: list[MetricCollectorPort],
    seed: int,
    max_virtual_time: float,
    tick_interval: float = 1.0,
    name: str = "external_validation",
) -> list:
    """Run a full Simul8 experiment on a pre-built graph; return MetricSeries list."""
    n = len(graph.agent_ids)
    config = ExperimentConfig(
        schema_version="1.0",
        name=name,
        seed=seed,
        simulation=SimulationConfig(num_agents=n, max_virtual_time=float(max_virtual_time), tick_interval=tick_interval),
        plugins=PluginsConfig(behavior="", communication="", topology="", metrics=(), persistence=()),
        plugin_configs={},
    )

    rng_manager = RandomnessManager()
    rng_manager.initialize(seed)

    agent_registry = AgentRegistry()
    agent_ids: list[AgentId] = []
    for i in range(n):
        agent_id = AgentId(i)
        agent_rng = rng_manager.get_agent_rng(agent_id)
        initial_state = behavior.initialize(agent_id, behavior_config, agent_rng)
        created_id = agent_registry.create_agent(initial_state=initial_state)
        agent_ids.append(created_id)

    topology_manager = TopologyManager()
    topology_manager.build(FixedTopology(graph), agent_ids, {}, rng_manager.global_rng)

    comm_protocol.initialize(topology_manager.topology, comm_config, rng_manager.global_rng)

    metrics_engine = MetricsEngine()
    for collector in metric_collectors:
        if hasattr(collector, "configure"):
            collector.configure(agent_registry=agent_registry, topology_manager=topology_manager)
        metrics_engine.register(collector)

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
    engine.run()

    return metrics_engine.get_all_series()
