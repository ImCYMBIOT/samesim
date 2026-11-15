"""
Canonical form: one fixed, JSON-serializable shape for any state or payload.

Mappings get string keys, sets are sorted, tuples become lists, and anything
that is not a JSON scalar is replaced by its repr. Two values that are equal
as far as a simulation is concerned therefore serialize to the same bytes,
on every run and every platform -- which is what a fingerprint or a trace
file needs.

Values must have a deterministic repr: an object whose repr embeds a memory
address would differ between otherwise identical runs.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def canonical(value: Any) -> Any:
    """Reduce a value to JSON-serializable form with a single fixed ordering."""
    if isinstance(value, Mapping):
        return {str(k): canonical(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((canonical(v) for v in value), key=repr)
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return repr(value)


def canonical_json(value: Any) -> str:
    """The canonical form as compact, sorted-key JSON text."""
    return json.dumps(canonical(value), sort_keys=True, separators=(",", ":"))
