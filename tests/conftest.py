"""Suite-wide pytest options."""
from __future__ import annotations


def pytest_addoption(parser):
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help=(
            "Re-record tests/regression/golden/traces.json instead of checking "
            "against it. Only for changes that are MEANT to alter simulation "
            "output -- the resulting diff must be reviewed like code."
        ),
    )
