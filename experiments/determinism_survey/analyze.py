"""
Tables for README.md from results/*.json (one file per OS x Python run of
survey.py, as uploaded by .github/workflows/determinism-survey.yml).

1. For each scenario: is the output bit-identical on every OS x Python
   combination? If not, which combinations agree with each other?
2. For each libm scenario: between each pair of operating systems, how many
   of the 2,000 blocks of 100 outputs differ -- so how often the platform
   math library gives a different result.

    python analyze.py
"""
from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
OS_ORDER = {"Linux": 0, "Darwin": 1, "Windows": 2}
OS_NAME = {"Linux": "Linux", "Darwin": "macOS", "Windows": "Windows"}


def main() -> None:
    reps = sorted((json.loads(p.read_text()) for p in (HERE / "results").glob("*.json")),
                  key=lambda r: (OS_ORDER[r["os"]], r["python"]))
    combos = [f"{OS_NAME[r['os']]} {'.'.join(r['python'].split('.')[:2])}" for r in reps]
    versions = {json.dumps(r["versions"], sort_keys=True) for r in reps}
    print(f"{len(reps)} runs: {', '.join(combos)}.")
    print(f"Library versions identical in every run: {len(versions) == 1} "
          f"({json.loads(versions.pop()) if len(versions) == 1 else 'NO'})\n")

    print("| Scenario | Same seed, same output everywhere? | Groups of identical output |")
    print("|---|---|---|")
    for name in reps[0]["scenarios"]:
        hashes = [r["scenarios"][name].get("hash") for r in reps]
        repeat = all(r["scenarios"][name].get("repeatable") for r in reps)
        groups = {}
        for c, h in zip(combos, hashes):
            groups.setdefault(h, []).append(c)
        if len(groups) == 1:
            verdict, detail = "**yes**", f"all {len(reps)}"
        else:
            verdict = f"no: {len(groups)} different results"
            detail = "; ".join(_compact(g) for g in groups.values())
        if not repeat:
            verdict += " (not even repeatable in one run)"
        print(f"| `{name}` | {verdict} | {detail} |")

    print("\nHow often the platform math library disagrees: blocks of 100 outputs "
          "(of 2,000) that differ between operating systems, Python 3.12:\n")
    by_os = {r["os"]: r for r in reps if r["python"].startswith("3.12")}
    pairs = list(combinations(sorted(by_os, key=OS_ORDER.get), 2))
    print("| Function | " + " | ".join(f"{OS_NAME[a]} vs {OS_NAME[b]}" for a, b in pairs) + " |")
    print("|---|" + "---:|" * len(pairs))
    for name in reps[0]["scenarios"]:
        if not name.startswith("libm/"):
            continue
        cells = []
        for a, b in pairs:
            ba, bb = by_os[a]["scenarios"][name]["blocks"], by_os[b]["scenarios"][name]["blocks"]
            cells.append(str(sum(x != y for x, y in zip(ba, bb))))
        print(f"| `{name[5:]}` | " + " | ".join(cells) + " |")


def _compact(group):
    by_os = {}
    for c in group:
        os_, ver = c.split(" ")
        by_os.setdefault(os_, []).append(ver)
    return ", ".join(f"{os_} {'/'.join(v)}" for os_, v in by_os.items())


if __name__ == "__main__":
    main()
