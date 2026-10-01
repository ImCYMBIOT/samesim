"""
Push-pull gossip averaging: SameSim vs. PeerSim vs. Jelasity's closed form.

PeerSim (Montresor & Jelasity) is the standard P2P simulator; its
cycle-driven aggregation example is push-pull averaging: each cycle, every
node, in a random order, averages with a random neighbor. Jelasity,
Montresor and Babaoglu (ACM TOCS 2005) show that on a complete graph the
variance shrinks by a factor of 1/(2*sqrt(e)) ~ 0.3033 per cycle.

    samesim  AsyncGossipBehavior, schedule: cycle (one exchange per agent per
             unit time at a uniformly random point: a random order each
             cycle), event activation, message latency 1e-7 (far below the
             1/n gap between agents), ConvergenceMetric
    peersim  PeerSim 1.0.5's example.aggregation.AverageFunction with
             Shuffle and AverageObserver, unmodified

Both run on the IDENTICAL graph for each seed: SameSim's generator builds
it, and PeerSim loads it with WireFromFile. Per run, the variance at the
start of every cycle; per-cycle reduction factors follow.

Parts:
    theory   complete graph, n = 1,000, 15 cycles, 50 seeds per tool
    sparse   Erdos-Renyi, average degree 20, n = 1,000, 15 cycles, 50 seeds
    speed    Erdos-Renyi, average degree 20, n = 10^3, 10^4, 10^5,
             20 cycles, 3 repeats per tool; wall time

PeerSim is downloaded on first use (SourceForge) and checked against its
SHA-256. Java comes from $JAVA, or `java` on PATH; e.g. with a conda env:

    JAVA=$(conda run -n peersim which java) python run_peersim.py
    python run_peersim.py --part theory --part sparse     # skip the slow part

Output: peersim_results.json next to this script.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

# Repo root, derived from this file so the script runs from any checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import samesim  # noqa: E402
from samesim.domain.ids import AgentId  # noqa: E402
from samesim.plugins.topologies.random_graph import ErdosRenyiTopology  # noqa: E402

HERE = Path(__file__).resolve().parent
SCRATCH = Path(os.environ.get("SAMESIM_EXPERIMENT_WORK", HERE / "_work"))
PEERSIM_URL = "https://sourceforge.net/projects/peersim/files/peersim-1.0.5.zip/download"
PEERSIM_SHA256 = "8d98f0a39c74a88b4c8aba6a0fae4bb8eb19af09a0837686619adc4d365dff61"
LATENCY = 1e-7


def peersim_classpath() -> str:
    root = SCRATCH / "peersim-1.0.5"
    if not (root / "peersim-1.0.5.jar").exists():
        SCRATCH.mkdir(parents=True, exist_ok=True)
        zpath = SCRATCH / "peersim-1.0.5.zip"
        if not zpath.exists():
            print("Downloading PeerSim 1.0.5 ...", flush=True)
            urllib.request.urlretrieve(PEERSIM_URL, zpath)
        digest = hashlib.sha256(zpath.read_bytes()).hexdigest()
        if digest != PEERSIM_SHA256:
            raise RuntimeError(f"PeerSim zip SHA-256 is {digest}, expected {PEERSIM_SHA256}")
        with zipfile.ZipFile(zpath) as z:
            z.extractall(SCRATCH)
    return os.pathsep.join(str(root / j) for j in ("peersim-1.0.5.jar", "jep-2.3.0.jar", "djep-1.0.0.jar"))


def java() -> str:
    exe = os.environ.get("JAVA") or shutil.which("java")
    if not exe:
        raise RuntimeError("No Java found: set $JAVA or put java on PATH")
    return exe


def graph(n: int, p: float, seed: int):
    """The graph SameSim's runner builds for this seed (the topology is the
    first consumer of random.Random(seed))."""
    return ErdosRenyiTopology().generate([AgentId(i) for i in range(n)], {"edge_probability": p},
                                         random.Random(seed))


def run_samesim(n: int, p: float, seed: int, cycles: int) -> dict:
    cfg = {
        "schema_version": "1.0",
        "experiment": {"name": "pushpull", "seed": seed},
        "simulation": {"num_agents": n, "max_virtual_time": cycles, "tick_interval": 1,
                       "activation": "event"},
        "plugins": {
            "behavior": "samesim.plugins.behaviors.async_gossip.AsyncGossipBehavior",
            "communication": "samesim.plugins.communication.latency.LatencyProtocol",
            "topology": "samesim.plugins.topologies.random_graph.ErdosRenyiTopology",
            "metrics": ["samesim.plugins.metrics.convergence.ConvergenceMetric"],
        },
        "plugin_configs": {
            "AsyncGossipBehavior": {"schedule": "cycle"},
            "LatencyProtocol": {"distribution": "constant", "delay": LATENCY},
            "ErdosRenyiTopology": {"edge_probability": p},
        },
    }
    t0 = time.perf_counter()
    r = samesim.run(cfg)
    total = time.perf_counter() - t0
    var = [x.value for x in r.series["convergence_variance"].records]
    return {"variance": var, "wall_total": total, "wall_engine": r.wall_clock_seconds}


def run_peersim(n: int, p: float, seed: int, cycles: int, cp: str) -> dict:
    work = SCRATCH / "peersim_runs"
    work.mkdir(parents=True, exist_ok=True)
    gfile = work / f"graph_n{n}_p{p:g}_s{seed}.txt"
    if not gfile.exists():
        g = graph(n, p, seed)
        with open(gfile, "w") as f:
            for a in sorted(g.agent_ids):
                f.write(f"{int(a)} " + " ".join(str(int(b)) for b in sorted(g.neighbors(a))) + "\n")
    cfg = work / f"cfg_n{n}_p{p:g}_s{seed}.txt"
    cfg.write_text(f"""random.seed {seed}
simulation.cycles {cycles + 1}
control.shf Shuffle
network.size {n}
protocol.lnk IdleProtocol
protocol.avg example.aggregation.AverageFunction
protocol.avg.linkable lnk
init.wire WireFromFile
init.wire.protocol lnk
init.wire.file {gfile}
init.uni peersim.vector.UniformDistribution
init.uni.protocol avg
init.uni.max 1
init.uni.min 0
include.init wire uni
control.avgo example.aggregation.AverageObserver
control.avgo.protocol avg
""")
    t0 = time.perf_counter()
    out = subprocess.run([java(), "-Xmx3g", "-cp", cp, "peersim.Simulator", str(cfg)],
                         capture_output=True, text=True, check=True)
    total = time.perf_counter() - t0
    var = [float(line.split()[6]) for line in out.stdout.splitlines() if line.startswith("control.avgo:")]
    if len(var) != cycles + 1:
        raise RuntimeError(f"PeerSim reported {len(var)} cycles, expected {cycles + 1}:\n{out.stdout[-500:]}")
    return {"variance": var, "wall_total": total}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", action="append", choices=["theory", "sparse", "speed"])
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    parts = args.part or ["theory", "sparse", "speed"]
    out_json = HERE / ("peersim_results_quick.json" if args.quick else "peersim_results.json")
    results = json.loads(out_json.read_text()) if out_json.exists() else []
    done = {(r["part"], r["tool"], r["n"], r["seed"]) for r in results}
    cp = peersim_classpath()

    jobs = []
    seeds = range(1, 4) if args.quick else range(1, 51)
    if "theory" in parts:
        jobs += [("theory", 1000, 1.0, s, 15) for s in seeds]
    if "sparse" in parts:
        jobs += [("sparse", 1000, 20 / 999, s, 15) for s in seeds]
    if "speed" in parts:
        for n in ((1000,) if args.quick else (1000, 10_000, 100_000)):
            jobs += [("speed", n, 20 / (n - 1), s, 20) for s in (1, 2, 3)]

    for part, n, p, seed, cycles in jobs:
        for tool in ("samesim", "peersim"):
            if (part, tool, n, seed) in done:
                continue
            r = run_samesim(n, p, seed, cycles) if tool == "samesim" else run_peersim(n, p, seed, cycles, cp)
            results.append({"part": part, "tool": tool, "n": n, "p": p, "seed": seed, "cycles": cycles, **r})
            out_json.write_text(json.dumps(results, indent=1))
            print(f"{part:6} {tool:7} n={n:<6} seed={seed:<2} wall {r['wall_total']:.2f}s", flush=True)
    print(f"Wrote {out_json}")


if __name__ == "__main__":
    main()
