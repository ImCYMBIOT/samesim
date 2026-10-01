"""The samesim command line and Python API, and the catalog they read from."""
from __future__ import annotations

import pytest

import samesim
from samesim.app import api, catalog
from samesim.app.config_loader import ConfigValidationError
from samesim.cli.main import main

EXAMPLES = catalog.list_examples()
PLUGINS = catalog.discover_plugins()


# ------------------------------------------------- catalog (auto-discovered)

def test_catalog_finds_every_kind_of_plugin():
    assert {p.kind for p in PLUGINS} == set(catalog.KINDS)
    assert len(PLUGINS) >= 30


@pytest.mark.parametrize("plugin", PLUGINS, ids=lambda p: p.name)
def test_every_plugin_says_what_it_does_and_which_options_it_takes(plugin):
    """`samesim plugins NAME` shows the module docstring's first line and its
    Configuration / Config keys block. A plugin without them is invisible to
    anyone using the CLI; "Config keys: none." is fine."""
    assert plugin.summary, f"{plugin.path}: module docstring has no first line"
    assert plugin.options, (f"{plugin.path}: module docstring has no 'Configuration:' or "
                            f"'Config keys:' block (write 'Config keys: none.' if it takes none)")


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda e: e.name)
def test_every_example_describes_itself_and_validates(example):
    assert example.summary, f"{example.path.name} needs a leading '# ...' description"
    samesim.validate(example.name)


# ---------------------------------------------------------------- the API

def test_api_runs_in_memory_and_writes_only_when_asked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = samesim.run("gossip_ring", overrides={"simulation.max_virtual_time": 5})
    assert r.output_files == [] and not any(tmp_path.iterdir()), "no output_dir: no files"
    assert len(r.series["convergence_variance"].records) == 6  # ticks 0..5
    r = samesim.run("gossip_ring", output_dir=tmp_path / "out", overrides={"simulation.max_virtual_time": 5})
    assert r.output_files and (tmp_path / "out" / "summary.json").exists()


def test_api_seed_and_overrides_change_the_run():
    base = samesim.run("gossip_ring", overrides={"simulation.max_virtual_time": 3})
    same = samesim.run("gossip_ring", overrides={"simulation.max_virtual_time": 3})
    other = samesim.run("gossip_ring", seed=99, overrides={"simulation.max_virtual_time": 3})
    values = lambda r: [x.value for x in r.series["convergence_variance"].records]
    assert values(base) == values(same) != values(other)
    assert other.config.seed == 99


def test_api_accepts_a_dict_and_validate_catches_problems():
    raw = api.load_raw("gossip_ring")
    assert samesim.validate(raw).name == "gossip_ring"
    raw["plugin_configs"]["GossipBehavior"].pop("fan_out", None)
    raw["plugin_configs"]["GossipBehavior"]["fanout"] = 3  # a misspelling of an unset option
    with pytest.raises(ConfigValidationError, match="Did you mean 'fan_out'"):
        samesim.validate(raw)


def test_unknown_config_name_lists_the_examples():
    with pytest.raises(FileNotFoundError, match="gossip_ring"):
        samesim.validate("no_such_thing")


@pytest.mark.parametrize("text,want", [
    ("1-3", [1, 2, 3]), ("1,5,9", [1, 5, 9]), ("1-3,10", [1, 2, 3, 10]), ("2,2,1-2", [2, 1]),
])
def test_seed_lists(text, want):
    assert api.parse_seeds(text) == want


@pytest.mark.parametrize("text,want", [
    ("simulation.num_agents=500", ("simulation.num_agents", 500)),
    ("a.b=[0, 1]", ("a.b", [0, 1])),
    ("a.b=true", ("a.b", True)),
    ("a.b=event", ("a.b", "event")),
])
def test_override_values_are_read_as_yaml(text, want):
    assert api.parse_override(text) == want


# ---------------------------------------------------------------- the CLI

def test_cli_new_validate_run_digest(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["new", "study", "--from", "gossip_ring"]) == 0
    text = (tmp_path / "study.yaml").read_text()
    assert 'name: "study"' in text and text.startswith("#"), "renamed, comments kept"
    assert main(["new", "study", "--from", "gossip_ring"]) == 2, "won't overwrite without --force"

    assert main(["validate", "study.yaml"]) == 0
    assert main(["validate", "study.yaml", "--set", "simulation.num_agnts=5"]) == 2
    assert "Did you mean 'simulation.num_agents'" in capsys.readouterr().err

    assert main(["run", "study.yaml", "-o", "out", "--seed", "4",
                 "--set", "simulation.max_virtual_time=5",
                 "--set", "plugins.metrics=[samesim.plugins.metrics.trace_digest.TraceDigestMetric]"]) == 0
    assert (tmp_path / "out" / "summary.json").exists()
    capsys.readouterr()
    assert main(["digest", "out"]) == 0
    assert len(capsys.readouterr().out.split()[0]) == 64  # a SHA-256 hex digest
    assert main(["digest", "nowhere"]) == 2


def test_cli_sweep_runs_each_seed(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["sweep", "gossip_ring", "--seeds", "1-3", "-o", "sw",
                 "--set", "simulation.max_virtual_time=3"]) == 0
    assert sorted(p.name for p in (tmp_path / "sw").iterdir()) == ["seed-1", "seed-2", "seed-3"]


def test_cli_lists_examples_and_plugins(capsys):
    assert main(["examples"]) == 0
    out = capsys.readouterr().out
    assert all(e.name in out for e in EXAMPLES)
    assert main(["plugins"]) == 0
    out = capsys.readouterr().out
    assert all(p.name in out for p in PLUGINS)
    assert main(["plugins", "LatencyProtocol"]) == 0
    assert "distribution" in capsys.readouterr().out
    assert main(["plugins", "NoSuchPlugin"]) == 2
