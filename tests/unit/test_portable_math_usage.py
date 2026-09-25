"""
Contract test: simulation code must not use platform-dependent math.

IEEE 754 guarantees bit-identical results only for +, -, *, /, sqrt and a few
exact operations. log, exp, pow, the trig functions and the random variates
built on them (expovariate, gauss, normalvariate, lognormvariate, ...) come
from the platform's C library and differ in the last bit between Linux,
macOS and Windows. In an event-driven run those bits are event times, so
the simulation itself diverges. It was found by golden traces recorded on
Linux failing on macOS and Windows.

This walks every file under simul8/core, simul8/plugins and simul8/domain,
so new code is covered automatically, and rejects:

    math.<transcendental>(...)    and  from math import <transcendental>
    <anything>.expovariate(...)   and the other libm-based random variates
    x ** y  and  pow(x, y)        (float ** calls the platform's pow())

Use simul8.domain.portable_math instead. Integer-only ** is legitimate; mark
that line with `# portable: int` to allow it.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "simul8"
SCANNED = ("core", "plugins", "domain")
EXEMPT = {ROOT / "domain" / "portable_math.py"}  # the one place allowed to build on math

TRANSCENDENTAL = {
    "log", "log1p", "log2", "log10", "exp", "exp2", "expm1", "pow",
    "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
    "sinh", "cosh", "tanh", "asinh", "acosh", "atanh",
    "erf", "erfc", "gamma", "lgamma", "cbrt", "hypot", "dist",
}
LIBM_VARIATES = {
    "expovariate", "gauss", "normalvariate", "lognormvariate", "gammavariate",
    "betavariate", "paretovariate", "weibullvariate", "vonmisesvariate", "binomialvariate",
}
ALLOW_MARK = "# portable: int"

FILES = sorted(p for d in SCANNED for p in (ROOT / d).rglob("*.py")
               if "__pycache__" not in p.parts and p not in EXEMPT)


def _violations(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))
    found = []

    def flag(node, what):
        if ALLOW_MARK not in lines[node.lineno - 1]:
            found.append(f"  line {node.lineno}: {what}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "math" and node.attr in TRANSCENDENTAL:
                flag(node, f"math.{node.attr}")
            elif node.attr in LIBM_VARIATES and not (
                    isinstance(node.value, ast.Name) and node.value.id == "portable_math"):
                flag(node, f".{node.attr}()")
        elif isinstance(node, ast.ImportFrom) and node.module == "math":
            for alias in node.names:
                if alias.name in TRANSCENDENTAL:
                    flag(node, f"from math import {alias.name}")
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            flag(node, "** operator")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "pow":
            flag(node, "pow()")
    return found


def test_discovery_found_the_sources():
    assert len(FILES) >= 30, len(FILES)


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(ROOT.parent)))
def test_no_platform_dependent_math(path):
    found = _violations(path)
    assert not found, (
        f"{path.relative_to(ROOT.parent)} uses math whose results differ between "
        f"platforms, so the same seed would give different runs on Linux, macOS "
        f"and Windows:\n" + "\n".join(found) +
        "\n\nUse simul8.domain.portable_math (log, exp, ipow, expovariate, "
        "normalvariate, lognormvariate), or x * x for squares. For integer-only "
        f"**, add `{ALLOW_MARK}` to the line."
    )
