#!/usr/bin/env python3
"""Summaries of the CFSG declaration graph mirrored by fetch_proofmap.py.

    python3 tools/analyze_proofmap.py --cache ~/.cache/concept-mining/proofmap --out data/map

Every edge u -> v means "the elaborated declaration u refers to v" (both inside
the CFSG project; Mathlib and TauCeti are outside the graph). From that it
computes

    folders.tsv          per top-level folder: declarations, lines, files,
                         reachable from the final theorem, edges in/out
    folder_edges.tsv     edges between top-level folders
    top_used.tsv         declarations with the most direct users
    top_used_by_folder.tsv  the 15 most used declarations of each folder
    unreachable.tsv      per folder: declarations and lines the final theorem
                         does not depend on
    parallel_definitions.tsv  definitions with the same normalized name in
                         different namespaces (candidate duplicated concepts)
    regions.tsv          dominator regions: declarations v together with all
                         declarations that reach the final theorem only
                         through v; sizes in lines (pilot candidates)
    name_families.tsv    final name components shared by many declarations in
                         different namespaces (candidate duplicated arguments)
    milestones.tsv       the milestone theorems listed by the site, by proof size
    summary.json

Standard library only; needs about 3 GB of memory for the full graph.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
from array import array
from collections import Counter, defaultdict


def load(cache: str):
    with open(os.path.join(cache, "lean_meta.json")) as f:
        meta = json.load(f)
    n, chunk = meta["points"], meta["chunk"]
    kinds_tab: dict[str, int] = {}
    mods_tab: dict[str, int] = {}
    kind = array("b", bytes(n))
    module = array("i", [0]) * n
    line = array("i", [0]) * n
    lines = array("i", [0]) * n
    idom = array("i", [0]) * n
    names: list[str] = [""] * n
    dep_off = array("q", [0]) * (n + 1)
    deps = array("i")
    for k in range((n + chunk - 1) // chunk):
        with gzip.open(os.path.join(cache, "lean", "d", f"{k}.json.gz")) as f:
            d = json.load(f)
        with gzip.open(os.path.join(cache, "lean", "n", f"{k}.json.gz")) as f:
            nn = json.load(f)
        nn = nn["n"] if isinstance(nn, dict) else nn
        mods = [mods_tab.setdefault(m, len(mods_tab)) for m in d["m"]]
        for i, r in enumerate(d["r"]):
            p = k * chunk + i
            kind[p] = kinds_tab.setdefault(r[0], len(kinds_tab))
            module[p] = mods[r[1]]
            line[p], lines[p] = r[2], r[3]
            idom[p] = r[13] if len(r) > 13 and r[13] is not None else -1
            names[p] = nn[i] or ""
            v = 0
            for x in r[6]:
                v += x
                deps.append(v)
            dep_off[p + 1] = len(deps)
            if len(r[6]) != r[7]:
                print(f"warning: deps of {p} truncated ({len(r[6])} of {r[7]})", file=sys.stderr)
        if k % 100 == 0:
            print(f"loaded chunk {k}", file=sys.stderr)
    kinds = {v: k for k, v in kinds_tab.items()}
    mods = {v: k for k, v in mods_tab.items()}
    return meta, kinds, mods, kind, module, line, lines, idom, names, dep_off, deps


def top_folder(mod: str) -> str:
    parts = mod.split(".")
    return ".".join(parts[:2]) if parts[0] == "CFSG" and len(parts) > 1 else parts[0]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--top", type=int, default=1000)
    a = ap.parse_args()
    meta, kinds, mods, kind, module, line, lines, idom, names, dep_off, deps = load(os.path.expanduser(a.cache))
    n = meta["points"]
    final = meta["final"]
    os.makedirs(a.out, exist_ok=True)
    folder_of_mod = {m: top_folder(s) for m, s in mods.items()}
    fold = [folder_of_mod[module[p]] for p in range(n)]

    # in-degree
    indeg = array("i", [0]) * n
    for v in deps:
        indeg[v] += 1

    # reachability from the final theorem
    reach = bytearray(n)
    stack = [final]
    reach[final] = 1
    while stack:
        u = stack.pop()
        for e in range(dep_off[u], dep_off[u + 1]):
            v = deps[e]
            if not reach[v]:
                reach[v] = 1
                stack.append(v)

    # folder table and folder edges
    F = defaultdict(lambda: Counter())
    files_of = defaultdict(set)
    fe = Counter()
    for u in range(n):
        f = fold[u]
        c = F[f]
        c["declarations"] += 1
        c["lines"] += lines[u]
        c["reachable"] += reach[u]
        c["reachable_lines"] += lines[u] if reach[u] else 0
        c["theorems"] += kinds[kind[u]] == "theorem"
        files_of[f].add(module[u])
        for e in range(dep_off[u], dep_off[u + 1]):
            g = fold[deps[e]]
            fe[(f, g)] += 1
            if g != f:
                c["edges_out"] += 1
                F[g]["edges_in"] += 1
            else:
                c["edges_internal"] += 1
    with open(os.path.join(a.out, "folders.tsv"), "w") as w:
        cols = ["declarations", "theorems", "lines", "reachable", "reachable_lines", "edges_internal", "edges_out", "edges_in"]
        w.write("folder\tfiles\t" + "\t".join(cols) + "\n")
        for f, c in sorted(F.items(), key=lambda x: -x[1]["lines"]):
            w.write(f"{f}\t{len(files_of[f])}\t" + "\t".join(str(c[k]) for k in cols) + "\n")
    with open(os.path.join(a.out, "folder_edges.tsv"), "w") as w:
        w.write("from\tto\tedges\n")
        for (f, g), k in fe.most_common():
            if f != g and k >= 100:
                w.write(f"{f}\t{g}\t{k}\n")

    # most used declarations
    order = sorted(range(n), key=lambda p: -indeg[p])
    users_folders = defaultdict(set)
    top = order[: a.top]
    topset = set(top)
    for u in range(n):
        for e in range(dep_off[u], dep_off[u + 1]):
            v = deps[e]
            if v in topset:
                users_folders[v].add(fold[u])
    hdr = "rank\tname\tkind\tmodule\tlines\tusers\tuser_folders\treachable\n"
    with open(os.path.join(a.out, "top_used.tsv"), "w") as w:
        w.write(hdr)
        for r, p in enumerate(top, 1):
            w.write(f"{r}\t{names[p]}\t{kinds[kind[p]]}\t{mods[module[p]]}\t{lines[p]}\t{indeg[p]}\t{len(users_folders[p])}\t{reach[p]}\n")
    per = defaultdict(list)
    for p in order:
        if len(per[fold[p]]) < 15 and indeg[p] > 0:
            per[fold[p]].append(p)
    with open(os.path.join(a.out, "top_used_by_folder.tsv"), "w") as w:
        w.write("folder\tname\tkind\tlines\tusers\n")
        for f in sorted(per, key=lambda f: -F[f]["lines"]):
            for p in per[f]:
                w.write(f"{f}\t{names[p]}\t{kinds[kind[p]]}\t{lines[p]}\t{indeg[p]}\n")

    # unreachable code
    with open(os.path.join(a.out, "unreachable.tsv"), "w") as w:
        w.write("folder\tdeclarations\tlines\tshare_of_folder_lines\n")
        for f, c in sorted(F.items(), key=lambda x: -(x[1]["lines"] - x[1]["reachable_lines"])):
            ul = c["lines"] - c["reachable_lines"]
            w.write(f"{f}\t{c['declarations'] - c['reachable']}\t{ul}\t{ul / max(1, c['lines']):.3f}\n")

    # dominator regions (idom supplied by the site, rooted at the final theorem)
    region_lines = array("q", [0]) * n
    region_size = array("i", [0]) * n
    children = defaultdict(list)
    for p in range(n):
        if reach[p] and idom[p] >= 0 and p != final:
            children[idom[p]].append(p)
    # post-order accumulation
    order_dfs = []
    stack = [final]
    while stack:
        u = stack.pop()
        order_dfs.append(u)
        stack.extend(children.get(u, ()))
    for u in reversed(order_dfs):
        region_lines[u] += lines[u]
        region_size[u] += 1
        if u != final and idom[u] >= 0:
            region_lines[idom[u]] += region_lines[u]
            region_size[idom[u]] += region_size[u]
    # candidate regions in three size bands; skip a region whose parent region
    # is barely larger (it is the same region seen one level up)
    bands = [(1000, 5000), (5000, 20000), (20000, 60000)]
    with open(os.path.join(a.out, "regions.tsv"), "w") as w:
        w.write("band\tname\tkind\tfolder\tregion_declarations\tregion_lines\tusers_of_root\tparent\n")
        for lo, hi in bands:
            cand = [p for p in order_dfs if lo <= region_lines[p] < hi and p != final]
            candset = set(cand)
            keep = [p for p in cand if not (idom[p] in candset and region_lines[idom[p]] < 1.5 * region_lines[p])]
            keep.sort(key=lambda p: -region_lines[p])
            for p in keep[:150]:
                w.write(f"{lo}-{hi}\t{names[p]}\t{kinds[kind[p]]}\t{fold[p]}\t{region_size[p]}\t{region_lines[p]}\t{indeg[p]}\t{names[idom[p]] if idom[p] >= 0 else ''}\n")

    # parallel vocabularies: definitions whose normalized final name component
    # coincides across namespaces (e.g. pCore / pCoreOf, IsSylowOf / IsSylowTwoOf)
    def norm(last: str) -> str:
        x = last.lower()
        x = re.sub(r"^is", "", x)
        x = re.sub(r"(of|in|data)$", "", x)
        return x
    defs = defaultdict(list)
    for p in range(n):
        if kinds[kind[p]] in ("def", "abbrev", "structure", "class", "inductive") and indeg[p] >= 20:
            last = names[p].rsplit(".", 1)[-1]
            if len(last) >= 4:
                defs[norm(last)].append(p)
    rows = []
    for key, ps in defs.items():
        nss = {names[p].rsplit(".", 1)[0] for p in ps}
        if len(nss) >= 2:
            tot = sum(indeg[p] for p in ps)
            rows.append((tot, key, ps))
    rows.sort(key=lambda r: -r[0])
    with open(os.path.join(a.out, "parallel_definitions.tsv"), "w") as w:
        w.write("key\tcopies\ttotal_users\tdefinitions(users)\n")
        for tot, key, ps in rows[:300]:
            ps = sorted(ps, key=lambda p: -indeg[p])
            w.write(f"{key}\t{len(ps)}\t{tot}\t" + "; ".join(f"{names[p]}({indeg[p]})" for p in ps[:12]) + "\n")

    # name families: same final component in many namespaces
    fam = defaultdict(list)
    for p in range(n):
        last = names[p].rsplit(".", 1)[-1]
        if len(last) >= 12 and not last.startswith("_") and not re.fullmatch(r"(proof|match|eq|mk|inst)_?\d*", last):
            fam[last].append(p)
    rows = []
    for last, ps in fam.items():
        if len(ps) >= 8:
            nss = {names[p].rsplit(".", 1)[0] for p in ps}
            if len(nss) >= 8:
                rows.append((len(ps), sum(lines[p] for p in ps), len({fold[p] for p in ps}), last, names[ps[0]]))
    rows.sort(key=lambda r: -r[1])
    with open(os.path.join(a.out, "name_families.tsv"), "w") as w:
        w.write("final_component\tcopies\ttotal_lines\tfolders\texample\n")
        for c, l, nf, last, ex in rows[:500]:
            w.write(f"{last}\t{c}\t{l}\t{nf}\t{ex}\n")

    # milestones named by the upstream site, with the size of their proofs
    with open(os.path.join(a.out, "milestones.tsv"), "w") as w:
        w.write("title\tcategory\tdeclaration\tstatement_lines\tproof_lines\n")
        for m in sorted(meta["milestones"], key=lambda m: m.get("proof_lines", 0)):
            p = m.get("p", -1)
            w.write(f"{m['title']}\t{m.get('category', '')}\t{names[p] if 0 <= p < n else ''}\t{m.get('lines', '')}\t{m.get('proof_lines', '')}\n")

    kc = Counter(kinds[kind[p]] for p in range(n))
    summary = {
        "commit": meta["commit"], "declarations": n, "edges": len(deps),
        "edges_reported": meta["counts"]["links"], "kinds": dict(kc),
        "lines_in_declarations": sum(lines), "reachable_from_final": sum(reach),
        "reachable_reported": meta["counts"]["in_final"],
        "unreachable_lines": sum(lines[p] for p in range(n) if not reach[p]),
        "declarations_with_no_users": sum(1 for p in range(n) if indeg[p] == 0),
        "declarations_with_one_user": sum(1 for p in range(n) if indeg[p] == 1),
        "final": names[final],
    }
    with open(os.path.join(a.out, "summary.json"), "w") as w:
        json.dump(summary, w, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
