#!/usr/bin/env python3
"""Families of declarations that are cases of one statement, judged by name.

Many declarations differ only in a case index written into the name:
`hcell_A3b0c1w12_0_1`, `c8FourActionChunk10_bounded`, `exists_frame` in 136
namespaces (one per group or model). Such a family is a candidate for one
general theorem plus a per-case check, or for a verified checker over a data
table. This script groups declarations by the name pattern obtained by
replacing digits and short case codes with placeholders (within a region),
and by the last name component across namespaces (across regions), and
reports what an ideal general theorem could remove: all proofs but one, each
case keeping a one-line instance.

    python3 tools/name_families.py --decls out/skeleton_decls.tsv.gz --out data/map/name_families
"""
import argparse, gzip, json, os, re
from collections import defaultdict


def pattern(name):
    last = name.split(".")[-1]
    p = re.sub(r"\d+", "#", last)
    p = re.sub(r"(?<=[_#])[A-Za-z](?=[#_]|$)", "?", p)  # one-letter case codes
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decls", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--min", type=int, default=5)
    a = ap.parse_args()
    rows = []
    with gzip.open(a.decls, "rt", encoding="utf-8") as f:
        next(f)
        for l in f:
            c = l.rstrip("\n").split("\t")
            rows.append((c[0], c[1], c[2], int(c[3]), int(c[4])))
    region_lines = defaultdict(int)
    for r in rows:
        region_lines[r[0]] += r[3]
    fam = defaultdict(list)
    for i, r in enumerate(rows):
        if "#" in pattern(r[2]) or "?" in pattern(r[2]):
            fam[(r[0], pattern(r[2]))].append(i)
    cross = defaultdict(list)
    for i, r in enumerate(rows):
        cross[r[2].split(".")[-1]].append(i)
    removable = defaultdict(float)
    out = []
    used = set()
    for (reg, p), g in fam.items():
        if len(g) < a.min:
            continue
        pl = sorted(rows[i][4] for i in g)
        save = sum(max(0, x - 1) for x in pl) - pl[len(pl) // 2]
        removable[reg] += save
        used.update(g)
        out.append((save, len(g), reg, p, sum(rows[i][3] for i in g)))
    cross_rows = []
    for name, g in cross.items():
        g = [i for i in g if i not in used]
        regs = {rows[i][0] for i in g}
        if len(g) < a.min or len(name) < 6 or len(regs) < 2:
            continue
        pl = sorted(rows[i][4] for i in g)
        save = sum(max(0, x - 1) for x in pl) - pl[len(pl) // 2]
        for i in g:
            removable[rows[i][0]] += save / len(g)
        cross_rows.append((save, len(g), len(regs), name, sum(rows[i][3] for i in g)))
    os.makedirs(a.out, exist_ok=True)
    out.sort(key=lambda r: -r[0])
    cross_rows.sort(key=lambda r: -r[0])
    with open(os.path.join(a.out, "case_families.tsv"), "w") as w:
        w.write("removable_lines\tmembers\tregion\tname_pattern\tlines\n")
        for r in out[:2000]:
            w.write("\t".join(map(str, r)) + "\n")
    with open(os.path.join(a.out, "cross_families.tsv"), "w") as w:
        w.write("removable_lines\tmembers\tregions\tname\tlines\n")
        for r in cross_rows[:2000]:
            w.write("\t".join(map(str, r)) + "\n")
    with open(os.path.join(a.out, "regions.tsv"), "w") as w:
        w.write("region\tlines\tfamily_removable\tshare\n")
        for reg, L in sorted(region_lines.items(), key=lambda x: -x[1]):
            w.write(f"{reg}\t{L}\t{int(removable[reg])}\t{removable[reg] / max(1, L):.3f}\n")
    tot = sum(region_lines.values())
    print(json.dumps({"lines": tot, "family_removable": int(sum(removable.values())),
                      "share": round(sum(removable.values()) / tot, 3),
                      "case_families": len(out), "cross_families": len(cross_rows)}))


if __name__ == "__main__":
    main()
