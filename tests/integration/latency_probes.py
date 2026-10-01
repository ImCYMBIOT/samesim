"""
Test-only plugins for tests/integration/test_latency_timing.py.

SendScheduleBehavior sends messages from agent 0 to agent 1 on the steps
listed in its config, and logs, for every message agent 1 receives, the
step it was sent on and the step it became visible on. The log is a class
attribute because the runner builds plugins itself; tests reset it.
"""
from __future__ import annotations

import random
from typing import Any

from samesim.domain.delivery import Delivery
from samesim.domain.ids import AgentId, MessageId, VirtualTime
from samesim.domain.message import Message
from samesim.domain.state import AgentState
from samesim.domain.topology import TopologyGraph
from samesim.ports.behavior import BehaviorPort, BehaviorResult
from samesim.ports.communication import CommunicationProtocolPort


class SendScheduleBehavior(BehaviorPort):
    log: list[dict[str, Any]] = []

    def __init__(self) -> None:
        self._send_steps: set[int] = set()
        self._per_step = 1
        self._counter = 0

    def initialize(self, agent_id: AgentId, config: dict[str, Any], rng: random.Random) -> AgentState:
        self._send_steps = set(config.get("send_steps", [0]))
        self._per_step = int(config.get("per_step", 1))
        return AgentState(data={"step": 0})

    def step(self, agent_id, current_state, inbox, neighbors, virtual_time) -> BehaviorResult:
        step = current_state.get("step")
        if agent_id == AgentId(1):
            for m in inbox:
                SendScheduleBehavior.log.append({
                    "sent_step": m.get("sent_step"),
                    "seen_step": step,
                    "seen_time": float(virtual_time),
                    "sent_time": m.get("sent_time"),
                })
        out: list[Message] = []
        if agent_id == AgentId(0) and step in self._send_steps:
            for _ in range(self._per_step):
                self._counter += 1
                out.append(Message(
                    message_id=MessageId(self._counter), sender_id=agent_id,
                    recipient_id=AgentId(1),
                    payload={"sent_step": step, "sent_time": float(virtual_time)},
                ))
        return BehaviorResult(next_state=current_state.with_value("step", step + 1), outbound_messages=out)


class DelayBySendStepProtocol(CommunicationProtocolPort):
    """Delay chosen per send step from config: {"delays": {step: delay}}."""

    def initialize(self, topology: TopologyGraph, config: dict[str, Any], rng: random.Random) -> None:
        self._delays = {int(k): v for k, v in config.get("delays", {}).items()}

    def route(self, message, sender_id, topology):
        delay = self._delays.get(message.get("sent_step"))
        return [Delivery(message.recipient_id, message, delay)]
