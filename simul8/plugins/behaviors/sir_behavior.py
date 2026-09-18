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

Configuration:
    transmission_rate: float — probability of infection per infected neighbor (default 0.2)
    recovery_rate: float     — probability of recovery per tick (default 0.1)
    initial_infected: int    — number of initial infected agents (default 1)
"""
from __future__ import annotations

import random
from typing import Any

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

        if status == "S":
            # 1. Count infected contacts received in inbox
            infected_contacts = sum(
                1 for msg in inbox if msg.get("status") == "I"
            )
            if infected_contacts > 0:
                # Infection probability: 1 - (1 - beta)^k
                p_infection = 1.0 - ((1.0 - self._beta) ** infected_contacts)
                if rng.random() < p_infection:
                    next_status = "I"

        elif status == "I":
            # 2. Check for recovery
            if rng.random() < self._gamma:
                next_status = "R"

        next_state = current_state.with_value("status", next_status)

        # 3. If infected, send a single infection warning -- the active
        # communication protocol decides delivery. With BroadcastProtocol
        # (the intended pairing for this behavior) that one message is
        # fanned out to every neighbor by the protocol itself; sending one
        # message per neighbor here as well would double that fan-out
        # (each neighbor receiving deg(agent_id) copies instead of one),
        # inflating the effective transmission rate far above beta.
        # recipient_id is nominal here since BroadcastProtocol ignores it
        # and recomputes deliveries from the topology.
        outbound: list[Message] = []
        if next_status == "I" and neighbors:
            self._msg_counter += 1
            outbound.append(Message(
                message_id=MessageId(self._msg_counter),
                sender_id=agent_id,
                recipient_id=agent_id,
                payload={"status": "I"},
            ))

        return BehaviorResult(next_state=next_state, outbound_messages=outbound)
