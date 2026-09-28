# Raft Election Time vs. Election-Timeout Range

**Status:** first result that needs Phase 2 (event-driven agents with
timers) of [docs/design.md](../../docs/design.md).
Modeled on Figure 16 of Ongaro & Ousterhout, *In Search of an
Understandable Consensus Algorithm* (USENIX ATC 2014).

## Question

Raft picks election timeouts at random so that one follower usually times
out first and wins before anyone else becomes a candidate. The paper makes
three qualitative claims about this:

1. Without randomization, split votes make elections take a long time.
2. Even a little randomization helps a lot, and ranges like 150–300 ms work
   well.
3. Timeouts too close to the network delay break Raft's timing requirement
   (broadcast time ≪ election timeout), and the cluster becomes unstable.

Does `RaftElectionBehavior` in Simul8 reproduce all three?

## Method

`run_raft_sweep.py` runs a 5-node cluster on a complete graph under event
activation. Messages take 5–15 ms (uniform), so a request/response takes
10–30 ms, bracketing the paper's ~15 ms broadcast time. The heartbeat interval is
one third of the minimum timeout. Each configuration runs 500 trials (seeds
0–499) with a 5,000 ms horizon, 5,500 trials in all.

The paper timed recovery after a leader crash. This first study times the
first election from a cold start instead (the crash study below came later,
with Phase 3). Both
begin with every follower's timer armed at almost the same instant, which is
the situation randomization has to resolve. The absolute numbers are not
comparable to the paper's hardware measurements. The shape is.

```
python run_raft_sweep.py            # full, ~4 min
python run_raft_sweep.py --quick    # 40 trials per range
```

Raw output: `raft_results.json`.

## Results

**Varying randomization** (minimum fixed at 150 ms):

| Timeout range (ms) | Elected within 5 s | Median | p95 | Max | Mean winning term |
|---|---:|---:|---:|---:|---:|
| 150–150 | 0 / 500 | — | — | — | — |
| 150–151 | 0 / 500 | — | — | — | — |
| 150–155 | 452 / 500 | 1,837 | 4,127 | 4,739 | 13.4 |
| 150–175 | 500 / 500 | 177 | 502 | 993 | 1.61 |
| 150–200 | 500 / 500 | 177 | 348 | 879 | 1.16 |
| 150–300 | 500 / 500 | 187 | 235 | 450 | 1.00 |

**Scaling the timeout down** (range = [T, 2T]):

| Timeout range (ms) | Median | p95 | Mean winning term | Further elections per run |
|---|---:|---:|---:|---:|
| 12–24 | 106 | 296 | 6.84 | **26.5** |
| 25–50 | 52 | 127 | 1.61 | 0.14 |
| 50–100 | 77 | 148 | 1.16 | 0 |
| 100–200 | 132 | 171 | 1.02 | 0 |
| 150–300 | 187 | 235 | 1.00 | 0 |

**Election Safety held in every trial.** No term ever had two leaders in
5,500 runs, including the ~13,000 re-elections of the 12–24 ms
configuration. (The safety tests in `tests/integration/test_raft_election.py`
confirm the check has teeth: letting nodes vote twice per term produces
violations.)

## Interpretation

All three claims reproduce.

1. **No randomization means no leader.** With 150–150 or 150–151 ms timeouts, every
   node becomes a candidate within about 1 ms of the others and votes for
   itself before any RequestVote can arrive, since the minimum message
   delay is 5 ms. The spread between nodes' timeouts grows only as a random
   walk, too slowly to exceed the delay within 5 s. In real deployments,
   OS and network jitter eventually break the tie, and the paper's 150–150
   case did elect, slowly. A simulator has no such jitter, so the
   dependence on explicit randomization is exposed completely.
2. **A little randomization changes everything.** At 150–155 ms, 90% of trials
   elect, but after 13 terms on average. At 150–175 ms every trial elects,
   with a median of 177 ms. At 150–300 ms the **first** candidate wins every single
   time (mean winning term 1.00), and the worst case falls from 993 ms to 450 ms.
   Widening the range trades a slightly later median (187 vs. 177 ms) for a
   much shorter tail.
3. **Timeouts near the network delay destabilize the cluster.** 12–24 ms
   elects a first leader quickly, but that leader doesn't last. Heartbeats
   take 5–15 ms to arrive, so followers regularly time out on a live
   leader, producing 26.5 further elections per 5-second run. At 25–50 ms
   this has almost disappeared (0.14), and at 50 ms and above it's gone.
   The fastest *first* election is at 25–50 ms. Going lower than that makes
   elections slower, not faster.

## Leader crash (Phase 3): the paper's actual scenario

The paper measured recovery after a *leader crash*. Once churn existed,
`run_raft_crash_sweep.py` could do the same. Each trial starts the 5-node
cluster in steady state (`initial_leader`: agent 0 leads term 1). At
t = 1000 ms plus a random offset within one heartbeat interval,
`ScheduledChurn` crashes **whoever is leader at that moment** (the
`where: {role: leader}` selector), and the time until a new leader is
elected is the downtime. The ranges, network and heartbeat rule are the same
as above, with 500 trials per range. Raw output: `raft_crash_results.json`.

| Timeout range (ms) | Recovered within 5 s | Median downtime | p95 | Max | Mean new term | Cold-start median (above) |
|---|---:|---:|---:|---:|---:|---:|
| 150–150 | 35 / 500 | 452 | 4,219 | 4,949 | 7.6 | never elects |
| 150–151 | 53 / 500 | 1,189 | 4,808 | 4,839 | 12.2 | never elects |
| 150–155 | 414 / 500 | 1,839 | 4,698 | 4,901 | 14.9 | 1,837 |
| 150–175 | 500 / 500 | 299 | 670 | 1,594 | 3.03 | 177 |
| 150–200 | 500 / 500 | 174 | 493 | 981 | 2.30 | 177 |
| 150–300 | 500 / 500 | 186 | 325 | 631 | 2.06 | 187 |
| 12–24 | 500 / 500 | 138 | 516 | 893 | 19.2 | 106 |
| 25–50 | 500 / 500 | 78 | 195 | 311 | 2.96 | 52 |
| 50–100 | 500 / 500 | 84 | 217 | 432 | 2.38 | 77 |
| 100–200 | 500 / 500 | 136 | 281 | 454 | 2.14 | 132 |

**Election Safety held in all 5,500 crash trials.**

What the crash scenario adds:

1. **Network jitter partly rescues the no-randomization configs, but only
   partly.** From a cold start, 150–150 never elects. After a crash it
   recovers in 7% of trials (35/500), because the followers' timers were
   last reset by heartbeats arriving 5–15 ms apart and so start out
   staggered. This is the paper's observation that real clusters do elect
   at 150–150, rarely and slowly.
2. **Narrow ranges recover worse after a crash than from a cold start.** At
   150–175 ms the median downtime is 299 ms against 177, and p95 670 against
   502. The likely reason is that Raft's majority is counted over the whole
   configured cluster, crashed node included: a candidate still needs 3 of
   5 votes but only 4 nodes can answer, so split votes are harder to
   resolve. This hasn't been isolated experimentally. At 150–300 ms the
   difference disappears (186 vs 187 ms): a wide range absorbs it.
3. **Too-short timeouts are unstable before the crash as well as after it.**
   At 12–24 ms the cluster had already held ~1.7 unnecessary elections
   before the crash (despite starting in steady state), and the winning term
   averages 19. From 25–50 ms up, there are no pre-crash elections.

## What this doesn't cover yet

- **Log replication**, and with it the election restriction on log
  freshness. Any node can win here.
- **Message loss and partitions** in the timing study. The safety tests
  include loss; this sweep doesn't.
