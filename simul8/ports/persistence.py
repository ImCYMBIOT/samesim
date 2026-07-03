"""
PersistencePort — the contract for exporting simulation results.

Purpose:
    Writes MetricSeries data to a storage backend after the simulation ends.

Contracts:
    - MUST NOT import from simul8.core or simul8.app
    - write() MUST be idempotent (calling twice produces identical output)
    - write() MUST embed experiment metadata (name, seed, schema_version)
      in the output so results are self-describing

Extension:
    Implement to export to: CSV, JSON, SQLite, Parquet, HDF5, InfluxDB, etc.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..domain.experiment import ExperimentConfig
from ..domain.metric import MetricSeries


class PersistencePort(ABC):
    """Abstract contract for writing simulation results to a storage backend."""

    @abstractmethod
    def write(
        self,
        series: list[MetricSeries],
        config: ExperimentConfig,
        output_dir: Path,
    ) -> list[Path]:
        """Export all metric series to the output directory.

        Args:
            series:     All MetricSeries collected during the simulation.
            config:     The experiment configuration (for metadata embedding).
            output_dir: Directory to write output files into.

        Returns:
            List of paths to the files that were written.
        """
        ...
