"""EventTraceMetric and JsonlTraceExporter: the run, event by event."""
from __future__ import annotations

import json
from collections import Counter

import pytest

import samesim
from samesim.app import catalog
from samesim.plugins.metrics.event_trace import TRACE_SCHEMA, trace_events

TRACE = "samesim.plugins.metrics.event_trace.EventTraceMetric"
JSONL = "samesim.plugins.persistence.jsonl_trace.JsonlTraceExporter"
EXAMPLES = [e.name for e in catalog.list_examples()]


def _traced(name: str, extra: dict | None = None, output_dir=None):
    raw = samesim.app.api.load_raw(name)
    horizon = raw["simulation"]["max_virtual_time"]
    overrides = {"plugins.metrics": raw["plugins"]["metrics"] + [TRACE],
                 "simulation.max_virtual_time": horizon if horizon <= 60 else horizon / 20,
                 **(extra or {})}
    return samesim.run(name, output_dir, overrides=overrides)


@pytest.mark.parametrize("name", EXAMPLES)
def test_trace_is_ordered_complete_and_leaves_the_run_alone(name):
    plain = samesim.run(name, overrides={
        "simulation.max_virtual_time": _traced(name).config.simulation.max_virtual_time})
    result = _traced(name)
    assert result.digest == plain.digest, "recording the trace changed the run"

    events = trace_events(result.series["event_trace"])
    assert [e["seq"] for e in events] == list(range(len(events)))
    assert [e["t"] for e in events] == sorted(e["t"] for e in events)
    assert events[0]["kind"] == "start" and events[-1]["kind"] == "end"

    # Every message that arrived, or was lost on arrival, was sent first: by
    # that sender, to that recipient, due exactly when it arrived. (Message
    # ids are whatever the behavior assigned, so they are not a unique key.)
    def copies(kinds, when):
        return Counter((e["from"], e["to"], e["id"], e[when]) for e in events if kinds(e))

    sent = copies(lambda e: e["kind"] == "send" and e["arrive"] is not None, "arrive")
    arrived = copies(lambda e: e["kind"] == "deliver"
                     or (e["kind"] == "lost" and e["reason"] == "recipient_failed"), "t")
    assert not arrived - sent, f"arrivals with no matching send: {arrived - sent}"


def test_metadata_holds_the_starting_picture():
    series = _traced("gossip_ring").series["event_trace"]
    n = _traced("gossip_ring").config.simulation.num_agents
    assert series.metadata["schema"] == TRACE_SCHEMA
    assert len(series.metadata["topology"]) == n == len(series.metadata["initial_states"])
    assert series.metadata["positions"] is None
    assert all(len(neighbors) == 2 for _agent, neighbors in series.metadata["topology"])


def test_positions_are_recorded_when_the_topology_has_them():
    raw = samesim.app.api.load_raw("gossip_ring")
    raw["plugins"]["topology"] = "samesim.plugins.topologies.geometric.GeometricTopology"
    raw["plugins"]["metrics"] = raw["plugins"]["metrics"] + [TRACE]
    raw["plugin_configs"] = {k: v for k, v in raw.get("plugin_configs", {}).items() if k != "RingTopology"}
    raw["plugin_configs"]["GeometricTopology"] = {"radius": 0.3}
    raw["simulation"]["max_virtual_time"] = 5
    result = samesim.run(raw)
    positions = result.series["event_trace"].metadata["positions"]
    assert len(positions) == result.config.simulation.num_agents
    assert all(len(xy) == 2 and 0 <= xy[0] <= 1 and 0 <= xy[1] <= 1 for xy in positions.values())


def test_jsonl_file_is_self_describing_and_identical_across_runs(tmp_path):
    files = []
    for run in ("a", "b"):
        result = _traced("raft_leader_crash", {"plugins.persistence": [JSONL],
                                               "simulation.max_virtual_time": 1500}, tmp_path / run)
        (path,) = [f for f in result.output_files if f.endswith("_trace.jsonl")]
        files.append(open(path, "rb").read())
    assert files[0] == files[1], "same config and seed wrote different bytes"

    lines = [json.loads(line) for line in files[0].decode("utf-8").splitlines()]
    header, events = lines[0], lines[1:]
    assert header["kind"] == "header" and header["schema"] == TRACE_SCHEMA
    assert header["experiment"] == result.config.name and header["seed"] == result.config.seed
    assert header["simulation"]["activation"] == "event"
    assert events == trace_events(result.series["event_trace"])
    assert {"send", "deliver", "state", "timer", "change", "tick", "end"} <= {e["kind"] for e in events}


def test_exporter_without_the_metric_says_what_to_add(tmp_path):
    with pytest.raises(ValueError, match="EventTraceMetric"):
        samesim.run("gossip_ring", tmp_path, overrides={"plugins.persistence": [JSONL]})
