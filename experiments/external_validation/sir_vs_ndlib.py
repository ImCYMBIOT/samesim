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

A third party referees: `reference_sir`, NDlib's SIRModel.iteration
transcribed into plain Python with its own RNG. If NDlib and the reference
agree, a difference between Simul8 and both is Simul8's.

Statistics per metric: mean with 95% CI for each implementation; Welch's
t-test for a difference; and TOST (two one-sided tests) for EQUIVALENCE
within +/-1% of the reference mean. "Not significantly different" is not
evidence of agreement; a passed equivalence test is.

History: the first version ran 20 seeds and reported "within 1.7%". An
outside review recomputed it: Welch t = 2.82, p = 0.008. The cause was
Simul8's seeding (seed XOR agent_id), which made replicates with different
seeds partly copies of each other and understated their spread; see the
README.
"""
from __future__ import annotations

import json
import math
import random
import statistics
import os
import sys
from pathlib import Path

import networkx as nx
from scipy import stats
import ndlib.models.ModelConfig as mc
import ndlib.models.epidemics as ep

sys.path.insert(0, str(Path(__file__).parent))
from simul8_harness import networkx_to_topology_graph, run_simul8  # noqa: E402

# Repo root, derived from this file so the script runs from any checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
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
N_SEEDS = 200
EQUIV_MARGIN = 0.01  # TOST margin, fraction of the reference mean


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


def reference_sir(graph_nx, seed: int) -> dict:
    """NDlib's SIRModel.iteration, transcribed; its own independent RNG."""
    rng = random.Random(f"reference/{seed}")
    adj = {u: sorted(graph_nx.neighbors(u)) for u in graph_nx}
    status = {u: (1 if u < INITIAL_INFECTED else 0) for u in graph_nx}
    infected = [sum(1 for v in status.values() if v == 1)]
    for _ in range(TICKS - 1):
        new = dict(status)
        for u, st_u in status.items():
            if st_u == 1:
                for v in adj[u]:
                    if status[v] == 0 and rng.random() < BETA:
                        new[v] = 1
                if rng.random() < GAMMA:
                    new[u] = 2
        status = new
        infected.append(sum(1 for v in status.values() if v == 1))
    return {
        "peak_infected": max(infected),
        "final_recovered": sum(1 for v in status.values() if v == 2),
        "extinction_tick": next((i for i, v in enumerate(infected) if v == 0), None),
    }


def ci95(values):
    m, se = statistics.mean(values), statistics.stdev(values) / math.sqrt(len(values))
    return m, 1.96 * se


def compare(a, b, margin):
    """Welch t-test for a difference; TOST for equivalence within +/-margin."""
    welch = stats.ttest_ind(a, b, equal_var=False)
    lower = stats.ttest_ind([x + margin for x in a], b, equal_var=False, alternative="greater")
    upper = stats.ttest_ind([x - margin for x in a], b, equal_var=False, alternative="less")
    return {"diff": statistics.mean(a) - statistics.mean(b), "welch_t": welch.statistic,
            "welch_p": welch.pvalue, "tost_p": max(lower.pvalue, upper.pvalue), "margin": margin}


if __name__ == "__main__":
    g_nx = nx.erdos_renyi_graph(N, EDGE_PROB, seed=1000)  # SAME graph every seed -- only epidemic RNG varies
    agent_ids = [AgentId(i) for i in range(N)]
    graph = networkx_to_topology_graph(g_nx, agent_ids)
    results = {"ndlib": [], "simul8": [], "reference": []}
    for seed in range(1, N_SEEDS + 1):
        results["ndlib"].append(run_ndlib(g_nx, seed=seed))
        results["simul8"].append(run_simul8_sir(g_nx, agent_ids, graph, seed=seed))
        results["reference"].append(reference_sir(g_nx, seed=seed))
        if seed % 20 == 0:
            print(f"{seed}/{N_SEEDS} seeds", flush=True)

    summary = {}
    print(f"\n=== {N_SEEDS} seeds, same graph (n={N}, beta={BETA}, gamma={GAMMA}) ===")
    for key in ("peak_infected", "final_recovered", "extinction_tick"):
        cols = {k: [r[key] for r in v if r[key] is not None] for k, v in results.items()}
        ref_mean = statistics.mean(cols["reference"])
        margin = EQUIV_MARGIN * ref_mean
        summary[key] = {k: dict(zip(("mean", "ci95"), ci95(v))) for k, v in cols.items()}
        print(f"\n{key}:")
        for k, v in cols.items():
            m, h = ci95(v)
            print(f"  {k:10} {m:8.2f} +/- {h:.2f}  (sd {statistics.stdev(v):.2f}, n={len(v)})")
        for a, b in (("simul8", "reference"), ("simul8", "ndlib"), ("ndlib", "reference")):
            c = compare(cols[a], cols[b], margin)
            summary[key][f"{a}_vs_{b}"] = c
            verdict = "EQUIVALENT" if c["tost_p"] < 0.05 else "not shown equivalent"
            print(f"  {a} - {b}: {c['diff']:+.2f}  Welch p={c['welch_p']:.3f}  "
                  f"TOST(+/-{margin:.2f}) p={c['tost_p']:.2g} -> {verdict}")

    out = Path(__file__).resolve().parent
    with open(out / "sir_vs_ndlib_results.json", "w") as f:
        json.dump({"runs": results, "summary": summary}, f, indent=2)
    print(f"\nWrote {out / 'sir_vs_ndlib_results.json'}")
