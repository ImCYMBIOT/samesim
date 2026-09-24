"""
External validation 2/5: gossip convergence vs. an independent reference
implementation.

There's no established third-party library for push-gossip averaging the
way NDlib covers epidemics or NetworkX covers graph structure, so this
reference is written fresh from the algorithm's own written specification
(GossipBehavior's docstring: "1. Average own value with any received
messages. 2. Select k random neighbors and send current value to each"),
using numpy array operations rather than Simul8's agent/message/event
architecture -- a structurally independent implementation of the same
spec, not a copy of GossipBehavior's code.

Checks statistical equivalence (convergence-tick distribution, final
variance-reduction ratio) across repeated seeds on the identical graph,
not bit-identical trajectories -- the two implementations consume
randomness completely differently.
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

import networkx as nx
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from simul8_harness import networkx_to_topology_graph, run_simul8  # noqa: E402

# Repo root, derived from this file so the script runs from any checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from simul8.domain.ids import AgentId  # noqa: E402
from simul8.plugins.behaviors.gossip_behavior import GossipBehavior  # noqa: E402
from simul8.plugins.communication.gossip import GossipProtocol  # noqa: E402
from simul8.plugins.metrics.convergence import ConvergenceMetric  # noqa: E402

N = 300
AVG_DEGREE = 8
FAN_OUT = 2
TICKS = 40
N_SEEDS = 15
CONVERGENCE_FRACTION = 0.01


def reference_gossip(adjacency: list[list[int]], ticks: int, fan_out: int, seed: int) -> list[float]:
    """Independent numpy reference: array-based, 1-tick delivery latency,
    same push-and-average rule, no Simul8 code involved."""
    rng = np.random.default_rng(seed)
    n = len(adjacency)
    values = rng.uniform(0.0, 1.0, size=n)
    inbox: list[list[float]] = [[] for _ in range(n)]

    variance_series = [float(np.var(values))]
    for _tick in range(ticks):
        next_inbox: list[list[float]] = [[] for _ in range(n)]
        for i in range(n):
            if inbox[i]:
                values[i] = (values[i] + sum(inbox[i])) / (1 + len(inbox[i]))
            neighbors = adjacency[i]
            if neighbors:
                k = min(fan_out, len(neighbors))
                targets = rng.choice(neighbors, size=k, replace=False)
                for t in targets:
                    next_inbox[int(t)].append(values[i])
        inbox = next_inbox
        variance_series.append(float(np.var(values)))
    return variance_series


def convergence_tick(series: list[float], threshold_fraction: float) -> int | None:
    threshold = series[0] * threshold_fraction
    for i, v in enumerate(series):
        if v <= threshold:
            return i
    return None


def run_simul8_gossip(graph, seed: int) -> list[float]:
    series = run_simul8(
        graph=graph,
        behavior=GossipBehavior(),
        behavior_config={"initial_value_range": [0.0, 1.0], "fan_out": FAN_OUT},
        comm_protocol=GossipProtocol(),
        comm_config={},
        metric_collectors=[ConvergenceMetric()],
        seed=seed,
        max_virtual_time=TICKS,
        name=f"gossip_vs_ref_s{seed}",
    )
    return [r.value for r in series[0].records]


if __name__ == "__main__":
    g_nx = nx.erdos_renyi_graph(N, AVG_DEGREE / (N - 1), seed=7)
    adjacency = [list(g_nx.neighbors(i)) for i in range(N)]
    agent_ids = [AgentId(i) for i in range(N)]
    graph = networkx_to_topology_graph(g_nx, agent_ids)

    ref_ticks, simul8_ticks = [], []
    for seed in range(1, N_SEEDS + 1):
        ref_series = reference_gossip(adjacency, TICKS, FAN_OUT, seed=seed)
        simul8_series = run_simul8_gossip(graph, seed=seed)

        t_ref = convergence_tick(ref_series, CONVERGENCE_FRACTION)
        t_simul8 = convergence_tick(simul8_series, CONVERGENCE_FRACTION)
        ref_ticks.append(t_ref if t_ref is not None else TICKS)
        simul8_ticks.append(t_simul8 if t_simul8 is not None else TICKS)
        print(f"seed={seed:2d}  reference converged at tick={t_ref}   simul8 converged at tick={t_simul8}", flush=True)

    print()
    print(f"=== Summary over {N_SEEDS} seeds (n={N}, avg_degree={AVG_DEGREE}, fan_out={FAN_OUT}) ===")
    print(f"reference: mean={statistics.mean(ref_ticks):.2f} std={statistics.stdev(ref_ticks):.2f} range=[{min(ref_ticks)},{max(ref_ticks)}]")
    print(f"simul8:    mean={statistics.mean(simul8_ticks):.2f} std={statistics.stdev(simul8_ticks):.2f} range=[{min(simul8_ticks)},{max(simul8_ticks)}]")
