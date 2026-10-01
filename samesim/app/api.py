"""
The entry points shared by the Python API (samesim.run, samesim.validate)
and the command line, so the two cannot drift apart.

A config can be given as:
    - a path to a YAML file,
    - the name of a shipped example ("raft_leader_crash"; see
      `samesim examples`),
    - a dict in the YAML file's shape.

`seed` replaces experiment.seed; `overrides` sets dotted paths, as
{"simulation.num_agents": 500, "plugin_configs.GossipBehavior.fan_out": 4}.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from ..domain.experiment import ExperimentConfig
from .catalog import find_example, list_examples
from .config_loader import ConfigLoader
from .experiment_runner import ExperimentRunner, RunResult

ConfigLike = "dict[str, Any] | str | Path"


def load_raw(config: dict[str, Any] | str | Path) -> dict[str, Any]:
    """The config as a plain dict, from a dict, a YAML path or an example name."""
    if isinstance(config, dict):
        return copy.deepcopy(config)
    path = Path(config)
    if path.exists():
        return ConfigLoader().load_raw(path)
    example = find_example(str(config))
    if example is not None:
        return ConfigLoader().load_raw(example.path)
    names = ", ".join(e.name for e in list_examples())
    raise FileNotFoundError(
        f"No config file '{config}', and no example by that name. Examples: {names}."
    )


def prepare(config: dict[str, Any] | str | Path, *, seed: int | None = None,
            overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """load_raw, then apply the seed and overrides."""
    raw = load_raw(config)
    changes = dict(overrides or {})
    if seed is not None:
        changes["experiment.seed"] = int(seed)
    return ConfigLoader.with_overrides(raw, changes) if changes else raw


def run(config: dict[str, Any] | str | Path, output_dir: str | Path | None = None, *,
        seed: int | None = None, overrides: dict[str, Any] | None = None) -> RunResult:
    """Run an experiment. Writes result files only if output_dir is given."""
    raw = prepare(config, seed=seed, overrides=overrides)
    return ExperimentRunner().run(raw, output_dir, write=output_dir is not None)


def validate(config: dict[str, Any] | str | Path, *, seed: int | None = None,
             overrides: dict[str, Any] | None = None) -> ExperimentConfig:
    """Everything a run does before its first event; raises on any problem."""
    return ExperimentRunner().validate(prepare(config, seed=seed, overrides=overrides))


def parse_override(text: str) -> tuple[str, Any]:
    """'simulation.num_agents=500' -> ('simulation.num_agents', 500).

    The value is parsed as YAML, so numbers, booleans, lists and nested
    mappings come out typed: fan_out=4 is an int, range=[0, 1] a list.
    """
    if "=" not in text:
        raise ValueError(f"Override '{text}' must look like path.to.key=value")
    key, value = text.split("=", 1)
    key = key.strip()
    if not key:
        raise ValueError(f"Override '{text}' has no key")
    return key, yaml.safe_load(value) if value.strip() else ""


def parse_seeds(text: str) -> list[int]:
    """'1-20' -> 1..20; '1,5,9'; '1-3,10' -> [1, 2, 3, 10]. Order kept, duplicates dropped."""
    seeds: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part[1:]:
            lo, hi = part.split("-", 1) if not part.startswith("-") else (part, part)
            lo_i, hi_i = int(lo), int(hi)
            if hi_i < lo_i:
                raise ValueError(f"Seed range '{part}' runs backwards")
            seeds.extend(range(lo_i, hi_i + 1))
        else:
            seeds.append(int(part))
    if not seeds:
        raise ValueError(f"No seeds in '{text}'")
    return list(dict.fromkeys(seeds))
