"""
The samesim command line.

    samesim examples                      list the shipped example configs
    samesim new my_study --from sir_random   copy one to start from
    samesim plugins [KIND | NAME]         every plugin, or one plugin's options
    samesim validate CONFIG               check everything without running
    samesim run CONFIG [-o DIR]           run once
    samesim sweep CONFIG --seeds 1-20     run many seeds, one after another
    samesim digest DIR                    the run's reproducibility fingerprint
    samesim visualize DIR                 an HTML dashboard of a run's results

CONFIG is a YAML file or the name of a shipped example. `run`, `validate`
and `sweep` accept --seed N and any number of --set path.to.key=value.
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path

from .. import __version__
from ..app import api, catalog


def _add_config_args(p: argparse.ArgumentParser, *, seed: bool = True) -> None:
    p.add_argument("config", help="a YAML config file, or the name of a shipped example")
    if seed:
        p.add_argument("--seed", type=int, help="replace experiment.seed")
    p.add_argument("--set", dest="overrides", action="append", default=[], metavar="PATH=VALUE",
                   help="override one config value, e.g. --set simulation.num_agents=500 "
                        "(repeatable; the value is read as YAML)")


def _overrides(args) -> dict:
    return dict(api.parse_override(o) for o in args.overrides)


# ----------------------------------------------------------------- commands

def cmd_examples(args) -> int:
    for e in catalog.list_examples():
        print(f"{e.name:22} {e.summary}")
    print("\nRun one:   samesim run <name>\nCopy one:  samesim new my_study --from <name>")
    return 0


def cmd_new(args) -> int:
    example = catalog.find_example(args.template)
    if example is None:
        names = ", ".join(e.name for e in catalog.list_examples())
        raise FileNotFoundError(f"No example '{args.template}'. Examples: {names}")
    target = Path(args.name if args.name.endswith((".yaml", ".yml")) else f"{args.name}.yaml")
    if target.exists() and not args.force:
        raise FileExistsError(f"{target} already exists (use --force to overwrite)")
    lines = example.path.read_text(encoding="utf-8").splitlines(keepends=True)
    out, renamed = [], False
    for line in lines:  # rename the experiment, keeping every comment
        if not renamed and line.lstrip().startswith("name:") and line.startswith("  "):
            out.append(f'  name: "{target.stem}"\n')
            renamed = True
        else:
            out.append(line)
    target.write_text("".join(out), encoding="utf-8")
    print(f"Wrote {target} (from the '{example.name}' example).")
    print(f"Next:  samesim validate {target}   then   samesim run {target}")
    return 0


def cmd_plugins(args) -> int:
    if args.query and args.query not in catalog.KINDS:
        p = catalog.find_plugin(args.query)
        if p is None:
            raise LookupError(f"No plugin or plugin kind '{args.query}'. Kinds: {', '.join(catalog.KINDS)}")
        print(f"{p.name}  ({p.kind})\n  {p.summary}\n")
        print(f"  In a config:   plugins.{catalog.KINDS[p.kind][1]}: \"{p.path}\"")
        if p.activation:
            print(f"  Activation:    {', '.join(p.activation)}")
        print(f"  Options:       plugin_configs.{p.name}\n")
        print("    " + (p.options or "none").replace("\n", "\n    "))
        return 0
    current = None
    for p in catalog.discover_plugins():
        if args.query and p.kind != args.query:
            continue
        if p.kind != current:
            current = p.kind
            print(f"\n{p.kind} (plugins.{catalog.KINDS[p.kind][1]})")
        mode = f" [{'/'.join(p.activation)}]" if p.activation else ""
        print(f"  {p.name:26} {p.summary}{mode}")
    print("\nDetails and options:  samesim plugins <Name>")
    return 0


def cmd_validate(args) -> int:
    config = api.validate(args.config, seed=args.seed, overrides=_overrides(args))
    p = config.plugins
    print(f"OK: '{config.name}', seed {config.seed}, {config.simulation.num_agents} agents, "
          f"{config.simulation.activation} activation, until t={config.simulation.max_virtual_time:g}")
    print(f"    {_short(p.behavior)} + {_short(p.communication)} on {_short(p.topology)}"
          + (f", churn: {_short(p.dynamics)}" if p.dynamics else ""))
    return 0


def cmd_run(args) -> int:
    result = api.run(args.config, args.output, seed=args.seed, overrides=_overrides(args))
    _report(result, args.output)
    return 0


def cmd_sweep(args) -> int:
    seeds = api.parse_seeds(args.seeds)
    out = Path(args.output)
    overrides = _overrides(args)
    api.validate(args.config, seed=seeds[0], overrides=overrides)  # fail before the first run
    for i, seed in enumerate(seeds, 1):
        result = api.run(args.config, out / f"seed-{seed}", seed=seed, overrides=overrides)
        print(f"[{i}/{len(seeds)}] seed {seed}: {result.wall_clock_seconds:.2f} s"
              + (f", digest {result.digest[:16]}" if result.digest else ""), flush=True)
    print(f"\nResults: {out}/seed-<n>/")
    return 0


def cmd_digest(args) -> int:
    files = sorted(Path(args.results).glob("*_trace_digest.csv"))
    if not files:
        raise FileNotFoundError(
            f"No *_trace_digest.csv in {args.results}. Add the fingerprint metric to the run:\n"
            f"  plugins.metrics: [..., \"samesim.plugins.metrics.trace_digest.TraceDigestMetric\"]"
        )
    for f in files:
        with open(f, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(l for l in fh if not l.startswith("#")))
        last = rows[-1]
        print(f"{last['digest']}  t={float(last['virtual_time']):g}  {f.name}")
    return 0


def cmd_visualize(args) -> int:
    from .visualize import generate_dashboard
    path = generate_dashboard(Path(args.results_dir))
    print(f"Dashboard written to: {path.resolve()}")
    return 0


def _report(result, output) -> None:
    c = result.config
    print(f"Ran '{c.name}' (seed {c.seed}, {c.simulation.num_agents} agents) "
          f"in {result.wall_clock_seconds:.2f} s.")
    for name, s in sorted(result.series.items()):
        if s.records and name != "trace_digest":
            print(f"  {name:28} {len(s.records):>7} records, last value {s.records[-1].value:g}")
    if result.digest:
        print(f"  digest {result.digest}")
    if output is not None:
        print(f"Results in {output}/")


def _short(path: str | None) -> str:
    return path.rsplit(".", 1)[-1] if path else ""


# ---------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="samesim",
        description="SameSim: same seed, same simulation. A deterministic discrete-event "
                    "simulator for message-passing agents.",
        epilog="Start with:  samesim examples",
    )
    parser.add_argument("--version", action="version", version=f"samesim {__version__}")
    parser.add_argument("--log-level", default="WARNING",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="logging verbosity (default: WARNING); DEBUG also shows tracebacks")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p = sub.add_parser("examples", help="list the shipped example configs")
    p.set_defaults(func=cmd_examples)

    p = sub.add_parser("new", help="start a config from an example")
    p.add_argument("name", help="the new config's name (writes NAME.yaml)")
    p.add_argument("--from", dest="template", default="gossip_random",
                   help="the example to copy (default: gossip_random)")
    p.add_argument("--force", action="store_true", help="overwrite an existing file")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("plugins", help="list plugins, or show one plugin's options")
    p.add_argument("query", nargs="?",
                   help=f"a kind ({', '.join(catalog.KINDS)}) or a plugin name")
    p.set_defaults(func=cmd_plugins)

    p = sub.add_parser("validate", help="check a config completely, without running it")
    _add_config_args(p)
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("run", help="run an experiment")
    _add_config_args(p)
    p.add_argument("--output", "-o", type=Path, default=Path("./results"), metavar="DIR",
                   help="directory for result files (default: ./results)")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("sweep", help="run one config over many seeds, one after another")
    _add_config_args(p, seed=False)
    p.add_argument("--seeds", required=True, help="e.g. 1-20, or 1,5,9, or 1-5,10")
    p.add_argument("--output", "-o", type=Path, default=Path("./results"), metavar="DIR",
                   help="writes DIR/seed-<n>/ for each seed (default: ./results)")
    p.set_defaults(func=cmd_sweep)

    p = sub.add_parser("digest", help="print a run's reproducibility fingerprint")
    p.add_argument("results", help="a results directory")
    p.set_defaults(func=cmd_digest)

    p = sub.add_parser("visualize", help="write an HTML dashboard for a results directory")
    p.add_argument("results_dir", nargs="?", default="./results")
    p.set_defaults(func=cmd_visualize)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level),
                        format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    try:
        return args.func(args)
    except Exception as exc:  # one clean line, unless asked for the traceback
        if args.log_level == "DEBUG":
            raise
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
