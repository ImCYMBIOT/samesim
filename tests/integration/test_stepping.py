"""Stepping a run (samesim.session) must be the same run as samesim.run.

Every shipped example is discovered and driven three ways -- run(), one
event at a time, and in chunks of virtual time -- and all three must end on
the same digest. A stepping mode that diverged for any behavior, activation
mode, protocol or churn plugin would fail here without a test naming it.
"""
from __future__ import annotations

import pytest

import samesim
from samesim.app import catalog
from samesim.domain.event import Event, MessageSentEvent, SimulationEndedEvent
from samesim.domain.metric import MetricSeries
from samesim.ports.metric_collector import MetricCollectorPort

EXAMPLES = [e.name for e in catalog.list_examples()]
SHORT = {"simulation.max_virtual_time": 12}


def _short(name: str) -> dict:
    """A shortened run: long enough for traffic, short enough for a test."""
    horizon = samesim.validate(name).simulation.max_virtual_time
    return {} if horizon <= 60 else {"simulation.max_virtual_time": horizon / 20}


@pytest.mark.parametrize("name", EXAMPLES)
def test_stepping_event_by_event_is_the_same_run(name):
    whole = samesim.run(name, overrides=_short(name))
    session = samesim.session(name, overrides=_short(name))
    times = []
    while (event := session.step()) is not None:
        times.append(event.virtual_time)
    stepped = session.finish()
    assert whole.digest is not None and stepped.digest == whole.digest
    assert times == sorted(times), "events came out of virtual-time order"
    assert session.events_processed == len(times)


@pytest.mark.parametrize("name", EXAMPLES)
def test_running_in_chunks_of_time_is_the_same_run(name):
    whole = samesim.run(name, overrides=_short(name))
    session = samesim.session(name, overrides=_short(name))
    horizon = session.config.simulation.max_virtual_time
    for k in range(1, 8):
        session.run_until(horizon * k / 7)
    session.run()
    assert session.finish().digest == whole.digest


def test_run_until_stops_after_everything_due_and_before_anything_later():
    session = samesim.session("gossip_ring", overrides=SHORT)
    dispatched = session.run_until(3.0)
    assert dispatched > 0 and session.time == 3.0
    assert session.next_event_time > 3.0
    assert session.run_until(3.0) == 0, "a second call to the same time found more to do"


def test_a_session_starts_at_zero_with_nothing_dispatched():
    session = samesim.session("gossip_ring", overrides=SHORT)
    assert (session.time, session.events_processed, session.finished) == (0.0, 0, False)
    assert session.next_event_time == 0.0


def test_step_returns_none_at_the_end_and_keeps_returning_it():
    session = samesim.session("gossip_ring", overrides=SHORT)
    session.run()
    assert session.step() is None and session.step() is None
    assert session.next_event_time is None
    assert session.time == SHORT["simulation.max_virtual_time"]


def test_finishing_early_ends_the_run_where_it_stands():
    session = samesim.session("gossip_ring", overrides=SHORT)
    session.run_until(4.0)
    result = session.finish()
    assert session.finished
    assert result.series["trace_digest"].records[-1].virtual_time == 4.0
    assert result.digest != samesim.run("gossip_ring", overrides=SHORT).digest
    assert session.finish() is result, "finish() twice must not end the run twice"
    with pytest.raises(RuntimeError, match="after finish"):
        session.step()
    with pytest.raises(RuntimeError, match="after finish"):
        session.run_until(9.0)


def test_metrics_can_be_read_while_the_run_is_paused():
    session = samesim.session("gossip_ring", overrides=SHORT)
    session.run_until(2.0)
    early = len(session.series["convergence_variance"].records)
    session.run_until(6.0)
    assert 0 < early < len(session.series["convergence_variance"].records)


def test_finish_writes_files_only_when_given_a_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    session = samesim.session("gossip_ring", overrides=SHORT)
    session.run()
    assert session.finish().output_files == [] and not list(tmp_path.iterdir())
    session = samesim.session("gossip_ring", overrides=SHORT)
    session.run()
    assert session.finish(tmp_path / "out").output_files
    assert (tmp_path / "out" / "summary.json").exists()


def test_an_engine_cannot_be_started_twice():
    session = samesim.session("gossip_ring", overrides=SHORT)
    session.step()
    with pytest.raises(RuntimeError, match="twice"):
        session._prepared.engine.start()


# ------------------------------------------------------- MessageSentEvent

class _SentProbe(MetricCollectorPort):
    """Subscribes to MessageSentEvent, so the engine starts emitting it."""

    seen: list[MessageSentEvent] = []

    def on_setup(self, topology, initial_states) -> None:
        type(self).seen = []

    def subscribed_events(self) -> frozenset[type[Event]]:
        return frozenset({MessageSentEvent, SimulationEndedEvent})

    def on_event(self, event, virtual_time) -> None:
        if isinstance(event, MessageSentEvent):
            type(self).seen.append(event)

    def get_series(self) -> MetricSeries:
        return MetricSeries(name="sent_probe")

    def reset(self) -> None:
        type(self).seen = []


PROBE = f"{__name__}._SentProbe"


@pytest.mark.parametrize("name", EXAMPLES)
def test_observing_sends_does_not_change_the_run(name):
    """MessageSentEvent takes event ids of its own. Nothing a run does may
    depend on that: the digest with a subscriber equals the digest without."""
    plain = samesim.run(name, overrides=_short(name))
    metrics = samesim.app.api.load_raw(name)["plugins"]["metrics"] + [PROBE]
    watched = samesim.run(name, overrides={**_short(name), "plugins.metrics": metrics})
    assert watched.digest == plain.digest
    for event in _SentProbe.seen:
        assert event.arrival_time is None or event.arrival_time > event.virtual_time


def test_no_send_event_is_built_when_nobody_subscribes():
    session = samesim.session("gossip_ring", overrides=SHORT)
    kinds = set()
    while (event := session.step()) is not None:
        kinds.add(type(event))
    assert not session._prepared.engine._emit_sent
    assert MessageSentEvent not in kinds
