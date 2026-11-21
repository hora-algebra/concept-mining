#!/usr/bin/env python3
"""First layer of the upper-bound map: code the final theorem does not need.

For every block of the map, counts the lines of declarations that the final
theorem does not depend on (directly or indirectly). Deleting them cannot
change the final theorem, so these lines are a hard upper bound for the
"dead code" method. Writes rows of data/potential/blocks.tsv with method
`dead-code`, replacing earlier rows of that method and keeping the others.

    python3 tools/site/potential_dead_code.py --cache ~/.cache/concept-mining/proofmap

Needs the exact graph downloaded by tools/fetch_proofmap.py. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from analyze_proofmap import load  # noqa: E402
from aggregate_blocks import block_of  # noqa: E402
import potential  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", default=os.path.join(ROOT, "data/potential/blocks.tsv"))
    a = ap.parse_args()
    meta, kinds, mods, kind, module, line, lines, idom, names, dep_off, deps = load(os.path.expanduser(a.cache))
    n, final = meta["points"], meta["final"]
    reach = bytearray(n)
    reach[final] = 1
    stack = [final]
    while stack:
        u = stack.pop()
        for e in range(dep_off[u], dep_off[u + 1]):
            v = deps[e]
            if not reach[v]:
                reach[v] = 1
                stack.append(v)
    with open(os.path.join(ROOT, "data/map/blocks.json"), encoding="utf-8") as fh:
        blocks = json.load(fh)
    kept = {f["folder"]: {p["part"] for p in f["parts"]} for f in blocks["folders"]}
    merged = {f["folder"]: next((p["part"] for p in f["parts"] if p["part"].endswith("other parts)")), None)
              for f in blocks["folders"]}
    dead_lines = defaultdict(int)
    dead_decls = defaultdict(int)
    mod_block = {mid: block_of(m) for mid, m in mods.items()}
    for p in range(n):
        if reach[p]:
            continue
        f, part = mod_block[module[p]]
        if part not in kept.get(f, set()):
            part = merged.get(f) or part
        dead_lines[(f, part)] += lines[p]
        dead_decls[(f, part)] += 1
    rows = [{"folder": f, "part": part, "method": "dead-code", "lines": dead_lines[(f, part)],
             "tokens": "", "evidence": f"{dead_decls[(f, part)]} declarations not needed by {names[final]}"}
            for (f, part) in sorted(dead_lines) if dead_lines[(f, part)] > 0]
    potential.replace_method(a.out, "dead-code", rows)
    print(len(rows), "blocks,", sum(r["lines"] for r in rows), "lines")


if __name__ == "__main__":
    main()
