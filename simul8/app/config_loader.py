"""
ConfigLoader — loads and validates experiment configuration from YAML files.

Responsibilities:
    - Parse YAML into an ExperimentConfig (frozen dataclass)
    - Validate required fields with clear error messages
    - Enforce schema_version compatibility

The loader is strict by design: unknown fields are silently ignored,
but missing required fields raise ConfigValidationError with the exact
field path. Research reproducibility depends on catching config mistakes
before a simulation runs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..domain.experiment import ExperimentConfig, PluginsConfig, SimulationConfig

SUPPORTED_SCHEMA_VERSIONS: frozenset[str] = frozenset({"1.0"})


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

    def _parse(self, raw: dict[str, Any]) -> ExperimentConfig:
        version = raw.get("schema_version")
        if version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ConfigValidationError(
                f"Unsupported schema_version '{version}'. "
                f"Supported versions: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            )

        experiment = raw.get("experiment", {})
        simulation = raw.get("simulation", {})
        plugins = raw.get("plugins", {})
        plugin_configs = raw.get("plugin_configs", {})

        # Validate required fields
        self._require(experiment, "name", "experiment.name")
        self._require(experiment, "seed", "experiment.seed")
        self._require(simulation, "num_agents", "simulation.num_agents")
        self._require(simulation, "max_virtual_time", "simulation.max_virtual_time")
        self._require(plugins, "behavior", "plugins.behavior")
        self._require(plugins, "communication", "plugins.communication")
        self._require(plugins, "topology", "plugins.topology")

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
            ),
            plugins=PluginsConfig(
                behavior=str(plugins["behavior"]),
                communication=str(plugins["communication"]),
                topology=str(plugins["topology"]),
                metrics=tuple(metrics),
                persistence=tuple(persistence),
            ),
            plugin_configs=plugin_configs,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
