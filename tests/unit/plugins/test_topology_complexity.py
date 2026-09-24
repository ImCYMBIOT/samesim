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
itself. Thresholds are deliberately loose: doubling n should roughly
double the work, and true quadratic growth quadruples it, so the bar is
set between those at 3.0x with the best of several runs to damp noise.
"""
from __future__ import annotations

import importlib
import inspect
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

SMALL_N = 2_000
LARGE_N = 4_000
REPEATS = 3
MAX_GROWTH_RATIO = 3.0  # linear ~2.0, quadratic ~4.0


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
    for _ in range(REPEATS):
        generator = generator_cls()
        start = time.perf_counter()
        generator.generate(agent_ids, config, random.Random(1))
        best = min(best, time.perf_counter() - start)
    return best


def test_discovery_found_the_generators():
    """Guard the guard -- a vacuous matrix would pass silently."""
    assert len(GENERATORS) >= 5, f"Expected to discover generators, got {GENERATORS}"


@pytest.mark.parametrize("generator_cls", GENERATORS, ids=lambda c: c.__name__)
def test_generator_does_not_scale_quadratically(generator_cls):
    small = _best_time(generator_cls, SMALL_N)
    large = _best_time(generator_cls, LARGE_N)

    # Generators fast enough to sit in timer noise can't be measured
    # meaningfully, and are by definition not the problem this guards.
    if large < 0.005:
        pytest.skip(f"{generator_cls.__name__} too fast at n={LARGE_N} to measure reliably")

    ratio = large / small
    assert ratio < MAX_GROWTH_RATIO, (
        f"{generator_cls.__name__} took {ratio:.2f}x longer when n doubled "
        f"({small * 1000:.1f}ms at n={SMALL_N} -> {large * 1000:.1f}ms at n={LARGE_N}). "
        f"Linear growth is ~2x and quadratic is ~4x, so this looks quadratic -- "
        f"typically an O(n) scan (e.g. building a candidate list over all "
        f"agent_ids) nested inside a per-node loop. Prefer rejection sampling "
        f"or direct edge sampling."
    )
