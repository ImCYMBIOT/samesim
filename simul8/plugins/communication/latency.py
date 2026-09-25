"""
LatencyProtocol — a channel with random per-message delay, and optional loss.

Every delivery gets its own delay drawn from a configurable distribution,
so messages can arrive out of order and stragglers exist. Recipient
selection follows the message's addressing mode exactly like every other
protocol (see Message.broadcast): an addressed message goes to its
recipient; a broadcast reaches each neighbor independently, each copy with
its own delay and its own loss draw.

Configuration (plugin_configs.LatencyProtocol):
    distribution:     "constant" | "uniform" | "exponential" | "lognormal"
                      (default "constant")
    delay:            constant only -- the delay, in virtual time
                      (default: omitted, meaning the engine's one tick)
    low, high:        uniform only -- bounds, 0 < low <= high
    mean:             exponential only -- mean delay, > 0
    mu, sigma:        lognormal only -- parameters of the underlying normal,
                      as in random.lognormvariate (median delay = e^mu)
    loss_probability: probability a delivery is dropped (default 0.0)

Delays are in virtual-time units, not ticks. Under synchronous activation
the engine rounds each one UP to whole ticks (a 2.5-tick delay arrives at
the third tick after sending), so the distribution is exact in the
protocol and quantized in the run.

Determinism: exponential and lognormal delays use simul8.domain.portable_math,
not random.expovariate/lognormvariate, whose results depend on the
platform's C math library. All randomness comes from the protocol's seeded RNG, drawn in
delivery order -- recipients in sorted order for broadcasts; for each
delivery, first the loss draw (only when loss_probability > 0), then the
delay draw (only when the delay is random).

Invalid parameters raise ValueError in initialize(), i.e. when the
experiment is set up -- never partway through a run.
"""
from __future__ import annotations

import math
import random
from typing import Any, Callable

from ...domain import portable_math
from ...domain.delivery import Delivery
from ...domain.ids import AgentId, MessageId
from ...domain.message import Message
from ...domain.topology import TopologyGraph
from ...ports.communication import CommunicationProtocolPort

DISTRIBUTIONS = ("constant", "uniform", "exponential", "lognormal")


class LatencyProtocol(CommunicationProtocolPort):
    """Per-delivery random latency with optional loss."""

    def __init__(self) -> None:
        self._rng: random.Random | None = None
        self._loss_prob: float = 0.0
        self._draw: Callable[[random.Random], float | None] = lambda rng: None
        self._msg_counter: int = 0

    def initialize(
        self,
        topology: TopologyGraph,
        config: dict[str, Any],
        rng: random.Random,
    ) -> None:
        self._rng = rng
        self._loss_prob = _probability(config.get("loss_probability", 0.0))
        self._draw = _delay_sampler(config)

    def route(
        self,
        message: Message,
        sender_id: AgentId,
        topology: TopologyGraph,
    ) -> list[Delivery]:
        rng = self._rng
        if rng is None:
            raise RuntimeError("LatencyProtocol.route() called before initialize()")

        if not message.broadcast:
            return self._deliver(rng, message.recipient_id, message)

        deliveries: list[Delivery] = []
        for neighbor_id in sorted(topology.neighbors(sender_id)):
            self._msg_counter += 1
            copy = Message(
                message_id=MessageId(self._msg_counter),
                sender_id=sender_id,
                recipient_id=neighbor_id,
                payload=message.payload,
            )
            deliveries.extend(self._deliver(rng, neighbor_id, copy))
        return deliveries

    def _deliver(self, rng: random.Random, recipient_id: AgentId, message: Message) -> list[Delivery]:
        if self._loss_prob > 0.0 and rng.random() < self._loss_prob:
            return []
        return [Delivery(recipient_id=recipient_id, message=message, delay=self._draw(rng))]


def _probability(value: Any) -> float:
    p = float(value)
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"LatencyProtocol: loss_probability must be in [0, 1], got {value!r}")
    return p


def _positive(config: dict[str, Any], key: str, *, allow_zero: bool = False) -> float:
    if key not in config:
        raise ValueError(f"LatencyProtocol: distribution needs '{key}'")
    v = float(config[key])
    if not math.isfinite(v) or v < 0 or (v == 0 and not allow_zero):
        bound = ">= 0" if allow_zero else "> 0"
        raise ValueError(f"LatencyProtocol: '{key}' must be finite and {bound}, got {config[key]!r}")
    return v


def _delay_sampler(config: dict[str, Any]) -> Callable[[random.Random], float | None]:
    kind = config.get("distribution", "constant")
    if kind not in DISTRIBUTIONS:
        raise ValueError(
            f"LatencyProtocol: unknown distribution {kind!r}; expected one of {DISTRIBUTIONS}"
        )

    if kind == "constant":
        if "delay" not in config:
            return lambda rng: None  # the engine's default: one tick
        d = _positive(config, "delay")
        return lambda rng: d

    if kind == "uniform":
        low, high = _positive(config, "low"), _positive(config, "high")
        if high < low:
            raise ValueError(f"LatencyProtocol: uniform needs low <= high, got {low} > {high}")
        return lambda rng: rng.uniform(low, high)

    if kind == "exponential":
        mean = _positive(config, "mean")

        def exponential(rng: random.Random) -> float:
            # Returns (negative) zero when random() gives 0.0 (p = 2^-53).
            # Zero is not a legal delay, so redraw -- still deterministic.
            while True:
                d = portable_math.expovariate(rng, 1.0 / mean)
                if d > 0.0:
                    return d
        return exponential

    # lognormal
    if "mu" not in config:
        raise ValueError("LatencyProtocol: distribution needs 'mu'")
    mu = float(config["mu"])
    if not math.isfinite(mu):
        raise ValueError(f"LatencyProtocol: 'mu' must be finite, got {config['mu']!r}")
    sigma = _positive(config, "sigma", allow_zero=True)
    return lambda rng: portable_math.lognormvariate(rng, mu, sigma)
