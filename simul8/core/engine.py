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
    Event,
    MessageDeliveredEvent,
    SimulationEndedEvent,
    SimulationStartedEvent,
    TickEvent,
)
from ..domain.experiment import ExperimentConfig
from ..domain.ids import AgentId, EventId, MessageId, VirtualTime
from ..domain.message import Message
from ..ports.behavior import BehaviorPort
from .agent_registry import AgentRegistry
from .communication_layer import CommunicationLayer
from .metrics_engine import MetricsEngine
from .scheduler import Scheduler
from .time_manager import TimeManager
from .topology_manager import TopologyManager

logger = logging.getLogger(__name__)

# Same-instant ordering: every delivery due at a tick is dispatched (and so
# in the inbox) before the tick itself runs.
DELIVERY_PRIORITY = 0
TICK_PRIORITY = 1


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
        """Route an event to its handler(s).

        For TickEvent: process agents first, then notify metrics.
        This ensures ConvergenceMetric (and similar) sees fresh state
        values when it samples at the TickEvent boundary.

        For all other events: notify metrics first (standard order).
        """
        if isinstance(event, TickEvent):
            self._handle_tick(event)
            # Metrics AFTER: converge metric samples here with up-to-date values
            self._metrics.on_event(event, event.virtual_time)
        elif isinstance(event, MessageDeliveredEvent):
            self._handle_message_delivered(event)
            self._metrics.on_event(event, event.virtual_time)
        else:
            # SimulationStartedEvent and future event types
            self._metrics.on_event(event, event.virtual_time)

    def _handle_tick(self, event: TickEvent) -> None:
        """Process one simulation tick for all agents.

        For each agent (in creation order, for determinism):
            1. Drain the pending inbox accumulated since the last tick
            2. Call behavior.step() → BehaviorResult
            3. Update agent state in the registry
            4. Emit AgentStateChangedEvent to metrics (synchronous)
            5. Route outbound messages → schedule MessageDeliveredEvents

        Then schedule the next TickEvent.
        """
        topology = self._topology.topology
        self._tick_index += 1
        if self._tick_time(self._tick_index) != event.virtual_time:
            raise RuntimeError(
                f"Tick bookkeeping out of step: tick #{self._tick_index} is at "
                f"t={event.virtual_time!r}, expected {self._tick_time(self._tick_index)!r}"
            )

        for agent in self._agents.iter_agents():
            inbox = self._pending_inbox.pop(agent.agent_id, [])
            neighbors = topology.neighbors(agent.agent_id)

            result = self._behavior.step(
                agent_id=agent.agent_id,
                current_state=agent.state,
                inbox=inbox,
                neighbors=neighbors,
                virtual_time=event.virtual_time,
            )

            # Persist the new state
            self._agents.update_state(agent.agent_id, result.next_state)

            # Notify metrics of the state change (synchronous, not via queue)
            state_event = AgentStateChangedEvent(
                event_id=self._next_event_id(),
                virtual_time=event.virtual_time,
                source_id=agent.agent_id,
                agent_id=agent.agent_id,
                state_snapshot=result.next_state.to_dict(),
            )
            self._metrics.on_event(state_event, event.virtual_time)

            # Route and schedule outbound messages
            for msg in result.outbound_messages:
                for delivery in self._comm.route(msg, agent.agent_id, topology):
                    delivery_time = self._delivery_tick_time(delivery.delay)
                    if delivery_time is None:
                        continue  # lands after the run ends; never observable
                    self._scheduler.schedule(MessageDeliveredEvent(
                        event_id=self._next_event_id(),
                        virtual_time=delivery_time,
                        source_id=agent.agent_id,
                        recipient_id=delivery.recipient_id,
                        message=delivery.message,
                        priority=DELIVERY_PRIORITY,
                    ))

        # Schedule the next tick (self-sustaining)
        next_tick_time = self._tick_time(self._tick_index + 1)
        if next_tick_time <= self._config.simulation.max_virtual_time:
            self._scheduler.schedule(TickEvent(
                event_id=self._next_event_id(),
                virtual_time=next_tick_time,
                priority=TICK_PRIORITY,
            ))

    def _handle_message_delivered(self, event: MessageDeliveredEvent) -> None:
        """Accumulate a delivered message into the recipient's pending inbox.

        The inbox is drained and delivered to the behavior on the next tick.
        """
        self._pending_inbox.setdefault(event.recipient_id, []).append(event.message)
        self._comm.record_delivery()

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
