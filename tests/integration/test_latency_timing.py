"""
Engine-level latency semantics, observed from inside a behavior.

Checks what an agent actually SEES, not just when events are stamped:

    - a delay is rounded UP to whole ticks; the default is exactly one tick
    - rounding is done on the tick schedule's own float arithmetic, so a
      delay that is an exact multiple of a fractional tick_interval arrives
      on the intended tick even after many ticks of float accumulation
    - messages can overtake each other
    - a message due after the run ends is silently never delivered
    - an illegal delay fails the run loudly, naming the protocol
    - end to end, the tick lag of LatencyProtocol's deliveries follows the
      configured distribution, rounded up to ticks
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from simul8.app.experiment_runner import ExperimentRunner
from tests.integration.latency_probes import SendScheduleBehavior

PROBE_BEHAVIOR = "tests.integration.latency_probes.SendScheduleBehavior"
PROBE_PROTOCOL = "tests.integration.latency_probes.DelayBySendStepProtocol"
LATENCY_PROTOCOL = "simul8.plugins.communication.latency.LatencyProtocol"


def _run(tmp_path: Path, *, dt: float, max_time: float, send_steps, protocol: str,
         protocol_config: dict, per_step: int = 1, seed: int = 1) -> list[dict]:
    SendScheduleBehavior.log = []
    cfg = {
        "schema_version": "1.0",
        "experiment": {"name": "latency", "seed": seed},
        "simulation": {"num_agents": 2, "max_virtual_time": max_time, "tick_interval": dt},
        "plugins": {
            "behavior": PROBE_BEHAVIOR,
            "communication": protocol,
            "topology": "simul8.plugins.topologies.ring.RingTopology",
            "metrics": [],
            "persistence": [],
        },
        "plugin_configs": {
            "SendScheduleBehavior": {"send_steps": list(send_steps), "per_step": per_step},
            protocol.rsplit(".", 1)[-1]: protocol_config,
        },
    }
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg))
    ExperimentRunner().run(path, output_dir=tmp_path / "out")
    return list(SendScheduleBehavior.log)


@pytest.mark.parametrize("delay,expected_ticks", [
    (None, 1),                  # default latency: the very next tick
    (0.001, 1),                 # anything up to one tick rounds up to one
    (1.0, 1),
    (1.000001, 2),              # just over a tick is a second tick
    (2.5, 3),
    (3.0, 3),
    (3 * 0.1 / 0.1, 3),         # 3.0000000000000004: float noise, still 3
])
def test_delay_rounds_up_to_whole_ticks(tmp_path, delay, expected_ticks):
    log = _run(tmp_path, dt=1.0, max_time=10, send_steps=[2],
               protocol=PROBE_PROTOCOL, protocol_config={"delays": {2: delay}})
    assert [(e["sent_step"], e["seen_step"]) for e in log] == [(2, 2 + expected_ticks)]


def test_fractional_tick_interval_survives_float_accumulation(tmp_path):
    """dt=0.1 after 70 ticks: t is 7.000000000000001-ish, not 7.0. A 0.3 delay
    must still mean exactly 3 ticks -- computed from the schedule's own
    additions, not from now + k*dt, which can miss its tick by one ulp and
    silently wait an extra tick."""
    steps = list(range(0, 90, 7))
    log = _run(tmp_path, dt=0.1, max_time=10, send_steps=steps,
               protocol=PROBE_PROTOCOL, protocol_config={"delays": {s: 0.3 for s in steps}})
    lags = {e["sent_step"]: e["seen_step"] - e["sent_step"] for e in log}
    assert lags == {s: 3 for s in steps}, lags


def test_messages_can_overtake_each_other(tmp_path):
    log = _run(tmp_path, dt=1.0, max_time=10, send_steps=[0, 1],
               protocol=PROBE_PROTOCOL, protocol_config={"delays": {0: 4.0, 1: 1.0}})
    assert [(e["sent_step"], e["seen_step"]) for e in log] == [(1, 2), (0, 4)]


def test_message_due_after_the_run_is_never_delivered(tmp_path):
    log = _run(tmp_path, dt=1.0, max_time=5, send_steps=[3],
               protocol=PROBE_PROTOCOL, protocol_config={"delays": {3: 1e300}})
    assert log == []


@pytest.mark.parametrize("bad", [0, 0.0, -1.0, float("nan"), float("inf")])
def test_illegal_delay_fails_loudly_naming_the_protocol(tmp_path, bad):
    with pytest.raises(ValueError, match="DelayBySendStepProtocol"):
        _run(tmp_path, dt=1.0, max_time=5, send_steps=[0],
             protocol=PROBE_PROTOCOL, protocol_config={"delays": {0: bad}})


def test_end_to_end_tick_lag_follows_the_configured_distribution(tmp_path):
    """Exponential(mean=2 time units) at dt=1 means a lag of k ticks with
    probability F(k) - F(k-1), F(x) = 1 - exp(-x/2). Chi-square over the
    observed lags of 20,000 messages sent through the real engine."""
    mean, n = 2.0, 20_000
    log = _run(tmp_path, dt=1.0, max_time=60, send_steps=[0], per_step=n,
               protocol=LATENCY_PROTOCOL,
               protocol_config={"distribution": "exponential", "mean": mean})
    lags = [e["seen_step"] for e in log]  # sent at step 0

    F = lambda x: 1 - math.exp(-x / mean)
    bins = list(range(1, 11))  # k = 1..10, then a tail bin
    observed = [sum(1 for l in lags if l == k) for k in bins] + [sum(1 for l in lags if l > 10)]
    probs = [F(k) - F(k - 1) for k in bins] + [1 - F(10)]
    # Messages due after t=60 are never delivered; P is ~1e-13, i.e. none.
    assert len(lags) == n
    chi2 = sum((o - n * p) ** 2 / (n * p) for o, p in zip(observed, probs))
    # 10 degrees of freedom: the 0.999 quantile is 29.59.
    assert chi2 < 29.59, f"chi2={chi2:.1f}; observed={observed}"
