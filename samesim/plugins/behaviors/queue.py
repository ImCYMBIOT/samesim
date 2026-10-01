"""
QueueBehavior — a single-server FIFO queue fed by Poisson sources (M/M/1).

One agent is the server; every other agent adjacent to it is a source.
Sources generate customers at the times of a Poisson process and send each
one to the server as a message. The server holds them in a FIFO queue and
serves one at a time, each for an exponential service time. Customers
arriving from several sources still form a Poisson stream (superposition),
so with total arrival rate lambda (the per-source rate times the number of
sources) and service rate mu this is the M/M/1 queue, with closed forms
(rho = lambda / mu < 1):

    mean wait in queue       Wq = rho / (mu - lambda)
    mean time in system      W  = 1 / (mu - lambda)
    mean number in system    L  = rho / (1 - rho)

A constant message latency (LatencyProtocol, distribution: constant) shifts
every arrival by the same amount, which leaves the arrival process Poisson,
so the closed forms still hold. Random latency would reorder arrivals and
make it a different queue.

Requires simulation.activation: event.

Every neighbor of the server is a source; an agent that isn't adjacent to
the server generates nothing. With two agents (one server, one source) the
source's rate is lambda.

Crash recovery (with churn): a crashed server keeps its queue but loses the
customer in service's departure timer; on recovery it restarts that
service. For exponential service times this is exact (memorylessness).
Customers sent to a crashed server are lost, as the engine reports.

Configuration (plugin_configs.QueueBehavior):
    arrival_rate:  customer arrival rate PER SOURCE (default 0.8)
    service_rate:  service rate, mu (default 1.0)
    server:        id of the server agent (default 0)

State:
    server:  {"role": "server", "queue": [arrival times, FIFO],
              "in_service_since": time | None, "served": int,
              "last_wait": float | None, "last_sojourn": float | None}
    source:  {"role": "source", "sent": int}

QueueMetric reads the server's state to record waits and the number in
system over time.
"""
from __future__ import annotations

import random
from typing import Any

from ...domain import portable_math
from ...domain.ids import AgentId, MessageId, VirtualTime
from ...domain.message import Message
from ...domain.state import AgentState
from ...domain.timer import Timer
from ...ports.behavior import BehaviorPort, BehaviorResult

ARRIVAL = "arrival"
DEPARTURE = "departure"


class QueueBehavior(BehaviorPort):
    """A single-server FIFO queue with Poisson arrivals and exponential service."""

    activation_modes = frozenset({"event"})

    def __init__(self) -> None:
        self._lambda: float = 0.8
        self._mu: float = 1.0
        self._server: AgentId = AgentId(0)
        self._rngs: dict[AgentId, random.Random] = {}
        self._msg_counter: int = 0

    def initialize(self, agent_id: AgentId, config: dict[str, Any], rng: random.Random) -> AgentState:
        self._lambda = float(config.get("arrival_rate", 0.8))
        self._mu = float(config.get("service_rate", 1.0))
        self._server = AgentId(int(config.get("server", 0)))
        if not (self._lambda > 0 and self._mu > 0):
            raise ValueError(
                f"QueueBehavior: arrival_rate and service_rate must be > 0, "
                f"got {self._lambda} and {self._mu}"
            )
        self._rngs[agent_id] = rng
        if agent_id == self._server:
            return AgentState(data={"role": "server", "queue": [], "in_service_since": None,
                                    "served": 0, "last_wait": None, "last_sojourn": None})
        return AgentState(data={"role": "source", "sent": 0})

    # ------------------------------------------------------------------ steps

    def step(self, agent_id, current_state, inbox, neighbors, virtual_time) -> BehaviorResult:
        if current_state.get("role") == "source":
            # Sources only ever run at bootstrap (they receive nothing).
            return BehaviorResult(next_state=current_state,
                                  set_timers=self._arrival_timer(agent_id, neighbors))
        if not inbox:  # server bootstrap: nothing to do until customers arrive
            return BehaviorResult(next_state=current_state)
        queue = list(current_state.get("queue")) + [float(virtual_time)] * len(inbox)
        state = current_state.with_value("queue", queue)
        if current_state.get("in_service_since") is None:
            return self._start_service(agent_id, state, virtual_time)
        return BehaviorResult(next_state=state)

    def on_timer(self, agent_id, current_state, tag, neighbors, virtual_time) -> BehaviorResult:
        if tag == ARRIVAL:
            out = []
            if self._server in neighbors:
                self._msg_counter += 1
                out.append(Message(message_id=MessageId(self._msg_counter), sender_id=agent_id,
                                   recipient_id=self._server, payload={"customer": True}))
            state = current_state.with_value("sent", current_state.get("sent") + len(out))
            return BehaviorResult(next_state=state, outbound_messages=out,
                                  set_timers=self._arrival_timer(agent_id, neighbors))
        # DEPARTURE: the customer at the head of the queue leaves.
        queue = list(current_state.get("queue"))
        arrived = queue.pop(0)
        state = (current_state
                 .with_value("queue", queue)
                 .with_value("served", current_state.get("served") + 1)
                 .with_value("last_wait", current_state.get("in_service_since") - arrived)
                 .with_value("last_sojourn", float(virtual_time) - arrived)
                 .with_value("in_service_since", None))
        if queue:
            return self._start_service(agent_id, state, virtual_time)
        return BehaviorResult(next_state=state)

    def on_recover(self, agent_id, current_state, neighbors, virtual_time) -> BehaviorResult:
        if current_state.get("role") == "source":
            return BehaviorResult(next_state=current_state,
                                  set_timers=self._arrival_timer(agent_id, neighbors))
        # The departure timer was lost in the crash. Restart the head
        # customer's service; exact for exponential service (memoryless).
        state = current_state.with_value("in_service_since", None)
        if state.get("queue"):
            return self._start_service(agent_id, state, virtual_time)
        return BehaviorResult(next_state=state)

    # ---------------------------------------------------------------- helpers

    def _start_service(self, agent_id, state, virtual_time) -> BehaviorResult:
        state = state.with_value("in_service_since", float(virtual_time))
        return BehaviorResult(next_state=state,
                              set_timers=[Timer(DEPARTURE, self._exp(agent_id, self._mu))])

    def _arrival_timer(self, agent_id, neighbors) -> list[Timer]:
        if self._server not in neighbors:
            return []
        return [Timer(ARRIVAL, self._exp(agent_id, self._lambda))]

    def _exp(self, agent_id, rate) -> float:
        # portable_math, not rng.expovariate: these are exact event times, and
        # libm's log differs across platforms in the last bit.
        rng = self._rngs[agent_id]
        while True:  # zero only when random() is 0.0 -- not a legal delay
            delay = portable_math.expovariate(rng, rate)
            if delay > 0.0:
                return delay
