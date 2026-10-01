"""
Contract test: no committed script may hardcode a machine-specific path.

Every experiments/ README tells a reader to "run it yourself". That promise
was false for months: ten scripts hardcoded an absolute repo root under one
developer's home directory, and five more wrote their results into an
agent session's scratchpad directory whose name contained a UUID. Nothing
failed loudly -- the scripts ran fine on the one machine they were written
on, which is exactly why nobody noticed.

Same reasoning as the other two contract tests: this DISCOVERS scripts by
walking the tree, so a newly added experiment is covered without anyone
remembering to register it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIRS = ("experiments", "samesim", "tests")

# An absolute path into a user's home, a temp dir, or a Windows drive is
# never legitimate in committed code. Paths under /usr, /etc and similar
# are fine -- those exist on every machine.
FORBIDDEN = re.compile(
    r"""["'](?:/home/|/Users/|/tmp/|/var/folders/|[A-Za-z]:\\\\)[^"']*["']"""
)


def _scripts() -> list[Path]:
    found: list[Path] = []
    for d in SCRIPT_DIRS:
        found.extend(sorted((REPO_ROOT / d).rglob("*.py")))
    return [p for p in found if "__pycache__" not in p.parts]


SCRIPTS = _scripts()


def test_discovery_found_the_scripts():
    """Guard the guard -- an empty sweep would pass silently."""
    assert len(SCRIPTS) >= 20, f"Expected to discover scripts, got {len(SCRIPTS)}"


@pytest.mark.parametrize(
    "script", SCRIPTS, ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_no_machine_specific_absolute_paths(script):
    hits = []
    for lineno, line in enumerate(script.read_text().splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue  # a path in prose is documentation, not a dependency
        for match in FORBIDDEN.finditer(line):
            hits.append(f"  line {lineno}: {match.group(0)}")

    assert not hits, (
        f"{script.relative_to(REPO_ROOT)} hardcodes machine-specific "
        f"path(s), so it only runs on the machine it was written on:\n"
        + "\n".join(hits)
        + "\n\nDerive the repo root from the file instead "
        "(Path(__file__).resolve().parents[N]), write outputs next to the "
        "script, and make any scratch location overridable by environment "
        "variable."
    )
