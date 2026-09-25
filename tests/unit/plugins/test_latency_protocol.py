"""LatencyProtocol: delays follow the configured distribution; loss, addressing,
determinism and config validation behave as documented."""
from __future__ import annotations

import math
import random

import pytest

from simul8.domain.ids import AgentId, MessageId
from simul8.domain.message import Message
from simul8.domain.topology import TopologyGraph
from simul8.plugins.communication.latency import LatencyProtocol

N = 20_000
A, B, C, D = (AgentId(i) for i in range(4))
STAR = TopologyGraph(
    agent_ids=frozenset({A, B, C, D}),
    adjacency={A: frozenset({B, C, D}), B: frozenset({A}), C: frozenset({A}), D: frozenset({A})},
)


def _protocol(config, seed=7) -> LatencyProtocol:
    p = LatencyProtocol()
    p.initialize(STAR, config, random.Random(seed))
    return p


def _addressed(i=1) -> Message:
    return Message(message_id=MessageId(i), sender_id=A, recipient_id=B, payload={})


def _delays(config, n=N) -> list[float]:
    p = _protocol(config)
    return [d.delay for i in range(n) for d in p.route(_addressed(i), A, STAR)]


def _ks(samples: list[float], cdf) -> float:
    xs = sorted(samples)
    n = len(xs)
    return max(max(cdf(x) - i / n, (i + 1) / n - cdf(x)) for i, x in enumerate(xs))


KS_CRITICAL = 1.95 / math.sqrt(N)  # alpha = 0.001


@pytest.mark.parametrize("config,cdf", [
    ({"distribution": "uniform", "low": 0.5, "high": 3.0},
     lambda x: (x - 0.5) / 2.5),
    ({"distribution": "exponential", "mean": 2.0},
     lambda x: 1 - math.exp(-x / 2.0)),
    ({"distribution": "lognormal", "mu": 0.3, "sigma": 0.6},
     lambda x: 0.5 * (1 + math.erf((math.log(x) - 0.3) / (0.6 * math.sqrt(2))))),
], ids=["uniform", "exponential", "lognormal"])
def test_delays_follow_the_configured_distribution(config, cdf):
    delays = _delays(config)
    assert all(d is not None and d > 0 for d in delays)
    stat = _ks(delays, cdf)
    assert stat < KS_CRITICAL, f"KS statistic {stat:.4f} >= {KS_CRITICAL:.4f}"


def test_constant_delay_is_exact_and_default_is_one_tick():
    assert set(_delays({"distribution": "constant", "delay": 2.5}, n=100)) == {2.5}
    assert set(_delays({}, n=100)) == {None}


def test_loss_rate_matches_configuration():
    p, n = 0.3, N
    delivered = len(_delays({"loss_probability": p}, n=n))
    z = (n - delivered - n * p) / math.sqrt(n * p * (1 - p))
    assert abs(z) < 4, f"dropped {n - delivered} of {n}, z={z:.2f}"


def test_honours_both_addressing_modes():
    p = _protocol({"distribution": "exponential", "mean": 1.0})
    addressed = p.route(_addressed(), A, STAR)
    assert [d.recipient_id for d in addressed] == [B]

    bcast = Message(message_id=MessageId(9), sender_id=A, recipient_id=A, payload={}, broadcast=True)
    fanned = p.route(bcast, A, STAR)
    assert [d.recipient_id for d in fanned] == [B, C, D]
    assert len({d.delay for d in fanned}) == 3, "each copy draws its own delay"


def test_same_seed_same_delays_different_seed_different_delays():
    cfg = {"distribution": "exponential", "mean": 1.0, "loss_probability": 0.2}

    def one_run(seed):
        p = _protocol(cfg, seed)
        return [(d.recipient_id, d.delay) for i in range(500) for d in p.route(_addressed(i), A, STAR)]
    assert one_run(1) == one_run(1)
    assert one_run(1) != one_run(2)


def test_no_rng_draws_when_nothing_is_random():
    """Documented draw order: constant delay with no loss consumes no
    randomness, so adding it to an experiment cannot perturb anything else
    that shares the RNG."""
    rng = random.Random(5)
    p = LatencyProtocol()
    p.initialize(STAR, {"distribution": "constant", "delay": 2.0}, rng)
    before = rng.getstate()
    for i in range(100):
        p.route(_addressed(i), A, STAR)
    assert rng.getstate() == before


@pytest.mark.parametrize("config,match", [
    ({"distribution": "gamma"}, "unknown distribution"),
    ({"distribution": "constant", "delay": 0}, "'delay' must be finite and > 0"),
    ({"distribution": "constant", "delay": -1}, "'delay' must be finite and > 0"),
    ({"distribution": "uniform", "low": 0, "high": 1}, "'low' must be finite and > 0"),
    ({"distribution": "uniform", "low": 2, "high": 1}, "low <= high"),
    ({"distribution": "uniform", "high": 1}, "needs 'low'"),
    ({"distribution": "exponential"}, "needs 'mean'"),
    ({"distribution": "exponential", "mean": float("inf")}, "'mean' must be finite"),
    ({"distribution": "lognormal", "sigma": 1}, "needs 'mu'"),
    ({"distribution": "lognormal", "mu": 0, "sigma": -1}, "'sigma' must be finite and >= 0"),
    ({"loss_probability": 1.5}, r"loss_probability must be in \[0, 1\]"),
])
def test_invalid_config_fails_at_setup(config, match):
    with pytest.raises(ValueError, match=match):
        _protocol(config)
