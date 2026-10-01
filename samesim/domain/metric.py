"""
Metric data model.

MetricRecord is a single timestamped observation.
MetricSeries is the accumulation of records for one named metric.

MetricCollectorPort plugins produce them; PersistencePort adapters write them to CSV, JSON, etc.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .ids import MetricName, VirtualTime


@dataclass(frozen=True)
class MetricRecord:
    """A single timestamped observation for one metric.

    Attributes:
        virtual_time: When (in simulation time) this was recorded.
        value:        The numeric value of the metric at this time.
        tags:         Optional key-value pairs for filtering/grouping.
                      Stored as a sorted tuple of pairs for hashability.
    """

    virtual_time: VirtualTime
    value: float
    tags: tuple[tuple[str, str], ...] = ()


@dataclass
class MetricSeries:
    """An ordered sequence of MetricRecords for a single named metric.

    Attributes:
        name:     The metric's canonical name (e.g. "convergence_variance").
        records:  Ordered list of observations, appended during simulation.
        metadata: Arbitrary key-value metadata (e.g. plugin parameters).
    """

    name: MetricName
    records: list[MetricRecord] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def append(self, virtual_time: VirtualTime, value: float, **tags: str) -> None:
        """Append a new observation."""
        record = MetricRecord(
            virtual_time=virtual_time,
            value=value,
            tags=tuple(sorted(tags.items())),
        )
        self.records.append(record)

    def __len__(self) -> int:
        return len(self.records)

    def is_empty(self) -> bool:
        return len(self.records) == 0
