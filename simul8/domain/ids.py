"""Domain type aliases. All IDs are ints — efficient, hashable, Rust-compatible."""
from __future__ import annotations

from typing import NewType

# Core identity types
AgentId = NewType("AgentId", int)
EventId = NewType("EventId", int)
MessageId = NewType("MessageId", int)

# Time is a float so fractional ticks are representable without special-casing.
# The engine always advances time monotonically.
VirtualTime = NewType("VirtualTime", float)

# Metric and plugin naming
MetricName = NewType("MetricName", str)
