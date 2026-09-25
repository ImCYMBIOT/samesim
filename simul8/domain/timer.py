"""
Timer — a request, made by a behavior, to be called back after a delay.

Only meaningful under event activation. An agent has at most one pending
timer per tag: setting a tag that is already pending replaces it. That is
what makes "reset the election timeout on every heartbeat" a one-liner --
set the tag again.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Timer:
    """Call BehaviorPort.on_timer(tag) after `delay` virtual time units.

    Attributes:
        tag:   Names the timer; one pending timer per (agent, tag).
        delay: Finite and strictly positive, like a message delay.
    """

    tag: str
    delay: float
