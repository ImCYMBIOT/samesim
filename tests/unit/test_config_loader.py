"""ConfigLoader: unknown fields are rejected; overrides set exactly what they name."""
from __future__ import annotations

import dataclasses

import pytest

from samesim.app.config_loader import ConfigLoader, ConfigValidationError
from samesim.domain.experiment import PluginsConfig, SimulationConfig


def _raw():
    return {
        "schema_version": "1.0",
        "experiment": {"name": "x", "seed": 1},
        "simulation": {"num_agents": 10, "max_virtual_time": 5},
        "plugins": {
            "behavior": "samesim.plugins.behaviors.gossip_behavior.GossipBehavior",
            "communication": "samesim.plugins.communication.gossip.GossipProtocol",
            "topology": "samesim.plugins.topologies.ring.RingTopology",
        },
    }


@pytest.mark.parametrize("section,typo,meant", [
    ("simulation", "activaton", "activation"),
    ("simulation", "num_agent", "num_agents"),
    ("plugins", "metric", "metrics"),
    ("experiment", "sed", "seed"),
    (None, "plugin_config", "plugin_configs"),
])
def test_an_unknown_field_is_rejected_with_a_suggestion(section, typo, meant):
    raw = _raw()
    (raw[section] if section else raw)[typo] = "x"
    with pytest.raises(ConfigValidationError) as err:
        ConfigLoader().load_dict(raw)
    assert typo in str(err.value) and f"Did you mean '{(section + '.') if section else ''}{meant}'" in str(err.value)


def test_every_dataclass_field_is_accepted():
    # The allowed names are read from the dataclasses, so a field added to
    # SimulationConfig or PluginsConfig is accepted without touching the loader.
    for section, cls in (("simulation", SimulationConfig), ("plugins", PluginsConfig)):
        for f in dataclasses.fields(cls):
            raw = _raw()
            raw[section].setdefault(f.name, raw[section].get(f.name, _sample(f.name)))
            ConfigLoader().load_dict(raw)


def _sample(name):
    return {"tick_interval": 1, "activation": "synchronous", "metrics": [], "persistence": [],
            "dynamics": None}.get(name, 1)


def test_overrides_set_nested_values_and_parse_nothing_themselves():
    raw = ConfigLoader.with_overrides(_raw(), {"simulation.num_agents": 50,
                                               "plugin_configs.GossipBehavior.fan_out": 4})
    cfg = ConfigLoader().load_dict(raw)
    assert cfg.simulation.num_agents == 50
    assert cfg.plugin_configs["GossipBehavior"]["fan_out"] == 4
    assert "plugin_configs" not in _raw(), "overrides must not mutate their input"


def test_an_override_into_a_missing_section_fails():
    with pytest.raises(ConfigValidationError, match="no section 'simulaton'"):
        ConfigLoader.with_overrides(_raw(), {"simulaton.num_agents": 5})


def test_a_misspelled_override_key_is_caught_by_the_loader():
    raw = ConfigLoader.with_overrides(_raw(), {"simulation.num_agnts": 5})
    with pytest.raises(ConfigValidationError, match="Did you mean 'simulation.num_agents'"):
        ConfigLoader().load_dict(raw)
