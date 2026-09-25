# Raft Election Time vs. Election-Timeout Range

**Status:** first result that needs Phase 2 (event-driven agents with
timers) of [docs/design/event_model.md](../../docs/design/event_model.md).
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

The paper timed recovery after a leader crash. Simul8 can't crash nodes yet
(Phase 3), so this study times the first election from a cold start. Both
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

## What this doesn't cover yet

- **Leader crashes.** This is the paper's actual scenario, and it needs
  nodes that can fail, which is Phase 3 (churn).
- **Log replication**, and with it the election restriction on log
  freshness. Any node can win here.
- **Message loss and partitions** in the timing study. The safety tests
  include loss; this sweep doesn't.
