"""
RaftElectionBehavior — Raft's leader election (Ongaro & Ousterhout, 2014, §5.2).

Leader election only: terms, randomized election timeouts, RequestVote,
votes, and heartbeats (empty AppendEntries). No log replication, so the
election restriction on log freshness does not apply -- any candidate is
eligible.

Requires simulation.activation: event.

Each agent is a follower, candidate or leader:

    follower   election timer expires  ->  candidate
    candidate  election timer expires  ->  candidate again, next term
               votes from a majority   ->  leader
               heartbeat, current term ->  follower
    any        message with a higher term -> follower in that term

A follower resets its election timer when it grants a vote or hears a
heartbeat from the current leader. A leader sends heartbeats every
heartbeat_interval. Each agent votes at most once per term.

Crash recovery (with churn): term and voted_for survive a crash, role and
votes do not (see on_recover). Cluster membership is every agent the
behavior has initialized; agents that join mid-run enlarge the majority,
which is NOT Raft's joint-consensus membership change -- use joins with
care.

Raft assumes every server can reach every other, and a majority is counted
over the whole cluster. Use a complete topology (ErdosRenyiTopology with
edge_probability: 1.0); on a sparser graph a candidate can only collect
votes from its neighbors and may never reach a majority.

Configuration (plugin_configs.RaftElectionBehavior):
    election_timeout_min: float  (default 150)
    election_timeout_max: float  (default 300)
    heartbeat_interval:   float  (default 50; should be well below the timeout)
    initial_leader:       int    (optional) start in steady state: this agent
                                 is leader of term 1 and every other agent a
                                 follower that voted for it. For experiments
                                 that begin from a running cluster, like
                                 crashing the leader. Default: cold start,
                                 everyone a follower in term 0.

Timeouts are in virtual-time units; the defaults match the paper's
recommended 150-300 ms with a millisecond time unit.

State: {"role", "term", "voted_for", "votes", "leader_id"}
    votes is the sorted list of agents that voted for this candidate in
    its current term.
"""
from __future__ import annotations

import random
from typing import Any

from ...domain.ids import AgentId, MessageId, VirtualTime
from ...domain.message import Message
from ...domain.state import AgentState
from ...domain.timer import Timer
from ...ports.behavior import BehaviorPort, BehaviorResult

ELECTION = "election"
HEARTBEAT = "heartbeat"


class RaftElectionBehavior(BehaviorPort):
    """Raft leader election over messages and timers."""

    activation_modes = frozenset({"event"})

    def __init__(self) -> None:
        self._agent_rngs: dict[AgentId, random.Random] = {}
        self._t_min = 150.0
        self._t_max = 300.0
        self._heartbeat = 50.0
        self._msg_counter = 0

    def initialize(self, agent_id: AgentId, config: dict[str, Any], rng: random.Random) -> AgentState:
        self._t_min = float(config.get("election_timeout_min", 150.0))
        self._t_max = float(config.get("election_timeout_max", 300.0))
        self._heartbeat = float(config.get("heartbeat_interval", 50.0))
        if not 0 < self._t_min <= self._t_max:
            raise ValueError(
                f"RaftElectionBehavior: need 0 < election_timeout_min <= election_timeout_max, "
                f"got {self._t_min}, {self._t_max}")
        if not self._heartbeat > 0:
            raise ValueError(f"RaftElectionBehavior: heartbeat_interval must be > 0, got {self._heartbeat}")
        self._agent_rngs[agent_id] = rng
        leader = config.get("initial_leader")
        if leader is not None:
            leader = int(leader)
            if int(agent_id) == leader:
                return AgentState(data={"role": "leader", "term": 1, "voted_for": leader,
                                        "votes": [leader], "leader_id": leader})
            return AgentState(data={"role": "follower", "term": 1, "voted_for": leader,
                                    "votes": [], "leader_id": leader})
        return AgentState(data={"role": "follower", "term": 0, "voted_for": None,
                                "votes": [], "leader_id": None})

    @property
    def _majority(self) -> int:
        return len(self._agent_rngs) // 2 + 1

    # -- messages -----------------------------------------------------------

    def step(self, agent_id, current_state, inbox, neighbors, virtual_time) -> BehaviorResult:
        if not inbox:  # bootstrap
            if current_state.get("role") == "leader":  # steady-state start (initial_leader)
                return BehaviorResult(
                    next_state=current_state,
                    outbound_messages=[self._broadcast(agent_id, "heartbeat", current_state.get("term"))],
                    set_timers=[Timer(HEARTBEAT, self._heartbeat)])
            return BehaviorResult(next_state=current_state, set_timers=[self._election_timer(agent_id)])

        s = dict(current_state.data)
        s["votes"] = list(s["votes"])
        was_leader = s["role"] == "leader"
        out: list[Message] = []
        reset_election = False

        for m in inbox:
            if m.get("term") > s["term"]:
                s.update(term=m.get("term"), role="follower", voted_for=None, votes=[], leader_id=None)
            if m.get("term") < s["term"]:
                continue  # stale: from an earlier term

            kind = m.get("kind")
            if kind == "request_vote" and s["role"] == "follower" \
                    and s["voted_for"] in (None, int(m.sender_id)):
                s["voted_for"] = int(m.sender_id)
                out.append(self._message(agent_id, m.sender_id, "vote", s["term"]))
                reset_election = True
            elif kind == "vote" and s["role"] == "candidate":
                if int(m.sender_id) not in s["votes"]:
                    s["votes"] = sorted(s["votes"] + [int(m.sender_id)])
                if len(s["votes"]) >= self._majority:
                    s.update(role="leader", leader_id=int(agent_id))
            elif kind == "heartbeat":
                # Same term (higher terms were handled above): a leader exists.
                s.update(role="follower", leader_id=int(m.sender_id))
                reset_election = True

        return self._transition(agent_id, was_leader, s, out, reset_election, virtual_time)

    # -- timers -------------------------------------------------------------

    def on_timer(self, agent_id, current_state, tag, neighbors, virtual_time) -> BehaviorResult:
        s = dict(current_state.data)
        if tag == HEARTBEAT:
            if s["role"] != "leader":
                return BehaviorResult(next_state=current_state)
            return BehaviorResult(
                next_state=current_state,
                outbound_messages=[self._broadcast(agent_id, "heartbeat", s["term"])],
                set_timers=[Timer(HEARTBEAT, self._heartbeat)],
            )

        # Election timeout: start (or restart) an election in the next term.
        s.update(role="candidate", term=s["term"] + 1, voted_for=int(agent_id),
                 votes=[int(agent_id)], leader_id=None)
        out = [self._broadcast(agent_id, "request_vote", s["term"])]
        if len(s["votes"]) >= self._majority:  # a one-agent cluster elects itself
            s.update(role="leader", leader_id=int(agent_id))
        return self._transition(agent_id, False, s, out, True, virtual_time)

    # -- crash recovery -----------------------------------------------------

    def on_recover(self, agent_id, current_state, neighbors, virtual_time) -> BehaviorResult:
        """Restart after a crash (Raft section 5.1).

        Raft keeps currentTerm and votedFor on stable storage, and that is
        what makes a restart safe: a node that forgot it had voted could vote
        again in the same term and elect a second leader. Role and votes are
        volatile, so the node comes back as a follower, with no known leader,
        and a fresh election timeout.
        """
        s = dict(current_state.data)
        s.update(role="follower", votes=[], leader_id=None)
        return BehaviorResult(next_state=AgentState(data=s), set_timers=[self._election_timer(agent_id)])

    # -- helpers ------------------------------------------------------------

    def _transition(self, agent_id, was_leader, s, out, reset_election, virtual_time) -> BehaviorResult:
        timers: list[Timer] = []
        cancels: set[str] = set()
        if s["role"] == "leader" and not was_leader:
            cancels.add(ELECTION)
            out.append(self._broadcast(agent_id, "heartbeat", s["term"]))
            timers.append(Timer(HEARTBEAT, self._heartbeat))
        elif s["role"] != "leader":
            if was_leader:
                cancels.add(HEARTBEAT)
                reset_election = True
            if reset_election:
                timers.append(self._election_timer(agent_id))
        return BehaviorResult(next_state=AgentState(data=s), outbound_messages=out,
                              set_timers=timers, cancel_timers=frozenset(cancels))

    def _election_timer(self, agent_id: AgentId) -> Timer:
        return Timer(ELECTION, self._agent_rngs[agent_id].uniform(self._t_min, self._t_max))

    def _broadcast(self, sender: AgentId, kind: str, term: int) -> Message:
        self._msg_counter += 1
        return Message(message_id=MessageId(self._msg_counter), sender_id=sender,
                       recipient_id=sender, payload={"kind": kind, "term": term}, broadcast=True)

    def _message(self, sender: AgentId, recipient: AgentId, kind: str, term: int) -> Message:
        self._msg_counter += 1
        return Message(message_id=MessageId(self._msg_counter), sender_id=sender,
                       recipient_id=recipient, payload={"kind": kind, "term": term})
