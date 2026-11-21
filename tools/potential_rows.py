#!/usr/bin/env python3
"""Write the upper bounds of tools/skeletons.py and tools/theory_duplicates.py
into data/potential/blocks.tsv, in the parts of data/map/blocks.json.

    python3 tools/potential_rows.py

Methods: same-shape (one general proof per family of proofs with the same
token shape) and same-statement (a statement proved again in another file).
Parts too small to be drawn on the map are summed into the folder's
"(N other parts)" part.
"""
import csv, json, os, sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "site"))
import potential  # noqa: E402

SOURCES = {
    "same-shape": ("data/map/skeletons/regions.tsv", "shape_removable",
                   "proofs with the same token shape (identifiers abstracted); one general proof per family"),
    "same-statement": ("data/map/theory_duplicates/regions.tsv", "removable_lines",
                       "statement proved again in another file; lines only that proof needs"),
}


def main():
    blocks = json.load(open(os.path.join(ROOT, "data/map/blocks.json")))
    parts = {f["folder"]: [p["part"] for p in f["parts"]] for f in blocks["folders"]}
    for method, (path, col, evidence) in SOURCES.items():
        acc = defaultdict(int)
        for r in csv.DictReader(open(os.path.join(ROOT, path)), delimiter="\t"):
            folder, _, part = r["region"].partition(".")
            if folder not in parts:
                continue
            if part and part not in parts[folder]:
                other = [p for p in parts[folder] if p.endswith("other parts)")]
                part = other[0] if other else ""
            acc[(folder, part)] += int(float(r[col]))
        rows = [{"folder": f, "part": p, "method": method, "lines": v, "tokens": None, "evidence": evidence}
                for (f, p), v in acc.items() if v > 0]
        potential.replace_method(os.path.join(ROOT, "data/potential/blocks.tsv"), method, rows)
        print(method, len(rows), sum(r["lines"] for r in rows))


if __name__ == "__main__":
    main()
