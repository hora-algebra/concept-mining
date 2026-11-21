#!/usr/bin/env python3
"""Baseline of one folder of CFSG ("the target") from the proof-map graph.

    python3 tools/island.py --cache ~/.cache/concept-mining/proofmap \
        --prefix CFSG.FeitThompson --out data/pilot/FeitThompson

Writes
    decls.tsv      every declaration of the target: name, kind, module, line,
                   lines, reachable from the final theorem, users inside and
                   outside the target
    protected.txt  the declarations of the target that something outside the
                   target uses and that the final theorem needs (with
                   --milestones: or one of the statements under
                   CFSG.Milestones); their statements and axioms must not
                   change
    unreachable_modules.tsv  modules of the target whose declarations the
                   final theorem never needs, with their lines
    summary.json   totals (lines, reachable lines, declarations, ...)

Standard library only (reuses the loader of analyze_proofmap.py).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from array import array
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_proofmap import load  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--prefix", required=True, help="module prefix, e.g. CFSG.FeitThompson")
    ap.add_argument("--out", required=True)
    ap.add_argument("--milestones", action="store_true",
                    help="also keep everything the CFSG.Milestones statements need")
    a = ap.parse_args()
    meta, kinds, mods, kind, module, line, lines, idom, names, dep_off, deps = load(os.path.expanduser(a.cache))
    n, final = meta["points"], meta["final"]
    inside_mod = {m for m, s in mods.items() if s == a.prefix or s.startswith(a.prefix + ".")}
    inside = bytearray(n)
    for p in range(n):
        if module[p] in inside_mod:
            inside[p] = 1

    reach = bytearray(n)
    roots = [final] + ([m["p"] for m in meta.get("milestones", [])] if a.milestones else [])
    for r in roots:
        reach[r] = 1
    stack = list(roots)
    while stack:
        u = stack.pop()
        for e in range(dep_off[u], dep_off[u + 1]):
            v = deps[e]
            if not reach[v]:
                reach[v] = 1
                stack.append(v)

    uin = array("i", [0]) * n
    uout = array("i", [0]) * n
    out_edges = 0
    for u in range(n):
        for e in range(dep_off[u], dep_off[u + 1]):
            v = deps[e]
            if inside[v]:
                if inside[u]:
                    uin[v] += 1
                else:
                    uout[v] += 1
            elif inside[u]:
                out_edges += 1

    os.makedirs(a.out, exist_ok=True)
    ids = [p for p in range(n) if inside[p]]
    ids.sort(key=lambda p: (mods[module[p]], line[p]))
    with open(os.path.join(a.out, "decls.tsv"), "w") as w:
        w.write("name\tkind\tmodule\tline\tlines\treachable\tusers_inside\tusers_outside\n")
        for p in ids:
            w.write(f"{names[p]}\t{kinds[kind[p]]}\t{mods[module[p]]}\t{line[p]}\t{lines[p]}\t{reach[p]}\t{uin[p]}\t{uout[p]}\n")
    prot = sorted(names[p] for p in ids if uout[p] > 0 and reach[p])
    with open(os.path.join(a.out, "protected.txt"), "w") as w:
        w.write("\n".join(prot) + "\n")
    ml, mr = Counter(), Counter()
    for p in ids:
        ml[module[p]] += lines[p]
        mr[module[p]] += lines[p] if reach[p] else 0
    with open(os.path.join(a.out, "unreachable_modules.tsv"), "w") as w:
        w.write("module\tlines\treachable_lines\n")
        for m in sorted(ml, key=lambda m: -(ml[m] - mr[m])):
            if ml[m] > mr[m]:
                w.write(f"{mods[m]}\t{ml[m]}\t{mr[m]}\n")
    s = {
        "target": a.prefix,
        "graph_commit": meta["commit"],
        "modules": len(inside_mod),
        "declarations": len(ids),
        "declaration_lines": sum(lines[p] for p in ids),
        "reachable_declarations": sum(reach[p] for p in ids),
        "reachable_lines": sum(lines[p] for p in ids if reach[p]),
        "protected": len(prot),
        "edges_to_outside": out_edges,
        "single_user_declarations": sum(1 for p in ids if uin[p] + uout[p] == 1),
    }
    with open(os.path.join(a.out, "summary.json"), "w") as w:
        json.dump(s, w, indent=2)
    print(json.dumps(s, indent=2))


if __name__ == "__main__":
    main()
