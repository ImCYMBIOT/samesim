"""
SirEpidemicBehavior — Susceptible-Infected-Recovered (SIR) epidemic simulation behavior.

States:
    "S": Susceptible. Can be infected by contacts with Infected neighbors.
    "I": Infected. Spreads infection to neighbors and recovers over time.
    "R": Recovered. Immune to further infection; does not spread.

Transitions:
    S -> I: If neighbor(s) are infected, probability of infection is:
            P(infection) = 1 - (1 - beta)^k
            where beta is the transmission_rate, and k is the number of infected neighbors.
    I -> R: Probability of recovery per tick is gamma (recovery_rate).

Initialization:
    Typically, 1 agent starts as Infected ("I"), and all other agents start as Susceptible ("S").

Timing: the step at t=0 is an announcement round. Every inbox is empty then,
since nobody has communicated yet, so nobody changes state; infected agents
only expose their neighbors. From t=1 on, the state at time t is exactly
iteration t of the standard discrete-time SIR (as in NDlib): infection from
the previous step's infected neighbors, and an infected agent exposes its
neighbors in every step before the one in which it recovers. Without the
announcement round, the initially infected took a recovery draw before
exposing anyone -- an expected infectious period 10% shorter than every other
agent's (9 steps instead of 10 at gamma = 0.1).

Configuration:
    transmission_rate: float — probability of infection per infected neighbor (default 0.2)
    recovery_rate: float     — probability of recovery per tick (default 0.1)
    initial_infected: int    — number of initial infected agents (default 1)
"""
from __future__ import annotations

import random
from typing import Any

from ...domain import portable_math
from ...domain.ids import AgentId, MessageId, VirtualTime
from ...domain.message import Message
from ...domain.state import AgentState
from ...ports.behavior import BehaviorPort, BehaviorResult


class SirEpidemicBehavior(BehaviorPort):
    """Susceptible-Infected-Recovered (SIR) model behavior."""

    def __init__(self) -> None:
        self._beta: float = 0.2  # transmission rate
        self._gamma: float = 0.1  # recovery rate
        self._msg_counter: int = 0
        self._agent_rngs: dict[AgentId, random.Random] = {}

    def initialize(
        self,
        agent_id: AgentId,
        config: dict[str, Any],
        rng: random.Random,
    ) -> AgentState:
        self._beta = float(config.get("transmission_rate", 0.2))
        self._gamma = float(config.get("recovery_rate", 0.1))
        initial_infected_count = int(config.get("initial_infected", 1))

        self._agent_rngs[agent_id] = rng

        # First initial_infected_count agents start as Infected, others Susceptible
        status = "I" if int(agent_id) < initial_infected_count else "S"
        return AgentState(data={"status": status})

    def step(
        self,
        agent_id: AgentId,
        current_state: AgentState,
        inbox: list[Message],
        neighbors: frozenset[AgentId],
        virtual_time: VirtualTime,
    ) -> BehaviorResult:
        rng = self._agent_rngs[agent_id]
        status = current_state.get("status", "S")
        next_status = status

        if virtual_time == 0:
            pass  # announcement round (see module docstring): no transitions
        elif status == "S":
            # 1. Count infected contacts received in inbox
            infected_contacts = sum(
                1 for msg in inbox if msg.get("status") == "I"
            )
            if infected_contacts > 0:
                # Infection probability: 1 - (1 - beta)^k
                # ipow, not **: float ** calls the platform's pow().
                p_infection = 1.0 - portable_math.ipow(1.0 - self._beta, infected_contacts)
                if rng.random() < p_infection:
                    next_status = "I"

        elif status == "I":
            # 2. Check for recovery
            if rng.random() < self._gamma:
                next_status = "R"

        next_state = current_state.with_value("status", next_status)

        # 3. If infected, expose the whole neighborhood: one message flagged
        # broadcast=True, rather than enumerating neighbors here. Every
        # protocol honours that flag (see Message.broadcast), so this pairs
        # correctly with lossless and lossy transports alike -- under a lossy
        # channel each neighbor is exposed independently, which is the point.
        outbound: list[Message] = []
        if next_status == "I" and neighbors:
            self._msg_counter += 1
            outbound.append(Message(
                message_id=MessageId(self._msg_counter),
                sender_id=agent_id,
                recipient_id=agent_id,  # ignored when broadcast=True
                payload={"status": "I"},
                broadcast=True,
            ))

        return BehaviorResult(next_state=next_state, outbound_messages=outbound)
