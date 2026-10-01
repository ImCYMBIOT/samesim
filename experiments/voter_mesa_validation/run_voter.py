"""
Voter model: SameSim vs. Mesa vs. the exact martingale result.

The synchronous voter model (every agent copies the previous-tick opinion
of a uniformly random neighbor) on a Barabasi-Albert graph, n = 50, m = 2.
Agents 0-4 -- the oldest, best-connected nodes -- start with opinion 1, the
rest with 0.

Exact result: the probability that opinion 1 takes over equals its
degree-weighted initial fraction M(0) = sum_i d_i x_i / sum_i d_i (a
martingale), here about 0.26 -- not the plain initial fraction 0.10. Each
seed gives a different graph, so M(0) is computed per run.

Both tools run on the IDENTICAL graph for each seed: SameSim's
BarabasiAlbertTopology with random.Random(seed), exactly as the experiment
runner builds it, handed to Mesa as a NetworkX graph.

    samesim  VoterBehavior + VoterMetric, synchronous activation
    mesa    the same rule in Mesa 3 (choose-then-apply each step)

Per run: M(0), the winning opinion, the consensus tick, and agent-updates
per second of run time (agents x ticks simulated / seconds).

    python run_voter.py            # 2,000 seeds per tool (~10 min)
    python run_voter.py --quick    # smoke run -> voter_results_quick.json

Output: voter_results.json next to this script.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
import time
from pathlib import Path

import mesa
import yaml

# Repo root, derived from this file so the script runs from any checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from samesim.app.experiment_runner import ExperimentRunner  # noqa: E402
from samesim.domain.ids import AgentId  # noqa: E402
from samesim.plugins.topologies.barabasi_albert import BarabasiAlbertTopology  # noqa: E402

HERE = Path(__file__).resolve().parent
SCRATCH = Path(os.environ.get("SAMESIM_EXPERIMENT_WORK", HERE / "_work"))

N, M_EDGES, ONES, HORIZON = 50, 2, 5, 400


def graph_for(seed: int) -> dict[int, list[int]]:
    """The graph SameSim's runner builds for this seed (topology is the first
    consumer of random.Random(seed))."""
    g = BarabasiAlbertTopology().generate([AgentId(i) for i in range(N)], {"m": M_EDGES},
                                          random.Random(seed))
    return {int(a): sorted(int(b) for b in g.neighbors(a)) for a in sorted(g.agent_ids)}


def predicted(adj: dict[int, list[int]]) -> float:
    total = sum(len(v) for v in adj.values())
    return sum(len(adj[a]) for a in adj if a < ONES) / total


def run_samesim(seed: int) -> dict:
    name = f"voter_s{seed}"
    cfg = {
        "schema_version": "1.0",
        "experiment": {"name": name, "seed": seed},
        "simulation": {"num_agents": N, "max_virtual_time": HORIZON},
        "plugins": {
            "behavior": "samesim.plugins.behaviors.voter.VoterBehavior",
            "communication": "samesim.plugins.communication.gossip.GossipProtocol",
            "topology": "samesim.plugins.topologies.barabasi_albert.BarabasiAlbertTopology",
            "metrics": ["samesim.plugins.metrics.voter_metrics.VoterMetric"],
            "persistence": ["samesim.plugins.persistence.csv_exporter.CsvExporter"],
        },
        "plugin_configs": {"VoterBehavior": {"initial_ones": ONES},
                           "BarabasiAlbertTopology": {"m": M_EDGES}},
    }
    (SCRATCH / "configs").mkdir(parents=True, exist_ok=True)
    path = SCRATCH / "configs" / f"{name}.yaml"
    path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    out = SCRATCH / "results" / name
    ExperimentRunner().run(path, output_dir=out)
    wall = json.loads((out / "summary.json").read_text())["wall_clock_runtime_seconds"]
    with open(out / f"{name}_voter.csv", newline="") as f:
        rows = list(csv.DictReader(l for l in f if not l.startswith("#")))
    t = next((float(r["virtual_time"]) for r in rows if float(r["value"]) in (0.0, 1.0)), None)
    final = float(rows[-1]["value"])
    return {"m0": float(rows[0]["weighted"]), "winner": int(final) if final in (0.0, 1.0) else None,
            "consensus_tick": t, "updates_per_s": N * (len(rows) - 1) / wall}



def _mesa_seed(seed):
    """Mesa >= 3.1 takes rng=; 3.0 only seed=. Both seed model.random the same way."""
    import inspect
    import mesa
    return {"rng": seed} if "rng" in inspect.signature(mesa.Model.__init__).parameters else {"seed": seed}


class VoterAgent(mesa.Agent):
    def __init__(self, model, node: int, opinion: int):
        super().__init__(model)
        self.node, self.opinion, self.next_opinion = node, opinion, opinion

    def choose(self):
        neighbor = self.model.random.choice(self.model.adj[self.node])
        self.next_opinion = self.model.by_node[neighbor].opinion

    def apply(self):
        self.opinion = self.next_opinion


class VoterModel(mesa.Model):
    def __init__(self, adj: dict[int, list[int]], seed: int):
        super().__init__(**_mesa_seed(seed))
        self.adj = adj
        self.by_node = {n: VoterAgent(self, n, 1 if n < ONES else 0) for n in sorted(adj)}

    def step(self):
        self.agents.do("choose")
        self.agents.do("apply")


def run_mesa(seed: int) -> dict:
    adj = graph_for(seed)
    model = VoterModel(adj, seed)
    t0 = time.perf_counter()
    tick = None
    for t in range(1, HORIZON + 1):
        model.step()
        ones = sum(a.opinion for a in model.by_node.values())
        if ones in (0, N):
            tick = t
            break
    wall = time.perf_counter() - t0
    steps = tick if tick is not None else HORIZON
    return {"m0": predicted(adj), "winner": (1 if ones == N else 0) if tick is not None else None,
            "consensus_tick": tick, "updates_per_s": N * steps / wall}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    seeds = range(1, 11) if args.quick else range(1, 2001)
    out_json = HERE / ("voter_results_quick.json" if args.quick else "voter_results.json")
    results = []
    for seed in seeds:
        for tool, fn in (("samesim", run_samesim), ("mesa", run_mesa)):
            results.append({"tool": tool, "seed": seed, **fn(seed)})
        if seed % 100 == 0:
            print(f"{seed} seeds done", flush=True)
    out_json.write_text(json.dumps(results, indent=2))
    print(f"Wrote {out_json}")


if __name__ == "__main__":
    main()
