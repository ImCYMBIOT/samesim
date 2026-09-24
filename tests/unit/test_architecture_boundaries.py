"""
Architectural boundary test: every layer may import only the layers beneath it.

    domain   ->  (nothing internal)
    ports    ->  domain
    core     ->  domain, ports
    plugins  ->  domain, ports            (never core, never app)
    app      ->  domain, ports, core
    cli      ->  app, domain

This is the architecture firewall. The rule it protects -- "the core never
knows what it's simulating, and a plugin can never touch the core" -- is the
project's central claim, so the test must be impossible to fool.

It used to be foolable in three ways, and the first was being exploited:

1. **Relative imports were invisible.** It compared ImportFrom.module against
   "simul8.core", but `from ...core.agent_registry import X` is recorded by
   the AST as module="core.agent_registry", level=3 -- never a match. Two
   metric plugins imported core classes this way and received the live,
   mutable AgentRegistry through a duck-typed configure() back door, and
   the suite stayed green.
2. **A file that failed to parse passed.** `except SyntaxError: return []`
   treated an unreadable file as one with no imports.
3. **`__init__.py` files were skipped** entirely.

All three are closed here: imports are resolved to absolute module names
before checking, parse failures fail the test, and every .py file under
simul8/ is walked -- so new layers' files and new plugins are covered
without anyone registering them.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "simul8"

ALLOWED: dict[str, frozenset[str]] = {
    "domain": frozenset({"domain"}),
    "ports": frozenset({"ports", "domain"}),
    "core": frozenset({"core", "domain", "ports"}),
    "plugins": frozenset({"plugins", "domain", "ports"}),
    "app": frozenset({"app", "domain", "ports", "core"}),
    "cli": frozenset({"cli", "app", "domain"}),
}


def _module_name(path: Path) -> str:
    rel = path.relative_to(PACKAGE_ROOT.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _package_of(path: Path) -> list[str]:
    """The package a relative import in this file is resolved against."""
    name = _module_name(path).split(".")
    return name if path.name == "__init__.py" else name[:-1]


def _absolute_imports(path: Path) -> list[tuple[int, str]]:
    # Deliberately no try/except: a file that cannot be parsed cannot be
    # checked, and must fail rather than pass as "no imports".
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                found.append((node.lineno, node.module or ""))
            else:
                base = _package_of(path)
                if node.level - 1 > len(base):
                    found.append((node.lineno, "<relative import beyond top-level package>"))
                    continue
                base = base[: len(base) - (node.level - 1)]
                found.append((node.lineno, ".".join(base + ([node.module] if node.module else []))))
    return found


def _layer(module: str) -> str | None:
    parts = module.split(".")
    return parts[1] if len(parts) > 1 and parts[0] == "simul8" else None


SOURCE_FILES = sorted(p for p in PACKAGE_ROOT.rglob("*.py") if "__pycache__" not in p.parts)


def test_discovery_found_the_sources():
    """Guard the guard -- an empty walk would pass silently."""
    assert len(SOURCE_FILES) >= 30, f"Expected to discover sources, got {len(SOURCE_FILES)}"
    layers = {_layer(_module_name(p)) for p in SOURCE_FILES}
    assert set(ALLOWED) <= layers, f"Missing layers: {set(ALLOWED) - layers}"


def test_every_layer_is_governed():
    """A new top-level subpackage must be given explicit rules, not a free pass."""
    layers = {
        _layer(_module_name(p)) for p in SOURCE_FILES
        if _layer(_module_name(p)) is not None and len(_module_name(p).split(".")) > 2
    }
    ungoverned = layers - set(ALLOWED)
    assert not ungoverned, (
        f"Subpackage(s) {sorted(ungoverned)} have no entry in ALLOWED. Decide "
        f"which layers they may import and add them."
    )


@pytest.mark.parametrize("path", SOURCE_FILES, ids=lambda p: _module_name(p))
def test_imports_respect_layering(path):
    source_layer = _layer(_module_name(path))
    if source_layer not in ALLOWED:
        pytest.skip("top-level module; governed by test_every_layer_is_governed")

    violations = []
    for lineno, module in _absolute_imports(path):
        if module.startswith("<"):
            violations.append(f"  line {lineno}: {module}")
            continue
        target = _layer(module)
        if target is not None and target not in ALLOWED[source_layer]:
            violations.append(f"  line {lineno}: imports {module} ({source_layer} -> {target})")

    assert not violations, (
        f"{_module_name(path)} breaks the layering. '{source_layer}' may import "
        f"only {sorted(ALLOWED[source_layer])}:\n" + "\n".join(violations)
    )
