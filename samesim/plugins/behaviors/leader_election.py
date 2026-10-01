"""
LeaderElectionBehavior — max-value flood-based leader election behavior.

Every agent starts with a randomly drawn positive integer "candidate_id" (its UID).
Initially, each agent considers itself the leader.

In each tick:
    1. Read all received leader candidate IDs from neighbors in the inbox.
    2. Adopt the maximum candidate ID seen so far (the leader).
    3. Broadcast the current known leader ID to all neighbors.

Eventually, the agent with the highest candidate_id will propagate its ID to
all nodes, achieving consensus.

Configuration: none required.
"""
from __future__ import annotations

import random
from typing import Any

from ...domain.ids import AgentId, MessageId, VirtualTime
from ...domain.message import Message
from ...domain.state import AgentState
from ...ports.behavior import BehaviorPort, BehaviorResult


class LeaderElectionBehavior(BehaviorPort):
    """Max-value flood leader election behavior."""

    def __init__(self) -> None:
        self._msg_counter: int = 0

    def initialize(
        self,
        agent_id: AgentId,
        config: dict[str, Any],
        rng: random.Random,
    ) -> AgentState:
        """Assign a unique random integer as the candidate ID."""
        # Generate a candidate ID (UID) in range [1, 10000000]
        # Combining global seed & agent_id via rng ensures uniqueness and reproducibility
        uid = rng.randint(1, 10_000_000)
        return AgentState(
            data={
                "uid": uid,
                "leader_id": uid,
            }
        )

    def step(
        self,
        agent_id: AgentId,
        current_state: AgentState,
        inbox: list[Message],
        neighbors: frozenset[AgentId],
        virtual_time: VirtualTime,
    ) -> BehaviorResult:
        my_uid = current_state.get("uid")
        current_leader = current_state.get("leader_id", my_uid)

        # 1. Inspect inbox and find the maximum leader ID proposed
        highest_seen = current_leader
        for msg in inbox:
            sender_leader = msg.get("leader_id")
            if sender_leader is not None and sender_leader > highest_seen:
                highest_seen = sender_leader

        # Update state if a new leader is adopted
        next_state = current_state.with_value("leader_id", highest_seen)

        # 2. Broadcast current leader to all neighbors
        outbound: list[Message] = []
        if neighbors:
            for neighbor_id in sorted(neighbors):
                self._msg_counter += 1
                outbound.append(Message(
                    message_id=MessageId(self._msg_counter),
                    sender_id=agent_id,
                    recipient_id=neighbor_id,
                    payload={"leader_id": highest_seen},
                ))

        return BehaviorResult(next_state=next_state, outbound_messages=outbound)
