"""
SameSim -- same seed, same simulation.

A deterministic discrete-event simulator for message-passing agents on
dynamic networks. The core manages agents, virtual time, events and message
routing; everything domain-specific is a plugin.

From Python:

    import samesim

    result = samesim.run("sir_random")                        # a shipped example
    result = samesim.run("my_study.yaml", seed=3,
                         overrides={"simulation.num_agents": 500})
    result = samesim.run({...config dict...}, output_dir="results")

    infected = result.series["sir_infected"]                  # a MetricSeries
    times = [r.virtual_time for r in infected.records]
    values = [r.value for r in infected.records]

    samesim.validate("my_study.yaml")   # every check a run does, without running

run() keeps results in memory and writes files only when output_dir is given.
"""
from .app.api import run, validate
from .app.catalog import discover_plugins, list_examples
from .app.experiment_runner import RunResult

__version__ = "0.2.1"

__all__ = ["run", "validate", "list_examples", "discover_plugins", "RunResult", "__version__"]
