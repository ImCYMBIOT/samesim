"""
Contract test: churn invariants hold for every behavior and every protocol.

For every discovered behavior (in each activation mode it declares) x every
discovered protocol, under heavy random failure and recovery:

    - a failed agent never runs (the engine emits a state change for every
      behavior call, so this is observable for ANY behavior, uninstrumented)
    - no message is delivered to a failed agent
    - every message reported lost to a failed recipient really was sent to
      a failed agent

Same discovery pattern as the other contract tests, so new behaviors and
protocols are covered without anyone registering them.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil

import pytest
import yaml

import simul8.plugins.behaviors as behaviors_pkg
import simul8.plugins.communication as protocols_pkg
from simul8.app.experiment_runner import ExperimentRunner
from simul8.ports.behavior import BehaviorPort
from simul8.ports.communication import CommunicationProtocolPort
from tests.integration.event_probes import EventLogMetric


def _discover(package, port):
    found = set()
    for _f, name, _p in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{package.__name__}.{name}")
        for _a, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, port) and obj is not port and not inspect.isabstract(obj) \
                    and obj.__module__ == module.__name__:
                found.add(obj)
    return sorted(found, key=lambda c: c.__name__)


BEHAVIORS = _discover(behaviors_pkg, BehaviorPort)
PROTOCOLS = _discover(protocols_pkg, CommunicationProtocolPort)
CASES = [(b, mode, p) for b in BEHAVIORS for mode in sorted(b.activation_modes) for p in PROTOCOLS]

BEHAVIOR_CONFIGS = {
    "SirEpidemicBehavior": {"transmission_rate": 0.4, "initial_infected": 4},
    "RaftElectionBehavior": {"election_timeout_min": 1.0, "election_timeout_max": 2.0,
                             "heartbeat_interval": 0.3},
}
TOTALS = {"fail": 0, "recover": 0, "lost": 0, "ran_after_recover": 0}


def test_discovery_found_the_plugins():
    assert len(BEHAVIORS) >= 5 and len(PROTOCOLS) >= 4


@pytest.mark.parametrize("behavior,mode,protocol", CASES,
                         ids=[f"{b.__name__}|{m}|{p.__name__}" for b, m, p in CASES])
def test_churn_invariants(behavior, mode, protocol, tmp_path):
    EventLogMetric.log = []
    cfg = {
        "schema_version": "1.0",
        "experiment": {"name": "cc", "seed": 5},
        "simulation": {"num_agents": 24, "max_virtual_time": 20.0,
                       "tick_interval": 0.5, "activation": mode},
        "plugins": {
            "behavior": f"{behavior.__module__}.{behavior.__name__}",
            "communication": f"{protocol.__module__}.{protocol.__name__}",
            "topology": "simul8.plugins.topologies.random_graph.ErdosRenyiTopology",
            "dynamics": "simul8.plugins.dynamics.random_churn.RandomChurn",
            "metrics": ["tests.integration.event_probes.EventLogMetric"],
            "persistence": [],
        },
        "plugin_configs": {
            behavior.__name__: BEHAVIOR_CONFIGS.get(behavior.__name__, {}),
            "ErdosRenyiTopology": {"edge_probability": 0.4},
            "RandomChurn": {"failure_rate": 0.05, "recovery_rate": 0.4},
            "LatencyProtocol": {"distribution": "exponential", "mean": 0.7},
        },
    }
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg))
    ExperimentRunner().run(path, output_dir=tmp_path / "out")

    failed, recovered_once = set(), set()
    for entry in EventLogMetric.log:
        kind, t = entry[0], entry[1]
        if kind == "change":
            _, _, fail, recover, _join = entry
            failed |= set(fail)
            failed -= set(recover)
            recovered_once |= set(recover)
            TOTALS["fail"] += len(fail)
            TOTALS["recover"] += len(recover)
        elif kind == "ran":
            assert entry[2] not in failed, f"agent {entry[2]} ran at t={t} while failed"
            TOTALS["ran_after_recover"] += entry[2] in recovered_once
        elif kind == "delivered":
            assert entry[2] not in failed, f"message delivered to failed agent {entry[2]} at t={t}"
        elif kind == "lost":
            TOTALS["lost"] += 1
            if entry[3] == "recipient_failed":
                assert entry[2] in failed, f"message 'lost' at t={t} to running agent {entry[2]}"


def test_zz_the_sweep_was_not_vacuous():
    """Runs after the sweep (alphabetical within the module): churn actually
    happened, messages were actually lost, and recovered agents ran again."""
    if TOTALS["fail"] == 0:
        pytest.skip("run the whole module for this check")
    assert TOTALS["fail"] > 50 and TOTALS["recover"] > 50, TOTALS
    assert TOTALS["lost"] > 50 and TOTALS["ran_after_recover"] > 50, TOTALS
