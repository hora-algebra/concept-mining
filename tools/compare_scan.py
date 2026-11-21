#!/usr/bin/env python3
"""Compare the source scan (scan_sources.py) with the exact proof-map graph.

For the declarations found by both, restricted to edges whose two ends lie in
the scanned directory, report precision and recall of the scanned edges and
the rank correlation of in-degrees.

    python3 tools/compare_scan.py --cache ~/.cache/concept-mining/proofmap --scan out/ft
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
from collections import Counter


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--scan", required=True)
    a = ap.parse_args()
    cache = os.path.expanduser(a.cache)
    sname = {}
    with open(os.path.join(a.scan, "decls.tsv")) as f:
        next(f)
        for row in f:
            c = row.split("\t")
            sname[int(c[0])] = c[1]
    sedges = set()
    with open(os.path.join(a.scan, "edges.tsv")) as f:
        next(f)
        for row in f:
            i, j = map(int, row.split())
            if sname[i] and sname[j]:
                sedges.add((sname[i], sname[j]))
    wanted = set(sname.values())

    meta = json.load(open(os.path.join(cache, "lean_meta.json")))
    n, chunk = meta["points"], meta["chunk"]
    pos_name: dict[int, str] = {}
    deps: dict[str, list[int]] = {}
    for k in range((n + chunk - 1) // chunk):
        nn = json.load(gzip.open(os.path.join(cache, "lean", "n", f"{k}.json.gz")))
        nn = nn["n"] if isinstance(nn, dict) else nn
        hit = [i for i, x in enumerate(nn) if x in wanted]
        for i, x in enumerate(nn):
            pos_name[k * chunk + i] = x
        if not hit:
            continue
        d = json.load(gzip.open(os.path.join(cache, "lean", "d", f"{k}.json.gz")))
        for i in hit:
            v, out = 0, []
            for x in d["r"][i][6]:
                v += x
                out.append(v)
            deps[nn[i]] = out
    common = set(deps)
    xedges = {(u, pos_name[v]) for u, vs in deps.items() for v in vs if pos_name.get(v) in common}
    sedges = {(u, v) for (u, v) in sedges if u in common and v in common}
    tp = len(sedges & xedges)
    res = {
        "scanned_declarations": len([x for x in sname.values() if x]),
        "matched_in_exact_graph": len(common),
        "exact_edges_inside": len(xedges),
        "scanned_edges_inside": len(sedges),
        "precision": round(tp / max(1, len(sedges)), 3),
        "recall": round(tp / max(1, len(xedges)), 3),
    }
    # Spearman correlation of in-degree (inside the directory)
    xi, si = Counter(v for _, v in xedges), Counter(v for _, v in sedges)
    names = sorted(common)

    def ranks(vals):
        order = sorted(range(len(vals)), key=lambda t: vals[t])
        r = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            for t in range(i, j + 1):
                r[order[t]] = (i + j) / 2
            i = j + 1
        return r

    rx, rs = ranks([xi[x] for x in names]), ranks([si[x] for x in names])
    m = len(names)
    mx, ms = sum(rx) / m, sum(rs) / m
    cov = sum((p - mx) * (q - ms) for p, q in zip(rx, rs))
    vx = sum((p - mx) ** 2 for p in rx) ** 0.5
    vs = sum((q - ms) ** 2 for q in rs) ** 0.5
    res["spearman_in_degree"] = round(cov / (vx * vs), 3) if vx and vs else None
    top_x = {x for x, _ in xi.most_common(50)}
    top_s = {x for x, _ in si.most_common(50)}
    res["top50_overlap"] = len(top_x & top_s)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
