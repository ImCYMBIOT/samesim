"""
CsvExporter — writes MetricSeries to CSV files, one file per series.

Output format:
    {experiment_name}_{metric_name}.csv
    Columns: virtual_time, value

Metadata is embedded as a comment header (lines starting with #) for
self-describing output files. This ensures results are reproducible:
the experiment name and seed are recorded alongside the data.
"""
from __future__ import annotations

import csv
from pathlib import Path

from ...domain.experiment import ExperimentConfig
from ...domain.metric import MetricSeries
from ...ports.persistence import PersistencePort


class CsvExporter(PersistencePort):
    """Exports MetricSeries to CSV files, one file per named series.

    Output files are self-describing: experiment metadata is written
    as comment lines at the top of each file.
    """

    def write(
        self,
        series: list[MetricSeries],
        config: ExperimentConfig,
        output_dir: Path,
    ) -> list[Path]:
        """Write all series to output_dir. Returns list of written paths."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []

        for s in series:
            filename = f"{config.name}_{s.name}.csv"
            filepath = output_dir / filename

            with open(filepath, "w", newline="", encoding="utf-8") as f:
                # Metadata header (self-describing)
                f.write(f"# experiment: {config.name}\n")
                f.write(f"# seed: {config.seed}\n")
                f.write(f"# schema_version: {config.schema_version}\n")
                f.write(f"# metric: {s.name}\n")
                f.write(f"# records: {len(s.records)}\n")

                writer = csv.writer(f)
                writer.writerow(["virtual_time", "value"])
                for record in s.records:
                    writer.writerow([record.virtual_time, record.value])

            written.append(filepath)

        return written
