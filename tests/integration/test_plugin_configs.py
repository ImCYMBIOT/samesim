"""plugin_configs can't be silently ignored, and a run records its whole config.

Two classes of plausible-but-wrong run, both of which used to happen:

- An option the plugin never reads (a typo, a key for another mode, a
  section naming a plugin that isn't in the experiment) had no effect: the
  plugin ran on its defaults and nothing said so. Every such option is now
  rejected before the simulation starts.
- summary.json listed fields by hand and missed every field added later
  (activation, dynamics, metrics, plugin_configs). It now embeds the
  resolved ExperimentConfig, and the test below walks the dataclass fields,
  so a field added tomorrow is checked too.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
import yaml

from simul8.app.config_loader import ConfigValidationError
from simul8.app.experiment_runner import ExperimentRunner, TrackedConfig
from simul8.domain.experiment import ExperimentConfig, PluginsConfig

# One real plugin per configurable role, with an option it reads. Discovered
# roles (below) must all appear here, so adding a role to PluginsConfig
# fails this test until the new role is covered.
ROLE_EXAMPLES = {
    "behavior": ("simul8.plugins.behaviors.gossip_behavior.GossipBehavior", "fan_out", 2),
    "communication": ("simul8.plugins.communication.lossy.LossyProtocol", "loss_probability", 0.1),
    "topology": ("simul8.plugins.topologies.watts_strogatz.WattsStrogatzTopology", "k", 4),
    "dynamics": ("simul8.plugins.dynamics.random_churn.RandomChurn", "failure_rate", 0.01),
}

# Roles that hold one plugin (str) receive plugin_configs; list roles
# (metrics, persistence) never do.
CONFIGURABLE_ROLES = [f.name for f in dataclasses.fields(PluginsConfig)
                      if f.type in ("str", "str | None", str)]


def _cfg(**plugin_overrides) -> dict:
    plugins = {
        "behavior": ROLE_EXAMPLES["behavior"][0],
        "communication": ROLE_EXAMPLES["communication"][0],
        "topology": ROLE_EXAMPLES["topology"][0],
        "metrics": ["simul8.plugins.metrics.convergence.ConvergenceMetric"],
        "persistence": ["simul8.plugins.persistence.csv_exporter.CsvExporter"],
    }
    plugins.update(plugin_overrides)
    return {
        "schema_version": "1.0",
        "experiment": {"name": "cfg", "seed": 3},
        "simulation": {"num_agents": 12, "max_virtual_time": 5},
        "plugins": plugins,
        "plugin_configs": {},
    }


def _run(tmp_path: Path, cfg: dict) -> Path:
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg))
    out = tmp_path / "out"
    ExperimentRunner().run(path, output_dir=out)
    return out


def _name(class_path: str) -> str:
    return class_path.rsplit(".", 1)[-1]


def test_every_configurable_role_is_covered():
    assert set(CONFIGURABLE_ROLES) == set(ROLE_EXAMPLES), (
        "PluginsConfig's single-plugin roles changed; add the new role to "
        "ROLE_EXAMPLES so its plugin_configs are checked too"
    )


@pytest.mark.parametrize("role", CONFIGURABLE_ROLES)
def test_the_real_option_is_accepted(tmp_path, role):
    path, key, value = ROLE_EXAMPLES[role]
    cfg = _cfg(**{role: path})
    cfg["plugin_configs"][_name(path)] = {key: value}
    _run(tmp_path, cfg)


@pytest.mark.parametrize("role", CONFIGURABLE_ROLES)
def test_a_misspelled_option_is_rejected_with_a_suggestion(tmp_path, role):
    path, key, value = ROLE_EXAMPLES[role]
    cfg = _cfg(**{role: path})
    typo = key.replace("_", "") if "_" in key else key + "x"
    cfg["plugin_configs"][_name(path)] = {typo: value}
    with pytest.raises(ConfigValidationError) as err:
        _run(tmp_path, cfg)
    msg = str(err.value)
    assert _name(path) in msg and typo in msg
    assert f"Did you mean '{key}'" in msg


def test_an_option_for_another_mode_is_rejected(tmp_path):
    # 'mean' configures the exponential distribution; with constant delays
    # it would be silently ignored.
    cfg = _cfg(communication="simul8.plugins.communication.latency.LatencyProtocol")
    cfg["plugin_configs"]["LatencyProtocol"] = {"distribution": "constant", "mean": 5.0}
    with pytest.raises(ConfigValidationError, match="'mean'"):
        _run(tmp_path, cfg)


def test_a_section_for_a_plugin_not_in_the_experiment_is_rejected(tmp_path):
    cfg = _cfg()
    cfg["plugin_configs"]["GossipBehaviour"] = {"fan_out": 2}
    with pytest.raises(ConfigValidationError, match="Did you mean 'GossipBehavior'"):
        _run(tmp_path, cfg)


def test_options_for_a_metric_or_exporter_are_rejected(tmp_path):
    cfg = _cfg()
    cfg["plugin_configs"]["CsvExporter"] = {"output_dir": "./results"}
    with pytest.raises(ConfigValidationError, match="takes no configuration"):
        _run(tmp_path, cfg)


def test_empty_sections_are_fine(tmp_path):
    cfg = _cfg()
    cfg["plugin_configs"] = {"GossipBehavior": {}, "LossyProtocol": None, "CsvExporter": {}}
    _run(tmp_path, cfg)


def test_lossy_mode_is_rejected_with_an_explanation(tmp_path):
    cfg = _cfg()
    cfg["plugin_configs"]["LossyProtocol"] = {"mode": "broadcast"}
    with pytest.raises(ValueError, match="Message.broadcast"):
        _run(tmp_path, cfg)


def test_tracked_config_counts_every_way_of_reading():
    # A plugin that reads its options in bulk (iteration, **unpacking,
    # copy) could have used any of them, so none may be reported unread.
    for read_all in (list, lambda c: {**c}, lambda c: c.copy(), lambda c: list(c.items()),
                     lambda c: list(c.keys()), lambda c: list(c.values())):
        c = TrackedConfig({"a": 1, "b": 2})
        read_all(c)
        assert c.unread() == []
    c = TrackedConfig({"a": 1, "b": 2, "c": 3})
    c["a"], c.get("b"), "zzz" in c
    assert c.unread() == ["c"]


def _leaves(obj, prefix=""):
    """(dotted path, value) for every leaf field of a dataclass tree."""
    for f in dataclasses.fields(obj):
        value = getattr(obj, f.name)
        if dataclasses.is_dataclass(value):
            yield from _leaves(value, f"{prefix}{f.name}.")
        else:
            yield f"{prefix}{f.name}", value


def test_summary_records_every_config_field(tmp_path):
    cfg = _cfg(
        behavior="simul8.plugins.behaviors.async_gossip.AsyncGossipBehavior",
        communication="simul8.plugins.communication.latency.LatencyProtocol",
        dynamics="simul8.plugins.dynamics.random_churn.RandomChurn",
    )
    cfg["simulation"].update({"activation": "event", "tick_interval": 0.5})
    cfg["plugin_configs"] = {
        "AsyncGossipBehavior": {"clock_rate": 2.0},
        "LatencyProtocol": {"distribution": "uniform", "low": 0.1, "high": 0.3},
        "RandomChurn": {"failure_rate": 0.05},
    }
    out = _run(tmp_path, cfg)
    recorded = json.loads((out / "summary.json").read_text())["config"]

    from simul8.app.config_loader import ConfigLoader
    config: ExperimentConfig = ConfigLoader().load(tmp_path / "cfg.yaml")
    leaves = list(_leaves(config))
    assert leaves, "no fields found"
    for path, value in leaves:
        node = recorded
        for part in path.split("."):
            assert part in node, f"summary.json is missing config field {path}"
            node = node[part]
        expected = list(value) if isinstance(value, tuple) else value
        assert node == expected, f"summary.json records {path}={node!r}, config has {expected!r}"
