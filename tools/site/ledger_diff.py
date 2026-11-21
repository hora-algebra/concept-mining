#!/usr/bin/env python3
"""Print, as Markdown, the ledger rows added or changed since a base revision.

    python3 tools/site/ledger_diff.py --base origin/main

Used by CI to summarize a pull request. Standard library only.
"""

from __future__ import annotations

import argparse
import subprocess


def rows(rev: str | None, path: str) -> list[str]:
    try:
        if rev is None:
            text = open(path, encoding="utf-8").read()
        else:
            text = subprocess.run(["git", "show", f"{rev}:{path}"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return [r for r in text.splitlines()[1:] if r.strip()]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True)
    a = ap.parse_args()
    print("## Ledger changes\n")
    any_change = False
    for path, cols in (("data/ledger/concepts.tsv", ["date", "target", "concept", "lines saved"]),
                       ("data/ledger/history.tsv", ["date", "target", "lines total"])):
        old, new = set(rows(a.base, path)), rows(None, path)
        added = [r.split("\t") for r in new if r not in old]
        removed = [r for r in old if r not in set(new)]
        if not added and not removed:
            continue
        any_change = True
        print(f"**{path}**: {len(added)} rows added, {len(removed)} rows removed or changed\n")
        if added:
            print("| " + " | ".join(cols) + " |\n|" + "---|" * len(cols))
            for r in added:
                pick = [r[0], r[1], r[2], r[6]] if "concepts" in path and len(r) > 6 else r[:3]
                print("| " + " | ".join(x.replace("|", "\\|") for x in pick) + " |")
            print()
    if not any_change:
        print("No change to the ledger.")


if __name__ == "__main__":
    main()
