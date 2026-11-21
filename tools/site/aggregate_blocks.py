#!/usr/bin/env python3
"""Aggregate the declaration graph into the blocks drawn on the site's map.

A block is a top-level folder of AxiomMath/CFSG split one level further
(`CFSG.LocalAnalysis.StandardType`, ...). For every block we count the lines
inside declarations, the number of declarations, and how many direct
references it receives from declarations in other blocks. Small blocks of a
folder are merged into one "other parts" block so that the map stays legible.

    python3 tools/site/aggregate_blocks.py --cache ~/.cache/concept-mining/proofmap \
        --out data/map/blocks.json

Needs the exact graph downloaded by tools/fetch_proofmap.py. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from analyze_proofmap import load  # noqa: E402


def block_of(mod: str) -> tuple[str, str]:
    """(folder, part) of a module name."""
    p = mod.split(".")
    if p[0] == "CFSG":
        if len(p) > 2:
            return p[1], p[2]
        return (p[1] if len(p) > 1 else "CFSG"), "(top)"
    # top-level libraries outside CFSG/ (Certificates, ...): keep them apart
    # from CFSG/Certificates by a suffix
    name = p[0] + "(top)"
    return name, (p[1] if len(p) > 1 else "(top)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep", type=int, default=20, help="at most this many parts kept per folder")
    ap.add_argument("--rest-share", type=float, default=0.12,
                    help="stop splitting a folder once the remaining parts are below this share")
    ap.add_argument("--min-share", type=float, default=0.015,
                    help="parts below this share of their folder are merged")
    a = ap.parse_args()
    meta, kinds, mods, kind, module, line, lines, idom, names, dep_off, deps = load(os.path.expanduser(a.cache))
    n = meta["points"]
    ids: dict[tuple[str, str], int] = {}
    mod_block = {mid: ids.setdefault(block_of(m), len(ids)) for mid, m in mods.items()}
    blk = [mod_block[module[p]] for p in range(n)]
    L = defaultdict(int); D = defaultdict(int); U = defaultdict(int)
    for p in range(n):
        b = blk[p]
        L[b] += lines[p]; D[b] += 1
        for j in range(dep_off[p], dep_off[p + 1]):
            q = blk[deps[j]]
            if q != b:
                U[q] += 1
    folders: dict[str, list[dict]] = defaultdict(list)
    for (f, part), b in ids.items():
        folders[f].append({"part": part, "lines": L[b], "decls": D[b], "used": U[b]})
    out = []
    for f, parts in folders.items():
        parts.sort(key=lambda c: -c["lines"])
        tot = sum(c["lines"] for c in parts)
        # keep the largest parts until the rest is small, or a cap is reached
        k = 0
        while k < len(parts) and k < a.keep and parts[k]["lines"] >= a.min_share * tot \
                and sum(c["lines"] for c in parts[k:]) > a.rest_share * tot:
            k += 1
        keep, rest = parts[:k], parts[k:]
        if len(rest) == 1:
            keep.append(rest[0])
        elif rest:
            keep.append({"part": f"({len(rest)} other parts)",
                         "lines": sum(c["lines"] for c in rest), "decls": sum(c["decls"] for c in rest),
                         "used": sum(c["used"] for c in rest)})
        out.append({"folder": f, "parts": keep})
    out.sort(key=lambda x: -sum(c["lines"] for c in x["parts"]))
    doc = {"source": "proof-map data of AxiomMath/CFSG", "commit": meta.get("commit", ""),
           "measure": "lines inside declarations", "folders": out}
    with open(a.out, "w") as fh:
        json.dump(doc, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write("\n")
    print(len(out), "folders,", sum(len(x["parts"]) for x in out), "blocks,",
          sum(c["lines"] for x in out for c in x["parts"]), "lines")


if __name__ == "__main__":
    main()
