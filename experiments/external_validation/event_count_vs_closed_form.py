"""
External validation 5/5: message volume vs. a closed-form combinatorial
expectation.

Not a comparison against another tool -- a check against exact arithmetic.
For a topology where every agent's degree >= fan_out, GossipBehavior sends
exactly fan_out messages per agent per tick (k = min(fan_out, degree) =
fan_out). With the engine's fixed dispatch order and the termination-
boundary fix (both ticks AND their message batches at t=max_virtual_time
now fully drain), total delivered messages over T ticks (t=0..T-1 send,
delivered at t=1..T) must equal exactly:

    n_agents * fan_out * T

This is the check that originally surfaced the engine termination bug
(experiments/gossip_topology_validation and the scaling benchmark never
would have caught it -- they only look at aggregate trends, not exact
counts). Now that both known engine/behavior bugs are fixed, this should
hold exactly, every time, for every n and T.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from samesim_harness import networkx_to_topology_graph, run_samesim  # noqa: E402

# Repo root, derived from this file so the script runs from any checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import networkx as nx  # noqa: E402

from samesim.domain.ids import AgentId  # noqa: E402
from samesim.plugins.behaviors.gossip_behavior import GossipBehavior  # noqa: E402
from samesim.plugins.communication.gossip import GossipProtocol  # noqa: E402
from samesim.plugins.metrics.message_count import MessageCountMetric  # noqa: E402

FAN_OUT = 2


def check_one(n: int, ticks: int, seed: int, avg_degree: float = 8.0) -> tuple[bool, int, int]:
    p = min(1.0, avg_degree / max(1, n - 1))
    g_nx = nx.erdos_renyi_graph(n, p, seed=seed)
    # Guarantee every agent's degree >= fan_out so k=fan_out always (isolate
    # the closed form from the min(fan_out, degree) edge case).
    while min(dict(g_nx.degree()).values()) < FAN_OUT:
        g_nx = nx.erdos_renyi_graph(n, p, seed=seed + 1000)
        seed += 1000

    agent_ids = [AgentId(i) for i in range(n)]
    graph = networkx_to_topology_graph(g_nx, agent_ids)

    series = run_samesim(
        graph=graph,
        behavior=GossipBehavior(),
        behavior_config={"fan_out": FAN_OUT},
        comm_protocol=GossipProtocol(),
        comm_config={},
        metric_collectors=[MessageCountMetric()],
        seed=seed,
        max_virtual_time=ticks,
        name=f"closed_form_n{n}_t{ticks}",
    )
    final_count = int(series[0].records[-1].value)
    expected = n * FAN_OUT * ticks
    return final_count == expected, final_count, expected


if __name__ == "__main__":
    cases = [(20, 5), (50, 10), (100, 20), (500, 15), (1000, 30)]
    all_ok = True
    for n, ticks in cases:
        ok, actual, expected = check_one(n, ticks, seed=42)
        all_ok &= ok
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] n={n:>5} ticks={ticks:>3}  actual={actual:>8}  expected={expected:>8}")

    print()
    print("ALL PASS" if all_ok else "SOME FAILED")
