"""
JsonlTraceExporter — writes the event trace as one JSON object per line.

Output: {experiment_name}_trace.jsonl

    line 1      {"kind": "header", "schema": "samesim.trace/1", "experiment",
                 "seed", "schema_version", "simulation": {...}, "topology",
                 "positions", "initial_states"}
    line 2...   one event per line, in dispatch order, in the shapes listed
                in metrics.event_trace

The file is self-describing and byte-identical for the same config and seed
on every platform: keys are sorted and values are in canonical form. Read
it line by line with any JSON parser; "schema" changes if the shapes ever
do.

Needs metrics.event_trace.EventTraceMetric among plugins.metrics, and says
so if it is missing. Other series are left to other exporters.

Config keys: none.
"""
from __future__ import annotations

from pathlib import Path

from ...domain.canonical import canonical_json
from ...domain.experiment import ExperimentConfig
from ...domain.metric import MetricSeries
from ...ports.persistence import PersistencePort

_SERIES = "event_trace"


class JsonlTraceExporter(PersistencePort):
    """Writes the EventTraceMetric series to a JSON Lines file."""

    def write(
        self,
        series: list[MetricSeries],
        config: ExperimentConfig,
        output_dir: Path,
    ) -> list[Path]:
        trace = next((s for s in series if str(s.name) == _SERIES), None)
        if trace is None:
            raise ValueError(
                "JsonlTraceExporter has no trace to write: add "
                "samesim.plugins.metrics.event_trace.EventTraceMetric to plugins.metrics."
            )
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        sim = config.simulation
        header = {
            "kind": "header",
            "schema": trace.metadata.get("schema"),
            "experiment": config.name,
            "seed": config.seed,
            "schema_version": config.schema_version,
            "simulation": {
                "num_agents": sim.num_agents,
                "max_virtual_time": sim.max_virtual_time,
                "tick_interval": sim.tick_interval,
                "activation": sim.activation,
            },
            "topology": trace.metadata.get("topology"),
            "positions": trace.metadata.get("positions"),
            "initial_states": trace.metadata.get("initial_states"),
        }
        path = output_dir / f"{config.name}_trace.jsonl"
        with open(path, "w", newline="\n", encoding="utf-8") as f:
            f.write(canonical_json(header) + "\n")
            for record in trace.records:
                f.write(dict(record.tags)["event"] + "\n")
        return [path]
