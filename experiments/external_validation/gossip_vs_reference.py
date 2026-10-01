"""
External validation 2/5: gossip convergence vs. an independent reference
implementation.

There's no established third-party library for push-gossip averaging the
way NDlib covers epidemics or NetworkX covers graph structure, so this
reference is written fresh from the algorithm's own written specification
(GossipBehavior's docstring: "1. Average own value with any received
messages. 2. Select k random neighbors and send current value to each"),
using numpy array operations rather than SameSim's agent/message/event
architecture -- a structurally independent implementation of the same
spec, not a copy of GossipBehavior's code.

Checks statistical equivalence of the convergence-tick distribution across
repeated seeds on the identical graph, not bit-identical trajectories -- the
two implementations consume randomness completely differently. Welch's
t-test for a difference, and TOST for equivalence within +/-0.5 tick (the
resolution of the measurement), fixed before running.

History: the first version compared 15 seeds and reported "overlapping
distributions" (11.3 vs 12.3 ticks). That difference was an indexing
off-by-one in this reference, not in SameSim: it recorded the initial
variance AND the first (no-op, empty-inbox) tick as separate entries, so its
tick numbers ran one ahead of SameSim's, where tick 0 is the first step. The
reference now records one entry per tick, tick 0 first, as SameSim does.
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path

import networkx as nx
import numpy as np
from scipy import stats

sys.path.insert(0, str(Path(__file__).parent))
from samesim_harness import networkx_to_topology_graph, run_samesim  # noqa: E402

# Repo root, derived from this file so the script runs from any checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from samesim.domain.ids import AgentId  # noqa: E402
from samesim.plugins.behaviors.gossip_behavior import GossipBehavior  # noqa: E402
from samesim.plugins.communication.gossip import GossipProtocol  # noqa: E402
from samesim.plugins.metrics.convergence import ConvergenceMetric  # noqa: E402

N = 300
AVG_DEGREE = 8
FAN_OUT = 2
TICKS = 40
N_SEEDS = 200
EQUIV_MARGIN_TICKS = 0.5
CONVERGENCE_FRACTION = 0.01


def reference_gossip(adjacency: list[list[int]], ticks: int, fan_out: int, seed: int) -> list[float]:
    """Independent numpy reference: array-based, 1-tick delivery latency,
    same push-and-average rule, no SameSim code involved."""
    rng = np.random.default_rng(seed)
    n = len(adjacency)
    values = rng.uniform(0.0, 1.0, size=n)
    inbox: list[list[float]] = [[] for _ in range(n)]

    # One entry per tick, recorded after the tick, tick 0 first -- SameSim's
    # convention (its first step is tick 0; inboxes are empty then, so the
    # tick-0 variance equals the initial variance).
    variance_series = []
    for _tick in range(ticks + 1):
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


def run_samesim_gossip(graph, seed: int) -> list[float]:
    series = run_samesim(
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

    ref_ticks, samesim_ticks = [], []
    for seed in range(1, N_SEEDS + 1):
        t_ref = convergence_tick(reference_gossip(adjacency, TICKS, FAN_OUT, seed=seed), CONVERGENCE_FRACTION)
        t_s8 = convergence_tick(run_samesim_gossip(graph, seed=seed), CONVERGENCE_FRACTION)
        assert t_ref is not None and t_s8 is not None, "a run didn't converge within TICKS"
        ref_ticks.append(t_ref)
        samesim_ticks.append(t_s8)

    def ci(v):
        return statistics.mean(v), 1.96 * statistics.stdev(v) / math.sqrt(len(v))

    welch = stats.ttest_ind(samesim_ticks, ref_ticks, equal_var=False)
    m = EQUIV_MARGIN_TICKS
    lo = stats.ttest_ind([x + m for x in samesim_ticks], ref_ticks, equal_var=False, alternative="greater")
    hi = stats.ttest_ind([x - m for x in samesim_ticks], ref_ticks, equal_var=False, alternative="less")
    tost_p = max(lo.pvalue, hi.pvalue)
    print(f"=== {N_SEEDS} seeds (n={N}, avg_degree={AVG_DEGREE}, fan_out={FAN_OUT}), ticks to 1% of initial variance ===")
    for name, v in (("reference", ref_ticks), ("samesim", samesim_ticks)):
        mean, h = ci(v)
        print(f"{name:10} {mean:6.2f} +/- {h:.2f}  (sd {statistics.stdev(v):.2f}, range {min(v)}-{max(v)})")
    diff = statistics.mean(samesim_ticks) - statistics.mean(ref_ticks)
    print(f"samesim - reference: {diff:+.2f}  Welch p={welch.pvalue:.3f}  "
          f"TOST(+/-{m} tick) p={tost_p:.2g} -> {'EQUIVALENT' if tost_p < 0.05 else 'not shown equivalent'}")
    out = Path(__file__).resolve().parent / "gossip_vs_reference_results.json"
    out.write_text(json.dumps({"reference": ref_ticks, "samesim": samesim_ticks, "diff": diff,
                               "welch_p": welch.pvalue, "tost_p": tost_p, "margin_ticks": m}, indent=2))
    print(f"Wrote {out}")
