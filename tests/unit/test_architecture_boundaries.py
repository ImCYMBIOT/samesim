"""
Architectural boundary test: plugins must not import from simul8.core or simul8.app.

This is the "architecture firewall" test. It parses all plugin source files
and greps for forbidden import statements. If any are found, the test fails
and lists the violations.

Why this matters:
    The core engine must remain independent of research plugins.
    A plugin that imports from core creates a circular dependency that
    would break the plugin architecture and prevent future Rust porting.
"""
from __future__ import annotations

import ast
from pathlib import Path


PLUGINS_ROOT = Path(__file__).parent.parent.parent / "simul8" / "plugins"
FORBIDDEN_PREFIXES = ("simul8.core", "simul8.app")


def _get_imports(filepath: Path) -> list[str]:
    """Extract all imported module names from a Python file."""
    try:
        tree = ast.parse(filepath.read_text(encoding="utf-8"))
    except SyntaxError:
        return []

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


def test_plugins_do_not_import_from_core_or_app():
    """No plugin file may import from simul8.core or simul8.app."""
    violations: list[str] = []

    for filepath in PLUGINS_ROOT.rglob("*.py"):
        if filepath.name == "__init__.py":
            continue
        for imp in _get_imports(filepath):
            if any(imp.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
                violations.append(
                    f"  {filepath.relative_to(PLUGINS_ROOT.parent.parent)}: "
                    f"forbidden import '{imp}'"
                )

    if violations:
        violation_list = "\n".join(violations)
        raise AssertionError(
            f"Architecture violation: plugins must not import from simul8.core or simul8.app.\n"
            f"Violations found:\n{violation_list}"
        )
