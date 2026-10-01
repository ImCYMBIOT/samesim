"""
Naive reference implementation of push-gossip averaging, for measuring what
SameSim's clean architecture (event queue, ports, dataclass events, metrics
pipeline) costs in raw speed versus the simplest possible Python loop doing
equivalent work.

Uses Ring topology deliberately, NOT Erdos-Renyi: ErdosRenyiTopology.generate()
enumerates all n*(n-1)/2 possible pairs (O(n^2)) regardless of density, which
would dominate both timings at scale and confound the comparison this script
is actually trying to make (event-loop overhead, not topology-generation cost
-- that finding is reported separately in run_scaling.py's write-up).
RingTopology.generate() is O(n), so it isolates the loop/engine overhead.

Fairness notes (so the comparison means something):
  - Uses the SAME per-agent RNG scheme ("<seed>/agent/<id>") as
    RandomnessManager, and the SAME topology (built via SameSim's own
    RingTopology plugin) -- the only thing being measured is the
    tick/message loop, not a different graph or different randomness.
  - Does the same amount of real work per tick: each agent still calls
    rng.sample() to pick fan_out targets and still "sends" its value to
    them (appended to a plain list, standing in for a Message object) --
    it just skips dataclasses, the event queue, ports, and the metrics
    pipeline entirely.
  - Same 1-tick delivery latency (an agent averages with values that
    arrived from the *previous* tick's sends, not the current one),
    matching SameSim's MessageDeliveredEvent semantics.
"""
from __future__ import annotations

import os
import random
import sys
import time
from pathlib import Path

# Repo root, derived from this file so the script runs from any checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from samesim.domain.ids import AgentId  # noqa: E402
from samesim.plugins.topologies.ring import RingTopology  # noqa: E402

FAN_OUT = 2


def run_naive_gossip(n: int, ticks: int, seed: int) -> dict:
    t0 = time.perf_counter()

    agent_ids = [AgentId(i) for i in range(n)]
    global_rng = random.Random(seed)

    topology = RingTopology().generate(agent_ids, {}, global_rng)

    agent_rngs = [random.Random(f"{seed}/agent/{i}") for i in range(n)]
    values = [agent_rngs[i].uniform(0.0, 1.0) for i in range(n)]

    inbox: list[list[float]] = [[] for _ in range(n)]
    for _tick in range(ticks):
        next_inbox: list[list[float]] = [[] for _ in range(n)]
        for i in range(n):
            rng = agent_rngs[i]
            if inbox[i]:
                values[i] = (values[i] + sum(inbox[i])) / (1 + len(inbox[i]))

            neighbors = list(topology.neighbors(agent_ids[i]))
            if neighbors:
                k = min(FAN_OUT, len(neighbors))
                targets = rng.sample(sorted(neighbors), k)
                for t in targets:
                    next_inbox[int(t)].append(values[i])
        inbox = next_inbox

    wall = time.perf_counter() - t0
    return {"n": n, "ticks": ticks, "seed": seed, "wall_seconds": wall}


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("--ns", type=str, default="100,1000,10000")
    parser.add_argument("--ticks", type=int, default=50)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()

    ns = [int(x) for x in args.ns.split(",")]
    results = []
    for n in ns:
        print(f"naive n={n} ...", flush=True)
        r = run_naive_gossip(n, args.ticks, args.seed)
        results.append(r)
        print(f"    -> wall={r['wall_seconds']:.3f}s", flush=True)

    out = Path(__file__).resolve().parent / "naive_results.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {out}")
