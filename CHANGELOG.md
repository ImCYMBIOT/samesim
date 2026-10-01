# Changelog

## 0.2.0 — 2026-10

First public release, under a new name.

**Renamed from Simul8 to SameSim** ("same seed, same simulation"). SIMUL8 is
an unrelated commercial product. Package, command and imports are now
`samesim`.

### Added
- Command line: `samesim examples`, `new`, `plugins`, `validate`,
  `run --seed --set`, `sweep --seeds`, `digest`, alongside `visualize`.
- Python API: `samesim.run(config, output_dir=None, seed=, overrides=)` and
  `samesim.validate(...)`. A config can be a YAML path, a shipped example's
  name or a dict; results come back in memory (`RunResult`).
- Example configs ship with the package.
- Plugins: `QueueBehavior` + `QueueMetric` (M/M/1), `VoterBehavior` +
  `VoterMetric`, `ConsensusMetric` (agreement among running vs. all agents
  under churn).
- Validation studies: M/M/1 vs. SimPy and the closed forms, with an exact
  Lindley-recursion test; voter model vs. Mesa and the exact martingale
  result; churn and convergence; a cross-platform determinism survey of
  SameSim, SimPy, Mesa, NDlib and plain Python on 3 OSes x Python 3.10–3.13.

### Changed
- Per-agent random streams are hashed from `"<seed>/agent/<id>"`. The old
  `seed XOR agent_id` made runs with different seeds share agent streams,
  so replicates were partly copies of each other. **Same seed now gives a
  different (independent) run than in 0.1.**
- SIR's first synchronous step is an announcement round, matching the
  standard discrete-time model.
- Unknown fields in a config, and `plugin_configs` options a plugin never
  reads, are errors instead of being silently ignored. `LossyProtocol`'s
  removed `mode` option is rejected.
- `summary.json` records the full resolved config.
- Every study re-run with independent seeds, 20–200 seeds per point and
  confidence intervals; five earlier claims were withdrawn (see each
  study's README).

## 0.1.0

Initial version (as Simul8): the engine, synchronous and event-driven
activation, latency, churn, golden traces and the first validation studies.
