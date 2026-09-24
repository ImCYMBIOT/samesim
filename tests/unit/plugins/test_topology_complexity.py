"""
Contract test: no topology generator may scale quadratically in n.

The second structural guard (alongside test_addressing_contract.py), and
for the same reason: the O(n^2) generation bug was found and fixed in
ErdosRenyiTopology, then later found again, untouched, in
WattsStrogatzTopology -- because the benchmark that caught the first one
only happened to exercise Ring and Erdos-Renyi. Fixing the instance the
benchmark happened to hit is not the same as fixing the class.

Like the addressing matrix, this DISCOVERS generators by walking the
plugins package, so a newly added topology is covered automatically.

Why a timing test: the failure mode is purely asymptotic (a plugin that
enumerates all n candidates inside a per-node loop), and it produces
correct graphs -- only slowly. There is nothing to assert about the output
itself.

How it measures, and why -- this test has been wrong twice:

  - It fits the growth EXPONENT by least squares over four sizes (n = 1k,
    2k, 4k, 8k), rather than trusting a single ratio between two sizes.
  - It disables the cyclic garbage collector while timing, as timeit
    does. GC work grows with the number of live objects, which makes
    linear code measure as mildly superlinear and noisy.
  - The bar is exponent 1.7. Measured with this method, every correct
    generator lands at 0.99-1.45 across repeated trials, and the pre-fix
    quadratic Watts-Strogatz lands near 2.

History: first it doubled n with a 3.0x bar (linear ~2x, quadratic ~4x);
a genuinely linear generator hit 3.06x from timer noise. Then it
quadrupled n with an 8x bar; correct generators reached 7.3x, because
"linear means 4x" ignores GC and memory effects. A guard that flakes gets
ignored, which is worse than having none.
"""
from __future__ import annotations

import gc
import importlib
import inspect
import math
import pkgutil
import random
import time

import pytest

import simul8.plugins.topologies as topologies_pkg
from simul8.domain.ids import AgentId
from simul8.ports.topology_generator import TopologyGeneratorPort

# Per-generator config chosen to hold average degree roughly constant, so
# the measurement reflects generation cost and not a denser graph.
CONFIGS: dict[str, dict] = {
    "ErdosRenyiTopology": {"__density__": 8.0},  # edge_probability derived from n
    "WattsStrogatzTopology": {"k": 8, "rewire_probability": 0.15},
    "BarabasiAlbertTopology": {"m": 4},
    "GridTopology": {"wrap": True},
    "RingTopology": {},
}

SIZES = (1_000, 2_000, 4_000, 8_000)
REPEATS = 5
MAX_EXPONENT = 1.7  # correct generators measure 0.99-1.45; quadratic ~2.0


def _discover() -> list[type]:
    found: list[type] = []
    for _finder, name, _ispkg in pkgutil.iter_modules(topologies_pkg.__path__):
        module = importlib.import_module(f"{topologies_pkg.__name__}.{name}")
        for _attr, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, TopologyGeneratorPort)
                and obj is not TopologyGeneratorPort
                and not inspect.isabstract(obj)
                and obj.__module__ == module.__name__
            ):
                found.append(obj)
    return sorted(set(found), key=lambda c: c.__name__)


GENERATORS = _discover()


def _config_for(generator_cls: type, n: int) -> dict:
    config = dict(CONFIGS.get(generator_cls.__name__, {}))
    density = config.pop("__density__", None)
    if density is not None:
        config["edge_probability"] = density / (n - 1)
    return config


def _best_time(generator_cls: type, n: int) -> float:
    agent_ids = [AgentId(i) for i in range(n)]
    config = _config_for(generator_cls, n)
    best = float("inf")
    gc.collect()
    gc.disable()
    try:
        for _ in range(REPEATS):
            generator = generator_cls()
            start = time.perf_counter()
            generator.generate(agent_ids, config, random.Random(1))
            best = min(best, time.perf_counter() - start)
    finally:
        gc.enable()
    return best


def _fitted_exponent(times: list[float]) -> float:
    xs = [math.log(n) for n in SIZES]
    ys = [math.log(t) for t in times]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)


def test_discovery_found_the_generators():
    """Guard the guard -- a vacuous matrix would pass silently."""
    assert len(GENERATORS) >= 5, f"Expected to discover generators, got {GENERATORS}"


@pytest.mark.parametrize("generator_cls", GENERATORS, ids=lambda c: c.__name__)
def test_generator_does_not_scale_quadratically(generator_cls):
    times = [_best_time(generator_cls, n) for n in SIZES]

    # Generators fast enough to sit in timer noise can't be measured
    # meaningfully, and are by definition not the problem this guards.
    if times[-1] < 0.005:
        pytest.skip(f"{generator_cls.__name__} too fast at n={SIZES[-1]} to measure reliably")

    exponent = _fitted_exponent(times)
    timings = ", ".join(f"n={n}: {t * 1000:.1f}ms" for n, t in zip(SIZES, times))
    assert exponent < MAX_EXPONENT, (
        f"{generator_cls.__name__} generation time grows as n^{exponent:.2f} "
        f"({timings}). Linear generators measure ~1.0-1.45 here and quadratic "
        f"~2.0, so this looks quadratic -- typically an O(n) scan (e.g. building "
        f"a candidate list over all agent_ids) nested inside a per-node loop. "
        f"Prefer rejection sampling or direct edge sampling."
    )
