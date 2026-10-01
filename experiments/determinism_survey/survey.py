"""
Do same-seed runs give bit-identical results -- across runs, Python versions
and operating systems -- in SameSim and in other Python simulators?

Each scenario runs twice with a fixed seed in this interpreter, and its full
output (every recorded number, as repr) is hashed with SHA-256. Run the
script under different Python versions and operating systems and compare
the hashes: identical hash = bit-identical run.

Scenarios, each written the way the tool's documentation writes models:

    samesim/async_gossip   examples/async_gossip_ring.yaml: event activation,
                          Poisson clocks, exponential latency
    samesim/sir            examples/sir_random.yaml
    samesim/gossip         examples/gossip_1000_agents.yaml: float averaging
    simpy/mm1             M/M/1 queue with random.expovariate, the SimPy idiom;
                          records each customer's arrival, start and end time
    simpy/mm1_service     the same run, recording each drawn service time
    mesa/voter            synchronous voter model (integer state)
    mesa/gossip           push-gossip averaging, mean via sum() / len
    ndlib/sir             NDlib SIRModel on a NetworkX G(n, p) graph
    python/gossip         the same averaging in plain Python, no framework:
                          isolates what the interpreter itself changes
    libm/<function>       the platform C math library directly: math.log,
                          exp, pow, sin and random.expovariate, gauss,
                          lognormvariate, each over 200,000 inputs
    portable/<function>   samesim.domain.portable_math's log, exp,
                          expovariate, normalvariate, lognormvariate on the
                          same inputs

The Mesa and plain-Python gossip models average with the builtin sum(),
as idiomatic Python does. CPython 3.12 changed sum() of floats to a
compensated algorithm, so their last bits -- and, iterated, their
trajectories -- can differ between 3.11 and 3.12. random.expovariate calls
the C library's log(), which differs between operating systems.

    python survey.py                 # prints JSON to stdout
    python survey.py --out FILE      # also writes it to FILE

Needs: simpy, mesa, ndlib, networkx (and SameSim, from this repository).
A scenario whose tool isn't installed is reported as "missing".
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import platform
import random
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

SEED = 7


def digest(values) -> str:
    h = hashlib.sha256()
    for v in values:
        h.update(repr(v).encode())
        h.update(b"\n")
    return h.hexdigest()


# ------------------------------------------------------------------ SameSim

def _samesim(example: str) -> str:
    import logging
    logging.disable(logging.INFO)
    from samesim.app.experiment_runner import ExperimentRunner
    with tempfile.TemporaryDirectory() as tmp:
        ExperimentRunner().run(REPO / "examples" / example, output_dir=tmp)
        files = sorted(p for p in Path(tmp).glob("*.csv"))
        return digest(p.name + "\n" + p.read_text() for p in files)


# ------------------------------------------------------------------- SimPy

def simpy_mm1() -> str:
    return _simpy_mm1()[0]


def simpy_mm1_service() -> str:
    return _simpy_mm1()[1]


def _simpy_mm1():
    """One M/M/1 run; returns hashes of (event times, drawn service times).

    The two differ in how they meet a last-bit difference in a draw: added
    to a clock near 20,000, a difference of ~1e-16 is far below the float
    spacing there (~4e-12) and usually rounds away; a service time recorded
    as drawn keeps it."""
    import simpy
    rng = random.Random(SEED)
    env = simpy.Environment()
    server = simpy.Resource(env, capacity=1)
    log, services = [], []

    def customer():
        arrival = env.now
        with server.request() as req:
            yield req
            start = env.now
            service = rng.expovariate(1.0)
            services.append(service)
            yield env.timeout(service)
        log.append((arrival, start, env.now))

    def source():
        while True:
            yield env.timeout(rng.expovariate(0.9))
            env.process(customer())

    env.process(source())
    env.run(until=20_000)
    return digest(log), digest(services)


# -------------------------------------------------------------------- Mesa


def _mesa_seed(seed):
    """Mesa >= 3.1 takes rng=; 3.0 only seed=. Both seed model.random the same way."""
    import inspect
    import mesa
    return {"rng": seed} if "rng" in inspect.signature(mesa.Model.__init__).parameters else {"seed": seed}

def _graph(n=60, p=0.1):
    import networkx as nx
    g = nx.gnp_random_graph(n, p, seed=SEED)
    return {u: sorted(g.neighbors(u)) for u in sorted(g)}


def mesa_voter() -> str:
    import mesa
    adj = _graph()

    class Voter(mesa.Agent):
        def __init__(self, model, node):
            super().__init__(model)
            self.node, self.opinion = node, model.random.randint(0, 1)
            self.next = self.opinion

        def choose(self):
            if self.model.adj[self.node]:
                self.next = self.model.by_node[self.model.random.choice(self.model.adj[self.node])].opinion

        def apply(self):
            self.opinion = self.next

    class Model(mesa.Model):
        def __init__(self):
            super().__init__(**_mesa_seed(SEED))
            self.adj = adj
            self.by_node = {n: Voter(self, n) for n in adj}

        def step(self):
            self.agents.do("choose")
            self.agents.do("apply")

    m = Model()
    trace = []
    for _ in range(200):
        m.step()
        trace.append(tuple(a.opinion for a in m.by_node.values()))
    return digest(trace)


def mesa_gossip() -> str:
    import mesa
    adj = _graph()

    class Node(mesa.Agent):
        def __init__(self, model, node):
            super().__init__(model)
            self.node, self.value, self.inbox = node, model.random.random(), []

        def push(self):
            nbrs = self.model.adj[self.node]
            for n in self.model.random.sample(nbrs, min(2, len(nbrs))):
                self.model.by_node[n].inbox.append(self.value)

        def average(self):
            if self.inbox:
                vals = [self.value] + self.inbox
                self.value = sum(vals) / len(vals)
                self.inbox = []

    class Model(mesa.Model):
        def __init__(self):
            super().__init__(**_mesa_seed(SEED))
            self.adj = adj
            self.by_node = {n: Node(self, n) for n in adj}

        def step(self):
            self.agents.do("push")
            self.agents.do("average")

    m = Model()
    trace = []
    for _ in range(100):
        m.step()
        trace.append(tuple(a.value for a in m.by_node.values()))
    return digest(trace)


# ------------------------------------------------------------------- NDlib

def ndlib_sir() -> str:
    import networkx as nx
    import ndlib.models.ModelConfig as mc
    import ndlib.models.epidemics as ep
    g = nx.erdos_renyi_graph(500, 0.02, seed=SEED)
    model = ep.SIRModel(g, seed=SEED)
    cfg = mc.Configuration()
    cfg.add_model_parameter("beta", 0.15)
    cfg.add_model_parameter("gamma", 0.1)
    cfg.add_model_initial_configuration("Infected", list(range(5)))
    model.set_initial_status(cfg)
    return digest(tuple(sorted(it["node_count"].items())) for it in model.iteration_bunch(100, node_status=False))


# ------------------------------------------------------------ plain Python

def python_gossip() -> str:
    adj = _graph()
    rng = random.Random(SEED)
    value = {n: rng.random() for n in adj}
    trace = []
    for _ in range(100):
        inbox = {n: [] for n in adj}
        for n in adj:
            for t in rng.sample(adj[n], min(2, len(adj[n]))):
                inbox[t].append(value[n])
        for n in adj:
            if inbox[n]:
                vals = [value[n]] + inbox[n]
                value[n] = sum(vals) / len(vals)
        trace.append(tuple(value.values()))
    return digest(trace)


LIBM_N = 200_000


def _inputs():
    rng = random.Random(SEED)
    return [rng.uniform(1e-6, 50.0) for _ in range(LIBM_N)]


BLOCK = 100  # libm scenarios also hash each block of 100 outputs


def _blocks(values) -> dict:
    """Whole-output hash, plus one short hash per block of BLOCK outputs, so
    comparing two platforms shows how many blocks -- roughly, how many
    values, when differences are rare -- disagree."""
    values = list(values)
    blocks = [digest(values[i:i + BLOCK])[:12] for i in range(0, len(values), BLOCK)]
    return {"hash": digest(values), "blocks": blocks}


def _libm(fn) -> dict:
    import math
    return _blocks(fn(math, x) for x in _inputs())


def _variates(draw) -> dict:
    rng = random.Random(SEED)
    return _blocks(draw(rng) for _ in range(LIBM_N))


def _portable(fn) -> str:
    from samesim.domain import portable_math
    return digest(fn(portable_math, x) for x in _inputs())


def _portable_variates(draw) -> str:
    from samesim.domain import portable_math
    rng = random.Random(SEED)
    return digest(draw(portable_math, rng) for _ in range(LIBM_N))


SCENARIOS = {
    "samesim/async_gossip": ("samesim", lambda: _samesim("async_gossip_ring.yaml")),
    "samesim/sir": ("samesim", lambda: _samesim("sir_random.yaml")),
    "samesim/gossip": ("samesim", lambda: _samesim("gossip_1000_agents.yaml")),
    "simpy/mm1": ("simpy", simpy_mm1),
    "simpy/mm1_service": ("simpy", simpy_mm1_service),
    "mesa/voter": ("mesa", mesa_voter),
    "mesa/gossip": ("mesa", mesa_gossip),
    "ndlib/sir": ("ndlib", ndlib_sir),
    "python/gossip": (None, python_gossip),
    "libm/log": (None, lambda: _libm(lambda m, x: m.log(x))),
    "libm/exp": (None, lambda: _libm(lambda m, x: m.exp(x / 2))),
    "libm/pow": (None, lambda: _libm(lambda m, x: m.pow(x, 1.37))),
    "libm/sin": (None, lambda: _libm(lambda m, x: m.sin(x))),
    "libm/expovariate": (None, lambda: _variates(lambda r: r.expovariate(0.9))),
    "libm/gauss": (None, lambda: _variates(lambda r: r.gauss(0.0, 1.0))),
    "libm/lognormvariate": (None, lambda: _variates(lambda r: r.lognormvariate(0.0, 1.0))),
    "portable/log": (None, lambda: _portable(lambda p, x: p.log(x))),
    "portable/exp": (None, lambda: _portable(lambda p, x: p.exp(x / 2))),
    "portable/expovariate": (None, lambda: _portable_variates(lambda p, r: p.expovariate(r, 0.9))),
    "portable/normalvariate": (None, lambda: _portable_variates(lambda p, r: p.normalvariate(r, 0.0, 1.0))),
    "portable/lognormvariate": (None, lambda: _portable_variates(lambda p, r: p.lognormvariate(r, 0.0, 1.0))),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    versions = {}
    for mod in ("simpy", "mesa", "ndlib", "networkx", "numpy"):
        try:
            versions[mod] = importlib.import_module(mod).__version__
        except Exception:
            versions[mod] = None
    results = {}
    for name, (needs, fn) in SCENARIOS.items():
        if needs and needs != "samesim" and versions.get(needs) is None:
            results[name] = {"status": "missing"}
            continue
        try:
            a, b = fn(), fn()
            if isinstance(a, dict):  # libm scenario: hash plus block hashes
                results[name] = {"status": "ok", "hash": a["hash"], "repeatable": a == b,
                                 "blocks": a["blocks"]}
            else:
                results[name] = {"status": "ok", "hash": a, "repeatable": a == b}
        except Exception as exc:  # report, don't hide
            results[name] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    report = {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "os": platform.system(),
        "machine": platform.machine(),
        "versions": versions,
        "scenarios": results,
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        args.out.write_text(text)


if __name__ == "__main__":
    main()
