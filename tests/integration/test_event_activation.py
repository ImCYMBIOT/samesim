"""
Event activation (Phase 2): agents run on messages and timers, not ticks.

Everything here is observed from inside a behavior -- what the engine
actually called, when, and with which inbox -- rather than inferred from
event timestamps.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from simul8.app.config_loader import ConfigValidationError
from simul8.app.experiment_runner import ExperimentRunner
from tests.integration.event_probes import ScriptedBehavior

PROBES = "tests.integration.event_probes"
RING = "simul8.plugins.topologies.ring.RingTopology"


def _run(tmp_path: Path, script=None, *, n=4, max_time=10.0, dt=1.0, activation="event",
         behavior=f"{PROBES}.ScriptedBehavior", protocol=f"{PROBES}.PayloadDelayProtocol",
         metrics=(), persistence=()) -> list[dict]:
    ScriptedBehavior.log = []
    cfg = {
        "schema_version": "1.0",
        "experiment": {"name": "event", "seed": 3},
        "simulation": {"num_agents": n, "max_virtual_time": max_time,
                       "tick_interval": dt, "activation": activation},
        "plugins": {"behavior": behavior, "communication": protocol, "topology": RING,
                    "metrics": list(metrics), "persistence": list(persistence)},
        # Only the scripted probe takes a script; handing one to any other
        # behavior would be an unread option, which the runner rejects.
        "plugin_configs": ({"ScriptedBehavior": {"script": script or {}}}
                           if behavior.endswith(".ScriptedBehavior") else {}),
    }
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg))
    ExperimentRunner().run(path, output_dir=tmp_path / "out")
    return list(ScriptedBehavior.log)


def _calls(log, agent):
    return [e for e in log if e["agent"] == agent]


# --- activation -------------------------------------------------------------

def test_every_agent_gets_one_bootstrap_step_at_t0_in_id_order(tmp_path):
    log = _run(tmp_path)
    assert [(e["t"], e["agent"], e["trigger"]) for e in log] == [
        (0.0, 0, "boot"), (0.0, 1, "boot"), (0.0, 2, "boot"), (0.0, 3, "boot")]


def test_agents_do_not_run_on_ticks(tmp_path):
    """No messages, no timers: after bootstrap nothing ever calls an agent,
    however many ticks go by."""
    log = _run(tmp_path, max_time=50)
    assert len(log) == 4


def test_ticks_still_sample_metrics(tmp_path):
    _run(tmp_path, max_time=5,
         metrics=["simul8.plugins.metrics.trace_digest.TraceDigestMetric"],
         persistence=["simul8.plugins.persistence.csv_exporter.CsvExporter"])
    rows = [l for l in (tmp_path / "out" / "event_trace_digest.csv").read_text().splitlines()
            if l and not l.startswith("#")][1:]
    tick_times = [float(r.split(",")[0]) for r in rows][:-1]  # last row is the end marker
    assert tick_times == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]


# --- delivery ---------------------------------------------------------------

def test_delay_is_exact_not_rounded_to_ticks(tmp_path):
    log = _run(tmp_path, {0: {"boot": [{"send": 1, "delay": 0.37}]}})
    received = [e for e in _calls(log, 1) if e["trigger"] == "message"]
    assert [(e["t"], e["inbox"]) for e in received] == [(0.37, [(0, 1)])]


def test_default_delay_is_one_tick_interval(tmp_path):
    log = _run(tmp_path, {0: {"boot": [{"send": 1, "delay": None}]}}, dt=0.25)
    assert [e["t"] for e in _calls(log, 1) if e["trigger"] == "message"] == [0.25]


def test_messages_arriving_at_one_instant_form_one_batch_in_send_order(tmp_path):
    script = {
        0: {"boot": [{"send": 1, "delay": 2.0}, {"send": 1, "delay": 2.0}]},
        2: {"boot": [{"send": 1, "delay": 2.0}, {"send": 1, "delay": 3.0}]},
    }
    log = _run(tmp_path, script)
    # The FULL call list: one call per instant, never an extra call with an
    # empty inbox (which is what a wake-per-message engine would produce).
    assert [(e["t"], e["trigger"], e["inbox"]) for e in _calls(log, 1)] == [
        (0.0, "boot", []),
        (2.0, "message", [(0, 1), (0, 2), (2, 3)]),
        (3.0, "message", [(2, 4)]),
    ]


# --- timers -----------------------------------------------------------------

def test_timer_fires_after_its_delay(tmp_path):
    log = _run(tmp_path, {0: {"boot": [{"set": "a", "delay": 2.5}]}})
    assert [(e["t"], e["tag"]) for e in log if e["call"] == "timer"] == [(2.5, "a")]


def test_setting_a_pending_tag_replaces_it(tmp_path):
    """Boot sets 'a' at 5; a message at t=1 sets 'a' again for +1 -> fires
    once, at t=2, never at t=5."""
    script = {
        0: {"boot": [{"set": "a", "delay": 5.0}]},
        1: {"boot": [{"send": 0, "delay": 1.0}]},
    }
    script[0]["message"] = [{"set": "a", "delay": 1.0}]
    log = _run(tmp_path, script)
    assert [(e["t"], e["agent"]) for e in log if e["call"] == "timer"] == [(2.0, 0)]


def test_cancel_discards_a_pending_timer(tmp_path):
    script = {
        0: {"boot": [{"set": "a", "delay": 5.0}], "message": [{"cancel": "a"}]},
        1: {"boot": [{"send": 0, "delay": 1.0}]},
    }
    log = _run(tmp_path, script)
    assert [e for e in log if e["call"] == "timer"] == []


def test_cancel_and_set_in_one_result_restarts_the_timer(tmp_path):
    script = {
        0: {"boot": [{"set": "a", "delay": 3.0}],
            "message": [{"cancel": "a"}, {"set": "a", "delay": 4.0}]},
        1: {"boot": [{"send": 0, "delay": 1.0}]},
    }
    log = _run(tmp_path, script)
    assert [e["t"] for e in log if e["call"] == "timer"] == [5.0]


def test_message_at_the_same_instant_is_processed_before_the_timer(tmp_path):
    """The heartbeat-vs-election-timeout race: a message and a timer due at
    the same instant -- the message runs first and can cancel the timer."""
    script = {
        0: {"boot": [{"set": "election", "delay": 2.0}], "message": [{"cancel": "election"}]},
        1: {"boot": [{"send": 0, "delay": 2.0}]},
    }
    log = _run(tmp_path, script)
    assert [e for e in log if e["call"] == "timer"] == []
    assert [(e["t"], e["trigger"]) for e in _calls(log, 0)] == [(0.0, "boot"), (2.0, "message")]


def test_timer_can_rearm_itself(tmp_path):
    script = {0: {"boot": [{"set": "hb", "delay": 1.5}], "timer:hb": [{"set": "hb", "delay": 1.5}]}}
    log = _run(tmp_path, script, max_time=6.0)
    assert [e["t"] for e in log if e["call"] == "timer"] == [1.5, 3.0, 4.5, 6.0]


def test_timers_and_messages_after_the_run_are_never_delivered(tmp_path):
    script = {0: {"boot": [{"set": "late", "delay": 11.0}, {"send": 1, "delay": 10.5}]}}
    log = _run(tmp_path, script, max_time=10.0)
    assert len(log) == 4  # bootstrap only


# --- failing loudly ---------------------------------------------------------

def test_timers_under_synchronous_activation_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="ScriptedBehavior set or cancelled timers under synchronous"):
        _run(tmp_path, {0: {"boot": [{"set": "a", "delay": 1.0}]}}, activation="synchronous")


def test_timer_without_on_timer_names_the_behavior(tmp_path):
    with pytest.raises(NotImplementedError, match="TimerWithoutHandlerBehavior"):
        _run(tmp_path, behavior=f"{PROBES}.TimerWithoutHandlerBehavior")


@pytest.mark.parametrize("behavior,activation", [
    ("TickOnlyBehavior", "event"),        # every pre-Phase-2 behavior
    ("EventOnlyBehavior", "synchronous"),
])
def test_incompatible_activation_is_rejected_at_load(tmp_path, behavior, activation):
    with pytest.raises(ConfigValidationError, match=f"{behavior} does not support"):
        _run(tmp_path, behavior=f"{PROBES}.{behavior}", activation=activation)
    assert ScriptedBehavior.log == []


def test_shipped_tick_driven_behaviors_are_rejected_under_event_activation(tmp_path):
    """The concrete failure this guards against: GossipBehavior under event
    activation would step once at t=0 and never again."""
    with pytest.raises(ConfigValidationError, match="GossipBehavior does not support"):
        _run(tmp_path, behavior="simul8.plugins.behaviors.gossip_behavior.GossipBehavior",
             protocol="simul8.plugins.communication.gossip.GossipProtocol")


def test_unknown_activation_value_is_rejected(tmp_path):
    with pytest.raises(ConfigValidationError, match="simulation.activation must be one of"):
        _run(tmp_path, activation="asynchronous")


@pytest.mark.parametrize("delay", [0.0, -1.0])
def test_non_positive_timer_delay_is_rejected(tmp_path, delay):
    with pytest.raises(ValueError, match="delay must be a finite number > 0"):
        _run(tmp_path, {0: {"boot": [{"set": "a", "delay": delay}]}})


def test_delay_lost_to_float_resolution_is_rejected(tmp_path):
    """1e-20 passes '> 0' but 5.0 + 1e-20 == 5.0: the effect would be
    simultaneous with its cause."""
    script = {0: {"boot": [{"set": "go", "delay": 5.0}], "timer:go": [{"send": 1, "delay": 1e-20}]}}
    with pytest.raises(ValueError, match="too small to advance virtual time"):
        _run(tmp_path, script)
