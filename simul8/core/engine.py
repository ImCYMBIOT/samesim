"""
SimulationEngine — the main simulation loop.

This is the only module that drives time forward and dispatches events.
It knows about the six questions:
    1. How many agents exist?         → AgentRegistry
    2. Who is connected to whom?      → TopologyManager
    3. When does an event happen?     → Scheduler / TimeManager
    4. How do messages move?          → CommunicationLayer
    5. How does time advance?         → TimeManager
    6. How do we record everything?   → MetricsEngine

It does NOT know:
    - What agents represent
    - What algorithm they run
    - What the messages contain
    - What metrics are being collected
    - How results are stored

Event dispatch ordering within a TickEvent:
    1. _handle_tick() runs all agents:
       a. Per-agent: behavior.step() → update state → emit AgentStateChangedEvent to metrics
       b. Per-agent: route outbound messages → schedule MessageDeliveredEvents
    2. metrics.on_event(TickEvent) — fires AFTER all state changes so ConvergenceMetric
       sees the full updated picture before sampling variance.

    MessageDeliveredEvent: accumulated into pending inbox; NOT immediately dispatched
    to the behavior. Inbox is drained at the next TickEvent.

Delivery latency: chosen per delivery by the protocol (Delivery.delay),
defaulting to one tick. Under synchronous activation a message is consumed
at the first tick at or after its arrival, so the engine rounds each delay
UP to a whole number of ticks k >= 1 and stamps the MessageDeliveredEvent
with that tick's time. The default (delay=None) is k=1: waiting in the
inbox at the very next tick, whatever the tick_interval is.

Tick times are produced by repeated addition (t + dt, then + dt, ...), not
by t0 + k*dt, and the two differ in the last bits for intervals like 0.1.
The engine therefore derives a delivery's tick time from the SAME sequence
of additions as the tick schedule (_tick_time). Computing it independently
would let a message land one ulp after its tick and silently wait an extra
tick -- the same class of bug as the old hardcoded T + 1.0, which meant four
ticks of latency at tick_interval=0.25.

Ordering at a shared instant is explicit, not incidental: deliveries have
priority 0 and TickEvents priority 1, so every message due at a tick is in
the inbox before that tick runs.
"""
from __future__ import annotations

import itertools
import logging
import math
from typing import Optional

from ..domain.event import (
    AgentStateChangedEvent,
    AgentWakeEvent,
    Event,
    MessageDeliveredEvent,
    SimulationEndedEvent,
    SimulationStartedEvent,
    TickEvent,
    TimerFiredEvent,
)
from ..domain.experiment import ExperimentConfig
from ..domain.ids import AgentId, EventId, MessageId, VirtualTime
from ..domain.message import Message
from ..domain.topology import TopologyGraph
from ..ports.behavior import BehaviorPort, BehaviorResult
from .agent_registry import AgentRegistry
from .communication_layer import CommunicationLayer
from .metrics_engine import MetricsEngine
from .scheduler import Scheduler
from .time_manager import TimeManager
from .topology_manager import TopologyManager

logger = logging.getLogger(__name__)

# Same-instant ordering, lowest first:
#   deliveries -- every message due at an instant is in its inbox ...
#   wakes      -- ... before the recipient runs on the batch (event mode) ...
#   timers     -- ... before timers due at that instant, so a message can
#                 still cancel one (a heartbeat beats an election timeout) ...
#   ticks      -- ... and metrics sample only after all of it.
# Synchronous mode only uses deliveries and ticks; their relative order is
# the same as it has always been.
DELIVERY_PRIORITY = 0
WAKE_PRIORITY = 1
TIMER_PRIORITY = 2
TICK_PRIORITY = 3


class SimulationEngine:
    """Top-level orchestrator of the event-driven simulation loop.

    Purpose:
        Drive simulation forward by processing events in virtual-time order.

    Responsibilities:
        - Pop events from the Scheduler and dispatch to handlers
        - Apply behavior to each agent on every TickEvent
        - Route agent messages through the CommunicationLayer
        - Accumulate agent inboxes between ticks
        - Deliver events to MetricsEngine
        - Enforce termination conditions

    Dependencies (all injected):
        Scheduler, TimeManager, AgentRegistry, TopologyManager,
        CommunicationLayer, MetricsEngine, BehaviorPort, ExperimentConfig

    Lifecycle:
        run() is called once by ExperimentRunner.
        The engine is single-use per experiment instance.
    """

    def __init__(
        self,
        scheduler: Scheduler,
        time_manager: TimeManager,
        agent_registry: AgentRegistry,
        topology_manager: TopologyManager,
        communication_layer: CommunicationLayer,
        metrics_engine: MetricsEngine,
        behavior: BehaviorPort,
        config: ExperimentConfig,
    ) -> None:
        self._scheduler = scheduler
        self._time = time_manager
        self._agents = agent_registry
        self._topology = topology_manager
        self._comm = communication_layer
        self._metrics = metrics_engine
        self._behavior = behavior
        self._config = config

        # Monotonically increasing counters for unique IDs (no global state)
        self._event_id_counter: itertools.count[int] = itertools.count()
        self._message_id_counter: itertools.count[int] = itertools.count()

        # Pending message inboxes: accumulated between ticks, drained each tick
        self._pending_inbox: dict[AgentId, list[Message]] = {}

        # Tick schedule, by index. _tick_times[i] is the virtual time of the
        # i-th tick, built by the same repeated addition the schedule uses.
        self._tick_times: list[VirtualTime] = [VirtualTime(0.0)]
        self._tick_index: int = -1

        # Event activation bookkeeping.
        self._event_mode: bool = config.simulation.activation == "event"
        self._wake_pending: dict[AgentId, VirtualTime] = {}
        self._timers: dict[tuple[AgentId, str], EventId] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Execute the simulation from t=0 to termination.

        Termination conditions (first that triggers):
            1. The next queued event's virtual_time exceeds
               config.simulation.max_virtual_time (checked via peek, before
               dequeuing -- every event AT max_virtual_time is still
               processed; only events strictly beyond it are excluded).
            2. EventQueue is empty (no more events to process)
        """
        logger.info(
            "Simulation '%s' starting | agents=%d | max_time=%.1f | seed=%d",
            self._config.name,
            self._agents.count(),
            self._config.simulation.max_virtual_time,
            self._config.seed,
        )

        # Bootstrap: schedule the start marker and first tick
        self._scheduler.schedule(SimulationStartedEvent(
            event_id=self._next_event_id(),
            virtual_time=VirtualTime(0.0),
        ))
        if self._event_mode:
            # One bootstrap step per agent, in creation order, so every
            # behavior gets to set its first timers or send first messages.
            for agent in self._agents.iter_agents():
                self._schedule_wake(agent.agent_id, VirtualTime(0.0))
        self._scheduler.schedule(TickEvent(
            event_id=self._next_event_id(),
            virtual_time=self._tick_time(0),
            priority=TICK_PRIORITY,
        ))

        events_processed = 0
        max_virtual_time = self._config.simulation.max_virtual_time

        while self._scheduler.has_events():
            # Peek before dequeuing: stop only once the *next* event would
            # fall strictly beyond the window, so every event AT
            # max_virtual_time (including the final TickEvent and any
            # deliveries landing exactly then) is still fully drained,
            # rather than breaking after the first such event and silently
            # dropping the rest of that same-instant batch.
            next_time = self._scheduler.peek_next_time()
            if next_time is not None and next_time > max_virtual_time:
                logger.info(
                    "Termination: max_virtual_time=%.1f reached (next event at t=%.1f is beyond it)",
                    max_virtual_time,
                    float(next_time),
                )
                break

            event = self._scheduler.next_event()
            if event is None:
                break

            self._time.advance(event.virtual_time)
            self._dispatch(event)
            events_processed += 1

        # Emit the end marker synchronously (not through the queue)
        end_event = SimulationEndedEvent(
            event_id=self._next_event_id(),
            virtual_time=self._time.current_time,
        )
        self._metrics.on_event(end_event, self._time.current_time)

        logger.info(
            "Simulation '%s' complete | events_processed=%d | final_time=%.1f",
            self._config.name,
            events_processed,
            float(self._time.current_time),
        )

    # ------------------------------------------------------------------
    # Internal dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, event: Event) -> None:
        """Route an event to its handler(s), then to metrics.

        Handlers run before metrics are notified, so a TickEvent sample (and
        anything else) sees the state that event produced.
        """
        if isinstance(event, TickEvent):
            self._handle_tick(event)
        elif isinstance(event, MessageDeliveredEvent):
            self._handle_message_delivered(event)
        elif isinstance(event, AgentWakeEvent):
            self._handle_wake(event)
        elif isinstance(event, TimerFiredEvent):
            if not self._handle_timer(event):
                return  # superseded: it never happened, so metrics don't see it
        self._metrics.on_event(event, event.virtual_time)

    def _handle_tick(self, event: TickEvent) -> None:
        """Advance the tick schedule; under synchronous activation, step agents.

        Synchronous: for each agent in creation order, drain its inbox, call
        step(), and apply the result. Event activation: agents do not run on
        ticks -- the tick only paces metric sampling.

        Then schedule the next TickEvent.
        """
        self._tick_index += 1
        if self._tick_time(self._tick_index) != event.virtual_time:
            raise RuntimeError(
                f"Tick bookkeeping out of step: tick #{self._tick_index} is at "
                f"t={event.virtual_time!r}, expected {self._tick_time(self._tick_index)!r}"
            )

        if not self._event_mode:
            topology = self._topology.topology
            for agent in self._agents.iter_agents():
                result = self._behavior.step(
                    agent_id=agent.agent_id,
                    current_state=agent.state,
                    inbox=self._pending_inbox.pop(agent.agent_id, []),
                    neighbors=topology.neighbors(agent.agent_id),
                    virtual_time=event.virtual_time,
                )
                self._apply(agent.agent_id, result, event.virtual_time, topology)

        # Schedule the next tick (self-sustaining)
        next_tick_time = self._tick_time(self._tick_index + 1)
        if next_tick_time <= self._config.simulation.max_virtual_time:
            self._scheduler.schedule(TickEvent(
                event_id=self._next_event_id(),
                virtual_time=next_tick_time,
                priority=TICK_PRIORITY,
            ))

    def _handle_message_delivered(self, event: MessageDeliveredEvent) -> None:
        """Put a delivered message in the recipient's inbox.

        Synchronous: drained at the next tick. Event activation: drained by
        the recipient's wake at this same instant, scheduled here if this is
        the first message reaching it now.
        """
        self._pending_inbox.setdefault(event.recipient_id, []).append(event.message)
        self._comm.record_delivery()
        if self._event_mode and self._wake_pending.get(event.recipient_id) != event.virtual_time:
            self._schedule_wake(event.recipient_id, event.virtual_time)

    def _handle_wake(self, event: AgentWakeEvent) -> None:
        """Event activation: run step() on everything that reached the agent now."""
        agent_id = event.agent_id
        self._wake_pending.pop(agent_id, None)
        topology = self._topology.topology
        result = self._behavior.step(
            agent_id=agent_id,
            current_state=self._agents.get(agent_id).state,
            inbox=self._pending_inbox.pop(agent_id, []),
            neighbors=topology.neighbors(agent_id),
            virtual_time=event.virtual_time,
        )
        self._apply(agent_id, result, event.virtual_time, topology)

    def _handle_timer(self, event: TimerFiredEvent) -> bool:
        """Event activation: an agent's timer expired -> on_timer(tag).

        Returns False for a superseded timer (replaced or cancelled after it
        was scheduled). Replacing or cancelling also removes the old event
        from the queue, so this is a second, independent guarantee: either
        mechanism alone keeps a superseded timer from firing.
        """
        key = (event.agent_id, event.tag)
        if self._timers.get(key) != event.event_id:
            return False
        del self._timers[key]
        topology = self._topology.topology
        result = self._behavior.on_timer(
            agent_id=event.agent_id,
            current_state=self._agents.get(event.agent_id).state,
            tag=event.tag,
            neighbors=topology.neighbors(event.agent_id),
            virtual_time=event.virtual_time,
        )
        self._apply(event.agent_id, result, event.virtual_time, topology)
        return True

    def _apply(
        self,
        agent_id: AgentId,
        result: BehaviorResult,
        now: VirtualTime,
        topology: TopologyGraph,
    ) -> None:
        """Commit one behavior call: state, metrics, messages, timers."""
        self._agents.update_state(agent_id, result.next_state)

        # Notify metrics of the state change (synchronous, not via queue)
        state_event = AgentStateChangedEvent(
            event_id=self._next_event_id(),
            virtual_time=now,
            source_id=agent_id,
            agent_id=agent_id,
            state_snapshot=result.next_state.to_dict(),
        )
        self._metrics.on_event(state_event, now)

        for msg in result.outbound_messages:
            for delivery in self._comm.route(msg, agent_id, topology):
                delivery_time = self._arrival_time(delivery.delay, now)
                if delivery_time is None:
                    continue  # lands after the run ends; never observable
                self._scheduler.schedule(MessageDeliveredEvent(
                    event_id=self._next_event_id(),
                    virtual_time=delivery_time,
                    source_id=agent_id,
                    recipient_id=delivery.recipient_id,
                    message=delivery.message,
                    priority=DELIVERY_PRIORITY,
                ))

        if result.set_timers or result.cancel_timers:
            self._apply_timers(agent_id, result, now)

    def _apply_timers(self, agent_id: AgentId, result: BehaviorResult, now: VirtualTime) -> None:
        behavior_name = type(self._behavior).__name__
        if not self._event_mode:
            raise ValueError(
                f"{behavior_name} set or cancelled timers under synchronous activation. "
                f"Timers exist only with simulation.activation='event'."
            )
        for tag in sorted(result.cancel_timers):
            self._cancel_timer(agent_id, tag)
        for timer in result.set_timers:
            if not isinstance(timer.tag, str):
                raise ValueError(f"{behavior_name} set a timer with non-string tag {timer.tag!r}")
            fire_at = self._after(now, timer.delay, f"{behavior_name} timer {timer.tag!r}")
            self._cancel_timer(agent_id, timer.tag)  # at most one per (agent, tag)
            if fire_at > self._config.simulation.max_virtual_time:
                continue  # would fire after the run ends
            event_id = self._next_event_id()
            self._scheduler.schedule(TimerFiredEvent(
                event_id=event_id,
                virtual_time=fire_at,
                source_id=agent_id,
                agent_id=agent_id,
                tag=timer.tag,
                priority=TIMER_PRIORITY,
            ))
            self._timers[(agent_id, timer.tag)] = event_id

    def _cancel_timer(self, agent_id: AgentId, tag: str) -> None:
        event_id = self._timers.pop((agent_id, tag), None)
        if event_id is not None:
            self._scheduler.cancel(event_id)

    def _schedule_wake(self, agent_id: AgentId, at: VirtualTime) -> None:
        self._wake_pending[agent_id] = at
        self._scheduler.schedule(AgentWakeEvent(
            event_id=self._next_event_id(),
            virtual_time=at,
            source_id=agent_id,
            agent_id=agent_id,
            priority=WAKE_PRIORITY,
        ))

    def _arrival_time(self, delay: float | None, now: VirtualTime) -> VirtualTime | None:
        """When a message sent now is delivered, or None if after the run.

        Synchronous: rounded up to the consuming tick. Event activation:
        exact -- now + delay, with None meaning one tick_interval.
        """
        if not self._event_mode:
            return self._delivery_tick_time(delay)
        d = self._config.simulation.tick_interval if delay is None else delay
        arrival = self._after(now, d, f"{self._comm.protocol_name} delivery")
        return arrival if arrival <= self._config.simulation.max_virtual_time else None

    @staticmethod
    def _after(now: VirtualTime, delay: float, what: str) -> VirtualTime:
        """now + delay, refusing delays that don't move time forward.

        A delay can pass the > 0 check yet vanish in the addition (1e-20
        added to 100.0 is 100.0). That would make an effect simultaneous
        with its cause -- exactly what strictly positive delays exist to
        prevent -- so it fails loudly instead.
        """
        if not (isinstance(delay, (int, float)) and not isinstance(delay, bool)
                and math.isfinite(delay) and delay > 0):
            raise ValueError(f"{what}: delay must be a finite number > 0, got {delay!r}")
        later = VirtualTime(now + delay)
        if later <= now:
            raise ValueError(
                f"{what}: delay {delay!r} is too small to advance virtual time "
                f"at t={now!r} (float resolution); use a larger delay."
            )
        return later

    # ------------------------------------------------------------------
    # Tick arithmetic
    # ------------------------------------------------------------------

    def _tick_time(self, index: int) -> VirtualTime:
        """Virtual time of the index-th tick, by the schedule's own additions."""
        dt = self._config.simulation.tick_interval
        while len(self._tick_times) <= index:
            self._tick_times.append(VirtualTime(self._tick_times[-1] + dt))
        return self._tick_times[index]

    def _delivery_tick_time(self, delay: float | None) -> VirtualTime | None:
        """The tick at which a message sent now with this delay is consumed.

        Returns None when that tick falls after max_virtual_time: such a
        message could never be observed, so it is not scheduled at all.
        """
        dt = self._config.simulation.tick_interval
        if delay is None:
            ticks = 1
        else:
            # Round up to whole ticks. The tolerance absorbs float noise in
            # delays meant to be exact multiples (3 * 0.1 / 0.1 is
            # 3.0000000000000004, which must mean 3 ticks, not 4).
            ticks = max(1, math.ceil(delay / dt - 1e-9))

        remaining = (self._config.simulation.max_virtual_time - self._tick_time(self._tick_index)) / dt
        if ticks > remaining + 1:
            return None  # also keeps _tick_time() from extending without bound
        time = self._tick_time(self._tick_index + ticks)
        return time if time <= self._config.simulation.max_virtual_time else None

    # ------------------------------------------------------------------
    # ID generation (engine-private, no global state)
    # ------------------------------------------------------------------

    def _next_event_id(self) -> EventId:
        return EventId(next(self._event_id_counter))

    def _next_message_id(self) -> MessageId:
        return MessageId(next(self._message_id_counter))
