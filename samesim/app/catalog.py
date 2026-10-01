"""
Catalog — the shipped example configs and every installed plugin, for the CLI.

Plugins are found by walking samesim.plugins, the same way the contract
tests find them, so a new plugin appears in `samesim plugins` without being
registered anywhere. What each one does and which options it takes are read
from its module docstring: the first line, and the indented block under a
line starting with "Configuration" or "Config keys" -- the format every
shipped plugin documents itself in.

Imports plugin modules dynamically (importlib), as PluginLoader does, so
the app layer still has no static dependency on plugins.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
from dataclasses import dataclass
from pathlib import Path

from ..ports.behavior import BehaviorPort
from ..ports.communication import CommunicationProtocolPort
from ..ports.metric_collector import MetricCollectorPort
from ..ports.persistence import PersistencePort
from ..ports.topology_dynamics import TopologyDynamicsPort
from ..ports.topology_generator import TopologyGeneratorPort

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"

# Plugin kind -> (port it implements, config key in `plugins:`).
KINDS: dict[str, tuple[type, str]] = {
    "behavior": (BehaviorPort, "behavior"),
    "communication": (CommunicationProtocolPort, "communication"),
    "topology": (TopologyGeneratorPort, "topology"),
    "dynamics": (TopologyDynamicsPort, "dynamics"),
    "metric": (MetricCollectorPort, "metrics"),
    "persistence": (PersistencePort, "persistence"),
}


@dataclass(frozen=True)
class PluginInfo:
    kind: str
    name: str            # class name, also its plugin_configs key
    path: str            # dotted path for the config file
    summary: str         # first line of the module docstring
    options: str         # the docstring's configuration block, as written
    activation: tuple[str, ...] = ()  # behaviors only


@dataclass(frozen=True)
class ExampleInfo:
    name: str
    path: Path
    summary: str


def list_examples() -> list[ExampleInfo]:
    """Every shipped example config, with its leading comment as a summary."""
    out = []
    for path in sorted(EXAMPLES_DIR.glob("*.yaml")):
        comment = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("#"):
                break
            comment.append(line.lstrip("# ").strip())
        out.append(ExampleInfo(name=path.stem, path=path, summary=" ".join(comment)))
    return out


def find_example(name: str) -> ExampleInfo | None:
    return next((e for e in list_examples() if e.name == name), None)


def discover_plugins() -> list[PluginInfo]:
    """Every concrete plugin class under samesim.plugins, sorted by kind and name."""
    plugins_pkg = importlib.import_module("samesim.plugins")
    found: dict[str, PluginInfo] = {}
    for mod_info in pkgutil.walk_packages(plugins_pkg.__path__, prefix="samesim.plugins."):
        if mod_info.ispkg:
            continue
        module = importlib.import_module(mod_info.name)
        summary, options = _describe(inspect.getdoc(module) or "")
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ != module.__name__ or inspect.isabstract(cls):
                continue
            for kind, (port, _) in KINDS.items():
                if issubclass(cls, port) and cls is not port:
                    path = f"{module.__name__}.{cls.__name__}"
                    activation = tuple(sorted(getattr(cls, "activation_modes", ()))) if kind == "behavior" else ()
                    found[path] = PluginInfo(kind=kind, name=cls.__name__, path=path,
                                             summary=summary, options=options, activation=activation)
    order = list(KINDS)
    return sorted(found.values(), key=lambda p: (order.index(p.kind), p.name))


def find_plugin(name: str) -> PluginInfo | None:
    """By class name (case-insensitive) or dotted path."""
    for p in discover_plugins():
        if name in (p.path, p.name) or name.lower() == p.name.lower():
            return p
    return None


def _describe(doc: str) -> tuple[str, str]:
    lines = doc.splitlines()
    summary = lines[0].strip() if lines else ""
    # "QueueBehavior — a single-server ..." -> "a single-server ..."
    summary = re.sub(r"^\w+\s*[—-]+\s*", "", summary)
    options: list[str] = []
    capturing = False
    for line in lines[1:]:
        if re.match(r"^(Configuration|Config keys)\b", line.strip()) and not line.startswith(" "):
            capturing = True
            head = line.split(":", 1)[1].strip() if ":" in line else ""
            if head:
                options.append(head)
            continue
        if capturing:
            if line.strip() and not line.startswith((" ", "\t")):
                break
            options.append(line)
    text = "\n".join(options).strip("\n")
    return summary, _dedent(text)


def _dedent(text: str) -> str:
    lines = text.splitlines()
    indents = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    cut = min(indents) if indents else 0
    return "\n".join(l[cut:] for l in lines).strip()
