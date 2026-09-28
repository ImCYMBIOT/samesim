"""
Churn (Phase 3): failures, recoveries, joins and edge changes, observed from
inside behaviors and metrics.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest
import yaml

from simul8.app.experiment_runner import ExperimentRunner
from tests.integration.event_probes import EventLogMetric, PayloadDelayProtocol, ScriptedBehavior

PROBES = "tests.integration.event_probes"
SCHEDULED = "simul8.plugins.dynamics.scheduled.ScheduledChurn"


def _run(tmp_path, script=None, events=(), *, n=4, max_time=10.0, activation="event",
         behavior=f"{PROBES}.ScriptedBehavior", topology="simul8.plugins.topologies.ring.RingTopology",
         behavior_config=None, metrics=(), persistence=(), extra_configs=None):
    ScriptedBehavior.log = []
    EventLogMetric.log = []
    PayloadDelayProtocol.topology_changes = []
    cfg = {
        "schema_version": "1.0",
        "experiment": {"name": "churn", "seed": 3},
        "simulation": {"num_agents": n, "max_virtual_time": max_time,
                       "tick_interval": 1.0, "activation": activation},
        "plugins": {"behavior": behavior, "communication": f"{PROBES}.PayloadDelayProtocol",
                    "topology": topology, "dynamics": SCHEDULED,
                    "metrics": [f"{PROBES}.EventLogMetric", *metrics], "persistence": list(persistence)},
        "plugin_configs": {"ScheduledChurn": {"events": list(events)}, **(extra_configs or {})},
    }
    # Only the scripted probe takes a script; any other behavior gets exactly
    # the options given (an unread option is rejected by the runner).
    if behavior_config is not None:
        cfg["plugin_configs"][behavior.rsplit(".", 1)[-1]] = behavior_config
    elif behavior.endswith(".ScriptedBehavior"):
        cfg["plugin_configs"]["ScriptedBehavior"] = {"script": script or {}}
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg))
    ExperimentRunner().run(path, output_dir=tmp_path / "out")
    return list(ScriptedBehavior.log), list(EventLogMetric.log)


def _calls(log, agent):
    return [(e["t"], e["trigger"]) for e in log if e["agent"] == agent]


# --- failure ----------------------------------------------------------------

def test_failed_agent_never_runs_and_messages_to_it_are_lost(tmp_path):
    script = {0: {"boot": [{"set": "go", "delay": 2.0}], "timer:go": [{"send": 1, "delay": 0.5}]}}
    calls, events = _run(tmp_path, script, [{"at": 1.5, "fail": [1]}])
    assert _calls(calls, 1) == [(0.0, "boot")]
    assert [e for e in events if e[0] == "lost"] == [("lost", 2.5, 1, "recipient_failed")]
    assert not [e for e in events if e[0] == "delivered"]


def test_messages_sent_before_failing_still_arrive(tmp_path):
    script = {0: {"boot": [{"send": 1, "delay": 2.0}]}}
    calls, _ = _run(tmp_path, script, [{"at": 1.0, "fail": [0]}])
    assert [(e["t"], e["inbox"]) for e in calls if e["agent"] == 1 and e["inbox"]] == [(2.0, [(0, 1)])]


def test_failure_at_the_same_instant_as_a_delivery_comes_first(tmp_path):
    script = {0: {"boot": [{"send": 1, "delay": 2.0}]}}
    _, events = _run(tmp_path, script, [{"at": 2.0, "fail": [1]}])
    assert [e for e in events if e[0] in ("lost", "delivered")] == [("lost", 2.0, 1, "recipient_failed")]


def test_failure_cancels_timers(tmp_path):
    script = {0: {"boot": [{"set": "late", "delay": 3.0}]}}
    calls, _ = _run(tmp_path, script, [{"at": 1.0, "fail": [0]}])
    assert not [e for e in calls if e["call"] == "timer"]


# --- recovery ---------------------------------------------------------------

def test_event_mode_recovery_keeps_state_and_runs_a_bootstrap_step(tmp_path):
    script = {0: {"boot": [{"set": "t", "delay": 3.0}], "step": [{"set": "t", "delay": 1.0}]}}
    calls, _ = _run(tmp_path, script, [{"at": 1.0, "fail": [0]}, {"at": 5.0, "recover": [0]}])
    mine = [e for e in calls if e["agent"] == 0]
    assert [(e["t"], e["call"], e.get("trigger")) for e in mine] == [
        (0.0, "step", "boot"),       # the t=3 timer is lost in the failure...
        (5.0, "step", "step"),       # ...recovery: default on_recover = empty-inbox step,
        (6.0, "timer", None),        # which re-armed the timer.
    ]
    assert mine[1]["calls"] == 1, "state survived the failure"


def test_sync_mode_recovery_resumes_at_the_next_tick(tmp_path):
    calls, _ = _run(tmp_path, {}, [{"at": 1.5, "fail": [1]}, {"at": 3.5, "recover": [1]}],
                    activation="synchronous", max_time=6.0)
    assert [t for t, _ in _calls(calls, 1)] == [0.0, 1.0, 4.0, 5.0, 6.0]


def test_where_selector_targets_by_state_at_the_time_of_the_event(tmp_path):
    """'Fail whoever has made 2 calls by t=1.5' -- decided at 1.5, not at setup."""
    script = {2: {"boot": [{"set": "a", "delay": 1.0}]}}
    calls, events = _run(tmp_path, script, [{"at": 1.5, "fail": {"where": {"calls": 2}}}])
    assert [e for e in events if e[0] == "change"] == [("change", 1.5, [2], [], [])]


# --- joins and edges --------------------------------------------------------

def test_joining_agent_is_initialized_exactly_as_at_t0(tmp_path):
    """An agent joining at t=2 must start from the same state it would have
    had if present from the start: same config, same per-agent RNG."""
    def first_value(n, events, subdir):
        _run(tmp_path / subdir, behavior="simul8.plugins.behaviors.async_gossip.AsyncGossipBehavior",
             behavior_config={}, n=n, events=events,
             metrics=["simul8.plugins.metrics.state_trace.StateTraceMetric"],
             persistence=["simul8.plugins.persistence.csv_exporter.CsvExporter"])
        with open(tmp_path / subdir / "out" / "churn_state_trace.csv", newline="") as f:
            rows = [r for r in csv.DictReader(l for l in f if not l.startswith("#"))]
        return next((float(r["virtual_time"]), r["state"]) for r in rows if r["agent_id"] == "4")
    (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir()
    t_a, v_a = first_value(5, [], "a")
    t_b, v_b = first_value(4, [{"at": 2.0, "join": [4], "add_edges": [[4, 0]]}], "b")
    assert (t_a, t_b) == (0.0, 2.0)
    assert v_a == v_b


def test_edges_change_neighbors_and_protocols_are_told(tmp_path):
    script = {0: {"boot": [{"set": "x", "delay": 3.0}]}}
    calls, _ = _run(tmp_path, script, [
        {"at": 1.0, "join": [4], "add_edges": [[4, 0], [4, 2]]},
        {"at": 2.0, "remove_edges": [[0, 1]]},
    ])
    joined = [e for e in calls if e["agent"] == 4]
    assert (joined[0]["t"], joined[0]["trigger"], joined[0]["neighbors"]) == (1.0, "boot", [0, 2])
    graphs = PayloadDelayProtocol.topology_changes
    assert len(graphs) == 2
    assert graphs[0][0] == [1, 3, 4] and graphs[1][0] == [3, 4]


# --- failing loudly ---------------------------------------------------------

@pytest.mark.parametrize("events,match", [
    ([{"at": 1.0, "fail": [1]}, {"at": 2.0, "fail": [1]}], "agent 1 has already failed"),
    ([{"at": 1.0, "recover": [1]}], "agent 1 has not failed"),
    ([{"at": 1.0, "fail": [9]}], "agent 9 does not exist"),
    ([{"at": 1.0, "join": [2]}], "id 2 is negative or already in use"),
    ([{"at": 1.0, "add_edges": [[0, 1]]}], r"\(0, 1\) already exists"),
    ([{"at": 1.0, "remove_edges": [[0, 2]]}], r"\(0, 2\) does not exist"),
    ([{"at": 1.0, "add_edges": [[0, 7]]}], "names an unknown agent"),
])
def test_invalid_changes_fail_naming_the_plugin(tmp_path, events, match):
    with pytest.raises(ValueError, match=f"ScheduledChurn produced an invalid change(.|\\n)*{match}"):
        _run(tmp_path, {}, events)


@pytest.mark.parametrize("events,match", [
    ([{"at": 0.0, "fail": [1]}], "strictly increasing"),
    ([{"at": 2.0, "fail": [1]}, {"at": 2.0, "recover": [1]}], "strictly increasing"),
    ([{"at": 1.0, "crash": [1]}], "unknown keys"),
])
def test_invalid_schedules_fail_at_setup(tmp_path, events, match):
    with pytest.raises(ValueError, match=match):
        _run(tmp_path, {}, events)


# --- accounting -------------------------------------------------------------

def test_every_message_is_delivered_or_reported_lost(tmp_path):
    """Nothing vanishes silently: with all traffic well before the horizon,
    copies sent == delivered + lost, under heavy failure/recovery churn."""
    script = {i: {"boot": [{"send": j, "delay": 0.5 + 0.7 * j} for j in range(6) if j != i]}
              for i in range(6)}
    events = [{"at": 0.3 * (k + 1), ("fail" if k % 2 == 0 else "recover"): [k // 2 % 6]}
              for k in range(12)]
    _, log = _run(tmp_path, script, events, n=6, max_time=20.0,
                  topology="simul8.plugins.topologies.random_graph.ErdosRenyiTopology",
                  extra_configs={"ErdosRenyiTopology": {"edge_probability": 1.0}})
    sent = 6 * 5
    delivered = sum(1 for e in log if e[0] == "delivered")
    lost = sum(1 for e in log if e[0] == "lost")
    assert lost > 0 and delivered + lost == sent, (delivered, lost)


def test_timer_due_after_recovery_was_still_lost_in_the_failure(tmp_path):
    """Timers die with the failure. A timer set before failing and due after
    recovery must not fire; it only would if failure merely paused it."""
    script = {0: {"boot": [{"set": "t", "delay": 3.0}]}}
    calls, _ = _run(tmp_path, script, [{"at": 1.0, "fail": [0]}, {"at": 2.0, "recover": [0]}])
    assert not [e for e in calls if e["call"] == "timer"]
