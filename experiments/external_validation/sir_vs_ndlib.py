"""
External validation 1/5: SIR epidemic dynamics vs. NDlib.

NDlib (https://ndlib.readthedocs.io) is an independent, widely-used Python
library for diffusion/epidemic modeling on networks. Its SIRModel uses the
same discrete-time contact-process formulation as Simul8's
SirEpidemicBehavior: P(infection) = 1 - (1-beta)^k for a susceptible node
with k infected neighbors, P(recovery) = gamma per tick for an infected
node. Because the formulas match, running both on the IDENTICAL graph with
the SAME beta/gamma/initial-infected set should produce statistically
equivalent outbreak curves -- not bit-identical (different RNG streams),
but the same ballpark across repeated seeds.

This is a genuinely independent check: NDlib's implementation, RNG usage,
and codebase share nothing with Simul8's.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

import networkx as nx
import ndlib.models.ModelConfig as mc
import ndlib.models.epidemics as ep

sys.path.insert(0, str(Path(__file__).parent))
from simul8_harness import networkx_to_topology_graph, run_simul8  # noqa: E402

sys.path.insert(0, "/home/agnivesh/Desktop/simul8")
from simul8.domain.ids import AgentId  # noqa: E402
from simul8.plugins.behaviors.sir_behavior import SirEpidemicBehavior  # noqa: E402
from simul8.plugins.communication.broadcast import BroadcastProtocol  # noqa: E402
from simul8.plugins.metrics.sir_metrics import (  # noqa: E402
    SirInfectedMetric,
    SirRecoveredMetric,
    SirSusceptibleMetric,
)

N = 500
EDGE_PROB = 0.02  # avg degree ~10
BETA = 0.15
GAMMA = 0.1
INITIAL_INFECTED = 5
TICKS = 100
N_SEEDS = 20


def run_ndlib(graph_nx, seed: int) -> dict:
    model = ep.SIRModel(graph_nx, seed=seed)
    config = mc.Configuration()
    config.add_model_parameter("beta", BETA)
    config.add_model_parameter("gamma", GAMMA)
    config.add_model_initial_configuration("Infected", list(range(INITIAL_INFECTED)))
    model.set_initial_status(config)

    infected_over_time = []
    for it in model.iteration_bunch(TICKS, node_status=False):
        infected_over_time.append(it["node_count"].get(1, 0))

    final = model.status
    recovered_final = sum(1 for v in final.values() if v == 2)
    return {
        "peak_infected": max(infected_over_time),
        "final_recovered": recovered_final,
        "extinction_tick": next((i for i, v in enumerate(infected_over_time) if v == 0), None),
    }


def run_simul8_sir(graph_nx, agent_ids, graph, seed: int) -> dict:
    series = run_simul8(
        graph=graph,
        behavior=SirEpidemicBehavior(),
        behavior_config={"transmission_rate": BETA, "recovery_rate": GAMMA, "initial_infected": INITIAL_INFECTED},
        comm_protocol=BroadcastProtocol(),
        comm_config={},
        metric_collectors=[SirSusceptibleMetric(), SirInfectedMetric(), SirRecoveredMetric()],
        seed=seed,
        max_virtual_time=TICKS,
        name=f"sir_vs_ndlib_s{seed}",
    )
    by_name = {s.name: [r.value for r in s.records] for s in series}
    infected = by_name["sir_infected"]
    recovered = by_name["sir_recovered"]
    return {
        "peak_infected": max(infected),
        "final_recovered": recovered[-1],
        "extinction_tick": next((i for i, v in enumerate(infected) if v == 0), None),
    }


if __name__ == "__main__":
    results = {"ndlib": [], "simul8": []}
    for seed in range(1, N_SEEDS + 1):
        g_nx = nx.erdos_renyi_graph(N, EDGE_PROB, seed=1000)  # SAME graph every seed -- only epidemic RNG varies
        agent_ids = [AgentId(i) for i in range(N)]
        graph = networkx_to_topology_graph(g_nx, agent_ids)

        r_ndlib = run_ndlib(g_nx, seed=seed)
        r_simul8 = run_simul8_sir(g_nx, agent_ids, graph, seed=seed)
        results["ndlib"].append(r_ndlib)
        results["simul8"].append(r_simul8)
        print(f"seed={seed:2d}  ndlib: peak={r_ndlib['peak_infected']:4d} final_R={r_ndlib['final_recovered']:4d} ext={r_ndlib['extinction_tick']}"
              f"   simul8: peak={r_simul8['peak_infected']:6.0f} final_R={r_simul8['final_recovered']:6.0f} ext={r_simul8['extinction_tick']}",
              flush=True)

    def summarize(rows, key):
        vals = [r[key] for r in rows]
        return statistics.mean(vals), statistics.stdev(vals), min(vals), max(vals)

    print("\n=== Summary over", N_SEEDS, "seeds (same graph, n=", N, ", beta=", BETA, ", gamma=", GAMMA, ") ===")
    for key in ("peak_infected", "final_recovered"):
        m1, s1, lo1, hi1 = summarize(results["ndlib"], key)
        m2, s2, lo2, hi2 = summarize(results["simul8"], key)
        print(f"{key}: ndlib  mean={m1:.1f} std={s1:.1f} range=[{lo1},{hi1}]")
        print(f"{key}: simul8 mean={m2:.1f} std={s2:.1f} range=[{lo2},{hi2}]")

    out = Path("/tmp/claude-1000/-home-agnivesh-Desktop-simul8/8d6013d0-83ba-439f-8d2e-520098154174/scratchpad/external_validation")
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "sir_vs_ndlib.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote {out / 'sir_vs_ndlib.json'}")
