# Same seed, same result? SameSim and other Python simulators, across Python versions and operating systems

A fixed-seed scenario in each tool, run on Linux, macOS and Windows under
Python 3.10, 3.11, 3.12 and 3.13 (12 combinations), with **identical
library versions everywhere** so that only the interpreter and the
platform vary. Each scenario's full output is fingerprinted with SHA-256.

**Result: SameSim's runs were bit-identical in all 12 combinations. So
were the other tools' runs whose outputs avoid float `sum()` and keep no
raw C-library results. Two things break bit-identity in ordinary Python
model code, and both are platform facts rather than bugs in any tool:**

1. **CPython 3.12 changed `sum()` of floats.** An idiomatic averaging
   model gives one result on 3.10–3.11 and another on 3.12–3.13, on every
   OS, in Mesa and in plain Python alike.
2. **The platform C math library differs between operating systems** in
   the last bit, for every function tested. Whether that reaches a model's
   output depends on the model: SimPy's event times absorbed it here, while
   the service times drawn in the same run did not.

SameSim guards against both by construction and checks it continuously:
`math.fsum` instead of `sum()`, `samesim.domain.portable_math` instead of
libm, a lint test that rejects platform-dependent math, and golden traces
that must reproduce on every OS in CI.

## What was run

`survey.py` runs each scenario twice and hashes every recorded number.
Every scenario was repeatable within a run on every platform.
`.github/workflows/determinism-survey.yml` runs it on 3 OSes × 4 Python
versions, with the versions in [`requirements.txt`](requirements.txt): SimPy
4.1.2, Mesa 3.0.3, NDlib 6.0.0, NetworkX 3.4.2 and numpy 2.2.6, the newest
releases supporting all four Python versions.

| Scenario | What it is |
|---|---|
| `samesim/async_gossip`, `samesim/sir`, `samesim/gossip` | The shipped examples: event-driven gossip with Poisson clocks and exponential latency; SIR; synchronous gossip averaging |
| `simpy/mm1` | M/M/1 queue, the SimPy idiom (`random.expovariate`); records each customer's arrival, start and end time |
| `simpy/mm1_service` | The same run, recording each drawn service time |
| `mesa/voter` | Synchronous voter model (integer state) |
| `mesa/gossip` | Push-gossip averaging, mean computed with `sum() / len` |
| `ndlib/sir` | NDlib `SIRModel` on a NetworkX G(n, p) graph |
| `python/gossip` | The same averaging as `mesa/gossip` in plain Python |
| `libm/*` | `math.log`, `exp`, `pow`, `sin` and `random.expovariate`, `gauss`, `lognormvariate`, 200,000 inputs each |
| `portable/*` | `portable_math`'s `log`, `exp`, `expovariate`, `normalvariate`, `lognormvariate` on the same inputs |

```bash
python survey.py --out result.json     # one platform
python analyze.py                      # the tables below, from results/*.json
```

The workflow is manual (`workflow_dispatch`). Raw per-platform results:
[`results/`](results/); analysis output: [`summary.txt`](summary.txt).

## Results

| Scenario | Same seed, same output on all 12? | Groups of identical output |
|---|---|---|
| `samesim/async_gossip` | **yes** | |
| `samesim/sir` | **yes** | |
| `samesim/gossip` | **yes** | |
| `simpy/mm1` | **yes** | |
| `simpy/mm1_service` | no: 3 results | one per OS |
| `mesa/voter` | **yes** | |
| `mesa/gossip` | no: 2 results | Python 3.10–3.11 vs. 3.12–3.13, on every OS |
| `ndlib/sir` | **yes** | |
| `python/gossip` | no: 2 results | Python 3.10–3.11 vs. 3.12–3.13, on every OS |
| `libm/log`, `exp`, `pow`, `sin`, `expovariate`, `gauss`, `lognormvariate` | no: 3 results each | one per OS, the same on every Python version |
| `portable/*` (all five) | **yes** | |

**The Python-version split is the interpreter, not the framework.**
`mesa/gossip` and `python/gossip` produce the *same* hash in every
combination: Mesa draws from its RNG in the same order as the plain-Python
version, and both change exactly where CPython 3.12 changed `sum()`.

**How often the C math library disagrees.** Of 2,000 blocks of 100
outputs, the number that differ between each pair of operating systems
(Python 3.12):

| Function | Linux vs. macOS | Linux vs. Windows | macOS vs. Windows |
|---|---:|---:|---:|
| `log` | 81 | 60 | 74 |
| `exp` | 325 | 753 | 804 |
| `pow` | 303 | 158 | 290 |
| `sin` | 1,964 | 1,914 | 1,989 |
| `expovariate` | 214 | 322 | 293 |
| `gauss` | 1,944 | 1,877 | 1,970 |
| `lognormvariate` | 309 | 811 | 860 |

Each differing block holds at least one differing value. So at least 0.03%
of `log` results and 0.1% of `expovariate` draws differ between operating
systems, and for `sin` and `gauss` nearly every block of 100 contains a
difference. (Linux and Windows ran on x86-64, macOS on arm64.)

**Why SimPy's event times survived anyway.** At least 44 of the first 360
blocks of `expovariate` draws differ between Linux and macOS, and those
are exactly the draws `simpy/mm1` consumes: same `Random(7)` stream, one
`random()` per draw. But SimPy adds each draw to a clock that grows toward
20,000. A last-bit difference in a draw of size ~1 is about 2×10⁻¹⁶,
while floats near 20,000 are spaced about 4×10⁻¹², so the sum almost
always rounds to the same clock value. The service times recorded in the
same run keep the difference, and `simpy/mm1_service` differs on every OS.
A model whose output depends on draws more directly will diverge. So will
one with short times, where the clock is small, or with branches that
compare draws. SameSim's event-driven runs did, before `portable_math`:
golden traces recorded on Linux failed on macOS and Windows.

## What this shows, and what it doesn't

- **Shown:** on these 12 platform combinations, SameSim's scenarios were
  bit-identical, the platform math library was not, and SameSim's
  replacement for it was.
- **Shown:** the two mechanisms that break same-seed reproducibility in
  Python simulation code, and that they live in the interpreter and the
  platform, not in Mesa, SimPy or NDlib.
- **Not shown:** that other tools *can't* be made bit-reproducible. A
  model written with `math.fsum` and platform-independent math would be.
  The difference is that SameSim enforces it for every plugin, with tests,
  instead of leaving it to each model's author.
- The libm differences are for these runner images. C libraries change
  between releases, which is itself a reason not to depend on them.
