# Contributing to SameSim

Thanks for your interest. Bug reports, questions, new plugins and new
validation studies are all welcome.

## Reporting a bug

Open an [issue](https://github.com/ImCYMBIOT/samesim/issues) with:

- `samesim --version`, your Python version and operating system;
- the config (YAML) and the command or Python call you ran;
- what you expected, and what happened instead (full error output: rerun
  with `samesim --log-level DEBUG ...` to get the traceback).

If two runs with the same config and seed give different results, or a
digest differs between machines, that is a bug in SameSim, not in your
model. Please include both digests (`samesim digest <results dir>`) and
both platforms.

## Asking for help

Open an issue with the `question` label. The
[User Guide](docs/user_guide.md) covers configs, activation modes, latency,
churn and every plugin's options; `samesim plugins NAME` prints a plugin's
options from the command line.

## Contributing code

```bash
git clone https://github.com/ImCYMBIOT/samesim.git && cd samesim
python -m venv .venv && source .venv/bin/activate   # or a conda env
pip install -e ".[dev]"
pytest                  # ~90 s
pytest -m "not slow"    # skip the scale tests
```

1. Open an issue first for anything larger than a small fix, so we can
   agree on the approach.
2. Read the [Developer Guide](docs/developer_guide.md): the architecture,
   the determinism rules, and how to write a plugin. Its section 7 is the
   checklist a pull request is reviewed against.
3. Keep runs deterministic. All randomness comes from the `rng` the engine
   gives you; float sums use `math.fsum`; `log`, `exp`, powers and random
   variates go through `samesim.domain.portable_math`. CI runs the golden
   traces on Linux, macOS and Windows and fails on any difference.
4. Fix bugs by class. A fix comes with a test that would have caught the
   whole kind of error, preferably one that discovers its targets (every
   plugin, every example) so it also covers future code.
5. Golden traces. A change that is not meant to alter simulation output
   must pass `tests/regression/test_golden_traces.py` unchanged. A new
   plugin or example records its traces with
   `pytest tests/regression/test_golden_traces.py --update-golden`, and the
   JSON diff should contain only additions. Say so in the pull request.
6. Update [CHANGELOG.md](CHANGELOG.md) under "Unreleased", and the User
   Guide if users will see the change.

## Contributing a validation study

Studies live in `experiments/<study>/` with a `README.md`, the scripts, the
raw results and an `analyze.py`. Use at least 20 independent seeds, report
confidence intervals, and fix any equivalence margin before running. When
comparing against another tool, run both on identical inputs (for
example, the same graph per seed) and pin that tool's version.

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).
