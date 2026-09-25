"""
Golden traces: every simulation Simul8 can currently express must keep
producing exactly the same run.

Phase 0 of docs/design/event_model.md. The engine's time model is about to be
refactored (latency, asynchronous activation, churn), and every phase of that
work promises to leave existing behavior bit-identical. This file is what
makes that promise checkable instead of just stated.

What is pinned:

    MATRIX    Every behavior x protocol x topology, DISCOVERED by walking
              the plugin packages (plus an order-sensitive probe behavior,
              tests/regression/probes.py), at two tick intervals (1.0, and 0.5 to
              exercise the delivery-time path that once hardcoded +1.0).
              Each run is fingerprinted by TraceDigestMetric, which folds
              every delivered message and every state change -- so a change
              to a single delivery anywhere fails here. Per-tick digests
              are stored, so a failure names the first tick that diverged.

    EXAMPLES  Every config in examples/, with every CSV it writes hashed
              byte-for-byte -- covering the metric and exporter plugins
              the matrix does not exercise.

A new plugin fails here until it is recorded, on purpose: recording a
golden trace is an explicit, reviewable act.

    pytest tests/regression/test_golden_traces.py --update-golden

Re-record only for a change that is MEANT to alter simulation output, and
review the JSON diff like code. A refactor that needs --update-golden is,
by definition, not a pure refactor.

Cross-platform note: Python's float repr and random.Random are identical on
every platform, but math.log / math.exp may differ in the last ulp between C
libraries, and two generators (Erdos-Renyi, Watts-Strogatz) use math.log. If
CI on another OS disagrees with a hash recorded on Linux, that is a real
reproducibility finding about those generators, not flakiness in this test.
"""
from __future__ import annotations

import csv
import hashlib
import importlib
import inspect
import json
import pkgutil
from pathlib import Path

import pytest
import yaml

import simul8.plugins.behaviors as behaviors_pkg
import simul8.plugins.communication as protocols_pkg
import simul8.plugins.topologies as topologies_pkg
from simul8.app.experiment_runner import ExperimentRunner
from simul8.ports.behavior import BehaviorPort
from simul8.ports.communication import CommunicationProtocolPort
from simul8.ports.topology_generator import TopologyGeneratorPort
from tests.regression.probes import EventProbeBehavior, InboxProbeBehavior

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_PATH = Path(__file__).resolve().parent / "golden" / "traces.json"
DIGEST_METRIC = "simul8.plugins.metrics.trace_digest.TraceDigestMetric"
CSV_EXPORTER = "simul8.plugins.persistence.csv_exporter.CsvExporter"

N_AGENTS = 36          # a perfect square, so GridTopology is a full grid
MAX_TIME = 20.0
TICK_INTERVALS = (1.0, 0.5)
SEED = 20260924
TICK_PREFIX = 16       # hex chars stored per tick; the final digest is kept in full

# Only plugins whose defaults would make the run degenerate need an entry.
# A plugin absent from these tables runs on its own defaults.
BEHAVIOR_CONFIGS = {
    "SirEpidemicBehavior": {"transmission_rate": 0.3, "recovery_rate": 0.1, "initial_infected": 3},
    "GossipBehavior": {"fan_out": 2, "initial_value_range": [0.0, 1.0]},
    # Defaults (150-300) would never fire within MAX_TIME=20, pinning nothing
    # but the bootstrap. Scaled so candidacy, voting and term escalation
    # happen inside the window. No matrix topology is complete, so no cell
    # reaches a majority (19 of 36) -- leadership and heartbeats are pinned
    # by examples/raft_election.yaml instead.
    "RaftElectionBehavior": {"election_timeout_min": 3.0, "election_timeout_max": 6.0,
                             "heartbeat_interval": 1.0},
}
PROTOCOL_CONFIGS = {
    "LossyProtocol": {"loss_probability": 0.2},
    # Mean 1.5 time units: at dt=1.0 most delays round up to 1-3 ticks and a
    # tail reaches further; at dt=0.5 the same draws span more ticks. Both
    # exercise out-of-order arrival and the tick-rounding path.
    "LatencyProtocol": {"distribution": "exponential", "mean": 1.5, "loss_probability": 0.1},
}
TOPOLOGY_CONFIGS = {
    "ErdosRenyiTopology": {"edge_probability": 0.15},
    "WattsStrogatzTopology": {"k": 4, "rewire_probability": 0.2},
    "BarabasiAlbertTopology": {"m": 2},
    "GridTopology": {"wrap": True},
}


def _discover(package, port) -> list[type]:
    found = set()
    for _f, name, _p in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{package.__name__}.{name}")
        for _a, obj in inspect.getmembers(module, inspect.isclass):
            if (issubclass(obj, port) and obj is not port
                    and not inspect.isabstract(obj) and obj.__module__ == module.__name__):
                found.add(obj)
    return sorted(found, key=lambda c: c.__name__)


def _path(cls: type) -> str:
    return f"{cls.__module__}.{cls.__name__}"


# The probe rides along with the discovered behaviors so the guard's
# sensitivity does not depend on which plugins happen to exist (see probes.py).
BEHAVIORS = _discover(behaviors_pkg, BehaviorPort) + [InboxProbeBehavior, EventProbeBehavior]
PROTOCOLS = _discover(protocols_pkg, CommunicationProtocolPort)
TOPOLOGIES = _discover(topologies_pkg, TopologyGeneratorPort)
EXAMPLES = sorted((REPO_ROOT / "examples").glob("*.yaml"))

# Every activation mode each behavior declares is its own set of cells.
MATRIX = [
    (b, p, t, dt, mode)
    for b in BEHAVIORS
    for mode in sorted(getattr(b, "activation_modes", {"synchronous"}))
    for p in PROTOCOLS for t in TOPOLOGIES for dt in TICK_INTERVALS
]


def _matrix_key(b, p, t, dt, mode="synchronous") -> str:
    # Synchronous keys carry no suffix, so they stay identical to the keys
    # recorded before activation modes existed.
    suffix = "" if mode == "synchronous" else f"|{mode}"
    return f"{b.__name__}|{p.__name__}|{t.__name__}|dt={dt}{suffix}"


def _example_key(path: Path) -> str:
    return f"example:{path.stem}"


EXPECTED_KEYS = {"matrix": {_matrix_key(*c) for c in MATRIX},
                 "examples": {_example_key(e) for e in EXAMPLES}}


# ---------------------------------------------------------------------------
# Golden store
# ---------------------------------------------------------------------------

class _Golden:
    def __init__(self, update: bool) -> None:
        self.update = update
        self.data = (json.loads(GOLDEN_PATH.read_text())
                     if GOLDEN_PATH.exists() else {"matrix": {}, "examples": {}})
        self.dirty = False

    def check(self, section: str, key: str, actual: dict) -> None:
        if self.update:
            if self.data[section].get(key) != actual:
                self.data[section][key] = actual
                self.dirty = True
            return

        expected = self.data[section].get(key)
        if expected is None:
            pytest.fail(
                f"No golden trace recorded for {key}. If this is a new plugin or "
                f"example, record it with --update-golden and commit the diff."
            )
        if expected == actual:
            return

        lines = [f"{key} no longer produces the run it used to."]
        for i, (e, a) in enumerate(zip(expected["ticks"], actual["ticks"])):
            if e != a:
                lines.append(f"  First divergence at virtual time {e.split(':')[0]} (tick #{i}).")
                break
        else:
            if len(expected["ticks"]) != len(actual["ticks"]):
                lines.append(
                    f"  Every shared tick matches, but the run now has "
                    f"{len(actual['ticks'])} tick records vs. {len(expected['ticks'])}."
                )
        for name in sorted(set(expected.get("files", {})) | set(actual.get("files", {}))):
            if expected.get("files", {}).get(name) != actual.get("files", {}).get(name):
                lines.append(f"  Output file differs: {name}")
        lines.append(
            "  If this change is MEANT to alter simulation output, re-record with "
            "--update-golden and review the JSON diff. Otherwise it is a regression."
        )
        pytest.fail("\n".join(lines))

    def prune(self) -> list[str]:
        removed = []
        for section, keys in EXPECTED_KEYS.items():
            for key in sorted(set(self.data[section]) - keys):
                removed.append(key)
                del self.data[section][key]
        if removed:
            self.dirty = True
        return removed

    def save(self) -> None:
        if self.dirty:
            GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            GOLDEN_PATH.write_text(json.dumps(self.data, indent=1, sort_keys=True) + "\n")


@pytest.fixture(scope="module")
def golden(request):
    store = _Golden(update=request.config.getoption("--update-golden"))
    yield store
    store.save()


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

def _run(cfg: dict, tmp_path: Path) -> Path:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    out = tmp_path / "out"
    ExperimentRunner().run(cfg_path, output_dir=out)
    return out


def _digest_record(out: Path, name: str) -> dict:
    with open(out / f"{name}_trace_digest.csv", newline="") as f:
        rows = list(csv.DictReader(line for line in f if not line.startswith("#")))
    assert rows, "TraceDigestMetric recorded nothing -- the run did not tick"
    return {
        "ticks": [f"{float(r['virtual_time'])!r}:{r['digest'][:TICK_PREFIX]}" for r in rows],
        "final": rows[-1]["digest"],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_discovery_found_the_plugins():
    """Guard the guard -- an empty matrix would pass silently."""
    assert len(BEHAVIORS) >= 5 and len(PROTOCOLS) >= 3 and len(TOPOLOGIES) >= 5, (
        BEHAVIORS, PROTOCOLS, TOPOLOGIES)
    assert len(EXAMPLES) >= 5, EXAMPLES


@pytest.mark.parametrize("behavior,protocol,topology,dt,mode", MATRIX,
                         ids=[_matrix_key(*c) for c in MATRIX])
def test_matrix_trace_is_unchanged(behavior, protocol, topology, dt, mode, tmp_path, golden):
    name = "golden"
    cfg = {
        "schema_version": "1.0",
        "experiment": {"name": name, "seed": SEED},
        "simulation": {"num_agents": N_AGENTS, "max_virtual_time": MAX_TIME,
                       "tick_interval": dt, "activation": mode},
        "plugins": {
            "behavior": _path(behavior),
            "communication": _path(protocol),
            "topology": _path(topology),
            "metrics": [DIGEST_METRIC],
            "persistence": [CSV_EXPORTER],
        },
        "plugin_configs": {
            behavior.__name__: BEHAVIOR_CONFIGS.get(behavior.__name__, {}),
            protocol.__name__: PROTOCOL_CONFIGS.get(protocol.__name__, {}),
            topology.__name__: TOPOLOGY_CONFIGS.get(topology.__name__, {}),
        },
    }
    out = _run(cfg, tmp_path)
    golden.check("matrix", _matrix_key(behavior, protocol, topology, dt, mode),
                 _digest_record(out, name))


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda p: p.stem)
def test_example_outputs_are_unchanged(example, tmp_path, golden):
    cfg = yaml.safe_load(example.read_text())
    cfg["plugins"]["metrics"] = list(cfg["plugins"].get("metrics", [])) + [DIGEST_METRIC]
    out = _run(cfg, tmp_path)
    name = cfg["experiment"]["name"]

    record = _digest_record(out, name)
    record["files"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(out.glob("*.csv"))
    }
    golden.check("examples", _example_key(example), record)


def test_no_orphaned_golden_entries(golden):
    """A renamed or removed plugin must not leave a stale entry behind."""
    if golden.update:
        golden.prune()
        return
    orphans = {s: sorted(set(golden.data[s]) - keys) for s, keys in EXPECTED_KEYS.items()}
    orphans = {s: k for s, k in orphans.items() if k}
    assert not orphans, (
        f"Golden entries with no matching plugin or example: {orphans}. "
        f"Prune them with --update-golden."
    )
