"""
ConfigLoader — loads and validates experiment configuration from YAML files.

Responsibilities:
    - Parse YAML into an ExperimentConfig (frozen dataclass)
    - Validate required fields with clear error messages
    - Enforce schema_version compatibility

The loader is strict by design: missing required fields and unknown
fields both raise ConfigValidationError with the exact field path (and,
for an unknown field, the closest known one). An unknown field used to be
ignored, so a typo such as `activaton: event` silently ran the default.
Research reproducibility depends on catching config mistakes before a
simulation runs. (Options inside plugin_configs are checked separately,
against what each plugin actually reads; see ExperimentRunner.)
"""
from __future__ import annotations

import dataclasses
import difflib
from pathlib import Path
from typing import Any

import yaml

from ..domain.experiment import (
    ACTIVATION_MODES,
    ExperimentConfig,
    PluginsConfig,
    SimulationConfig,
)

SUPPORTED_SCHEMA_VERSIONS: frozenset[str] = frozenset({"1.0"})
TOP_LEVEL_KEYS = ("schema_version", "experiment", "simulation", "plugins", "plugin_configs")
EXPERIMENT_KEYS = ("name", "seed")


class ConfigValidationError(Exception):
    """Raised when a config file is missing required fields or has an invalid value."""


class ConfigLoader:
    """Loads YAML experiment configurations into frozen ExperimentConfig objects.

    Usage:
        loader = ConfigLoader()
        config = loader.load("examples/gossip_1000_agents.yaml")
    """

    def load(self, path: Path | str) -> ExperimentConfig:
        """Load and validate a YAML config file.

        Args:
            path: Path to the YAML config file.

        Returns:
            A frozen ExperimentConfig ready for use by ExperimentRunner.

        Raises:
            FileNotFoundError: If path does not exist.
            ConfigValidationError: If schema_version is unsupported or
                                   required fields are missing.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            raw: dict[str, Any] = yaml.safe_load(f) or {}

        return self._parse(raw)

    def load_dict(self, raw: dict[str, Any]) -> ExperimentConfig:
        """Validate a config given as a dict in the YAML file's shape."""
        if not isinstance(raw, dict):
            raise ConfigValidationError(f"A config must be a mapping, got {type(raw).__name__}")
        return self._parse(raw)

    def load_raw(self, path: Path | str) -> dict[str, Any]:
        """The YAML file as a plain dict, before validation."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _parse(self, raw: dict[str, Any]) -> ExperimentConfig:
        version = raw.get("schema_version")
        if version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ConfigValidationError(
                f"Unsupported schema_version '{version}'. "
                f"Supported versions: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            )

        experiment = raw.get("experiment") or {}
        simulation = raw.get("simulation") or {}
        plugins = raw.get("plugins") or {}
        plugin_configs = raw.get("plugin_configs") or {}

        # Unknown keys, in every section the loader owns. The allowed names
        # come from the config dataclasses' own fields, so a field added to
        # SimulationConfig or PluginsConfig is accepted automatically.
        self._known(raw, set(TOP_LEVEL_KEYS), "")
        for name, section in (("experiment", experiment), ("simulation", simulation),
                              ("plugins", plugins), ("plugin_configs", plugin_configs)):
            if not isinstance(section, dict):
                raise ConfigValidationError(f"'{name}' must be a mapping, got {section!r}")
        self._known(experiment, set(EXPERIMENT_KEYS), "experiment.")
        self._known(simulation, {f.name for f in dataclasses.fields(SimulationConfig)}, "simulation.")
        self._known(plugins, {f.name for f in dataclasses.fields(PluginsConfig)}, "plugins.")

        # Validate required fields
        self._require(experiment, "name", "experiment.name")
        self._require(experiment, "seed", "experiment.seed")
        self._require(simulation, "num_agents", "simulation.num_agents")
        self._require(simulation, "max_virtual_time", "simulation.max_virtual_time")
        self._require(plugins, "behavior", "plugins.behavior")
        self._require(plugins, "communication", "plugins.communication")
        self._require(plugins, "topology", "plugins.topology")

        activation = str(simulation.get("activation", "synchronous"))
        if activation not in ACTIVATION_MODES:
            raise ConfigValidationError(
                f"simulation.activation must be one of {list(ACTIVATION_MODES)}, "
                f"got '{activation}'"
            )

        # Normalise list fields (YAML scalars vs lists)
        metrics = self._as_list(plugins.get("metrics", []))
        persistence = self._as_list(plugins.get("persistence", []))

        return ExperimentConfig(
            schema_version=str(version),
            name=str(experiment["name"]),
            seed=int(experiment["seed"]),
            simulation=SimulationConfig(
                num_agents=int(simulation["num_agents"]),
                max_virtual_time=float(simulation["max_virtual_time"]),
                tick_interval=float(simulation.get("tick_interval", 1.0)),
                activation=activation,
            ),
            plugins=PluginsConfig(
                behavior=str(plugins["behavior"]),
                communication=str(plugins["communication"]),
                topology=str(plugins["topology"]),
                metrics=tuple(metrics),
                persistence=tuple(persistence),
                dynamics=str(plugins["dynamics"]) if plugins.get("dynamics") else None,
            ),
            plugin_configs=plugin_configs,
        )

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------

    @staticmethod
    def with_overrides(raw: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
        """A copy of `raw` with dotted-path values replaced or added.

        {"simulation.num_agents": 500, "plugin_configs.GossipBehavior.fan_out": 4}
        sets those two values. Intermediate mappings are created as needed
        under plugin_configs (a plugin with no section yet); anywhere else a
        missing section or a path through a non-mapping is an error, so a
        mistyped path fails instead of being silently added.

        Raises:
            ConfigValidationError: naming the bad path.
        """
        import copy
        out = copy.deepcopy(raw)
        for path, value in overrides.items():
            parts = path.split(".")
            if not all(parts):
                raise ConfigValidationError(f"Override path '{path}' has an empty part")
            node = out
            for i, part in enumerate(parts[:-1]):
                if part not in node:
                    if parts[0] == "plugin_configs":
                        node[part] = {}
                    else:
                        raise ConfigValidationError(
                            f"Override '{path}': no section '{'.'.join(parts[:i + 1])}' in the config"
                        )
                node = node[part]
                if not isinstance(node, dict):
                    raise ConfigValidationError(
                        f"Override '{path}': '{'.'.join(parts[:i + 1])}' is not a section"
                    )
            node[parts[-1]] = value
        return out

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _known(section: dict, allowed: set[str], prefix: str) -> None:
        for key in section:
            if key not in allowed:
                close = difflib.get_close_matches(str(key), sorted(allowed), n=1)
                hint = f" Did you mean '{prefix}{close[0]}'?" if close else ""
                raise ConfigValidationError(
                    f"Unknown config field '{prefix}{key}' -- it would be ignored.{hint} "
                    f"Known fields here: {sorted(allowed)}."
                )

    @staticmethod
    def _require(section: dict, key: str, path: str) -> None:
        if key not in section:
            raise ConfigValidationError(f"Required field missing: '{path}'")

    @staticmethod
    def _as_list(value: Any) -> list:
        if isinstance(value, list):
            return value
        if value is None:
            return []
        return [value]
