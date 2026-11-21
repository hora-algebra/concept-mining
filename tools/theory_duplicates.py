#!/usr/bin/env python3
"""Theorems proved twice: the same statement in different files, with the size of each proof's own subtree.

The statement of each theorem is fingerprinted at source level (local names
renamed, tools/skeletons.py). For each group of theorems with the same
statement in two or more files, the proof map's dominator tree gives the
lines that only that theorem needs (its dominator region). Keeping one member
and deriving the others from it removes the other regions. The sum is an
upper bound on what deduplicating whole arguments could save.

    python3 tools/theory_duplicates.py --decls out/skeleton_decls.tsv.gz \
        --cache ~/.cache/concept-mining/proofmap --out data/map/theory_duplicates
"""
import argparse, gzip, json, os, sys
from array import array
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_proofmap import load  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decls", required=True)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    meta, kinds, mods, kind, module, line, lines, idom, names, dep_off, deps = load(os.path.expanduser(a.cache))
    n, final = meta["points"], meta["final"]
    reach = bytearray(n); reach[final] = 1; st = [final]
    while st:
        u = st.pop()
        for e in range(dep_off[u], dep_off[u + 1]):
            v = deps[e]
            if not reach[v]:
                reach[v] = 1; st.append(v)
    children = defaultdict(list)
    for p in range(n):
        if reach[p] and idom[p] >= 0 and p != final:
            children[idom[p]].append(p)
    order, st = [], [final]
    while st:
        u = st.pop(); order.append(u); st.extend(children.get(u, ()))
    region = array("q", [0]) * n
    for u in reversed(order):
        region[u] += lines[u]
        if u != final and idom[u] >= 0:
            region[idom[u]] += region[u]
    index = {names[p]: p for p in range(n)}
    groups = defaultdict(list)
    with gzip.open(a.decls, "rt", encoding="utf-8") as f:
        next(f)
        for l in f:
            c = l.rstrip("\n").split("\t")
            if len(c) < 10 or not c[9]:
                continue
            p = index.get(c[2])  # fully qualified (tools/skeletons.py tracks namespaces)
            if p is not None:
                groups[c[9]].append(p)
    rows, total = [], 0
    by_folder = defaultdict(int)
    for key, g in groups.items():
        g = sorted(set(g))
        files = {mods[module[p]] for p in g}
        if len(files) < 2:
            continue
        # a member inside another member's dominator region (e.g. a milestone
        # that just cites an assembly theorem) is not removed with it: count
        # only the part of each region that no other member owns
        def ancestors(p):
            out, q, k = set(), idom[p], 0
            while q >= 0 and q != final and k < 10000:
                out.add(q); q = idom[q]; k += 1
            return out
        anc = {p: ancestors(p) if reach[p] else set() for p in g}
        def exclusive(p):
            if not reach[p]:
                return lines[p]
            inner = [q for q in g if q != p and p in anc[q]]
            top = [q for q in inner if not any(r in anc[q] for r in inner if r != q)]
            return region[p] - sum(region[q] for q in top)
        sizes = sorted((exclusive(p), p) for p in g)
        save = sum(s for s, _ in sizes[:-1])
        if save <= 0:
            continue
        total += save
        for s, p in sizes[:-1]:
            by_folder[".".join(mods[module[p]].split(".")[1:3])] += s
        rows.append((save, len(g), len(files), names[sizes[-1][1]], " ; ".join(names[p] for _, p in sizes[:6])))
    rows.sort(key=lambda r: -r[0])
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "groups.tsv"), "w") as w:
        w.write("removable_lines\tmembers\tfiles\tkept\tmembers_smallest_first\n")
        for r in rows[:3000]:
            w.write("\t".join(map(str, r)) + "\n")
    with open(os.path.join(a.out, "regions.tsv"), "w") as w:
        w.write("region\tremovable_lines\n")
        for k, v in sorted(by_folder.items(), key=lambda x: -x[1]):
            w.write(f"{k}\t{v}\n")
    print(json.dumps({"groups": len(rows), "removable_lines": total, "share": round(total / sum(lines), 4)}))


if __name__ == "__main__":
    main()
