#!/usr/bin/env python3
"""How much of each region is data rather than argument.

A declaration counts as data when at least 60% of its tokens are numbers,
brackets, commas or string literals (certificate tables, witness lists,
matrices). Such code is checked by a generic checker elsewhere; making it
shorter is a question of encoding or of computing it at build time, not of
finding concepts, so the compression map reports it separately.

    python3 tools/data_share.py --root ~/Codes/upstream/cfsg --out data/map/data_share.tsv
"""
import argparse, os, re, sys
from collections import defaultdict
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from size import TOKEN  # noqa: E402
from skeletons import split_decls  # noqa: E402

LIT = re.compile(r'^(\d+(\.\d+)?|[\[\](),;⟨⟩!#{}|-]|"(?:[^"\\]|\\.)*")$')


def scan(args):
    root, path = args
    rel = os.path.relpath(path, os.path.join(root, "CFSG"))
    parts = rel.split(os.sep)
    region = ".".join(parts[:2]).removesuffix(".lean") if len(parts) > 2 else parts[0].removesuffix(".lean")
    data = total = 0
    try:
        src = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return region, 0, 0
    for t in split_decls(src):
        toks = TOKEN.findall(t)
        lines = sum(1 for l in t.splitlines() if l.strip())
        total += lines
        if toks and sum(1 for x in toks if LIT.match(x)) >= 0.6 * len(toks):
            data += lines
    return region, data, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    root = os.path.expanduser(a.root)
    files = [(root, os.path.join(d, f)) for d, _, fs in os.walk(os.path.join(root, "CFSG"))
             if "/Certificates" not in d for f in fs if f.endswith(".lean")]
    R = defaultdict(lambda: [0, 0])
    with Pool(12) as p:
        for reg, d, t in p.imap_unordered(scan, files, chunksize=200):
            R[reg][0] += d
            R[reg][1] += t
    with open(a.out, "w") as w:
        w.write("region\tdata_lines\tlines\tdata_share\n")
        for reg, (d, t) in sorted(R.items(), key=lambda x: -x[1][1]):
            w.write(f"{reg}\t{d}\t{t}\t{d / max(1, t):.3f}\n")
    D = sum(v[0] for v in R.values()); T = sum(v[1] for v in R.values())
    print(D, T, round(D / T, 3))


if __name__ == "__main__":
    main()
