"""
CLI entry point for Simul8.

Usage:
    python -m simul8.cli.main run examples/gossip_1000_agents.yaml
    python -m simul8.cli.main run examples/gossip_1000_agents.yaml --output ./results
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from ..app.experiment_runner import ExperimentRunner


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="simul8",
        description=(
            "Simul8 — modular event-driven simulation platform for distributed systems research.\n"
            "The engine manages agents, time, events, and communication.\n"
            "Everything else is a plugin."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- run subcommand ---
    run_parser = subparsers.add_parser("run", help="Run a simulation experiment from a YAML config")
    run_parser.add_argument(
        "config",
        type=Path,
        help="Path to the YAML experiment configuration file",
    )
    run_parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("./results"),
        metavar="DIR",
        help="Output directory for result files (default: ./results)",
    )
    run_parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )

    # --- visualize subcommand ---
    viz_parser = subparsers.add_parser("visualize", help="Generate an interactive dashboard from results")
    viz_parser.add_argument(
        "results_dir",
        type=Path,
        nargs="?",
        default=Path("./results"),
        help="Directory containing experiment results (default: ./results)",
    )
    viz_parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    if args.command == "run":
        runner = ExperimentRunner()
        runner.run(args.config, args.output)
    elif args.command == "visualize":
        from .visualize import generate_dashboard
        try:
            db_path = generate_dashboard(args.results_dir)
            print(f"Success! Dashboard written to: {db_path.resolve()}")
        except Exception as e:
            print(f"Error generating dashboard: {e}", file=sys.stderr)
            sys.exit(1)



if __name__ == "__main__":
    main()
