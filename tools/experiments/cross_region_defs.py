#!/usr/bin/env python3
"""Definitions with the same body in different regions of CFSG (source level).

A small experiment for docs/two-layer-search.md: which definitions recur
across the top-level folders, i.e. which concepts would pay off across
regions rather than inside one. Each `def`/`abbrev` is normalized by removing
its name, renaming its binders positionally and collapsing whitespace; two
definitions with the same normalized text are copies of one concept.

    python3 tools/experiments/cross_region_defs.py --root ~/Codes/upstream/cfsg --out data/experiments/cross_region_defs.tsv
"""
import argparse, os, re, sys
from collections import defaultdict

DEF = re.compile(r"^(?:@\[[^\]]*\]\s*)?(?:noncomputable\s+|private\s+|protected\s+)*(?:def|abbrev)\s+(\S+)(.*?)(?=\n\S|\Z)", re.M | re.S)
BINDER_NAMES = re.compile(r"[\(\{\[⦃]\s*((?:[^\s:()\[\]{}⦃⦄]+\s+)*[^\s:()\[\]{}⦃⦄]+)\s*:")
COMMENT = re.compile(r"/-.*?-/|--[^\n]*", re.S)


def normalize(rest):
    rest = re.sub(r"\s+", " ", COMMENT.sub(" ", rest)).strip()
    if ":=" not in rest:
        return None
    names = []
    for m in BINDER_NAMES.finditer(rest.split(":=")[0]):
        names += m.group(1).split()
    for i, n in enumerate(dict.fromkeys(names)):
        if re.fullmatch(r"[\w'₀-₉]+", n):
            rest = re.sub(rf"(?<![\w.']){re.escape(n)}(?![\w'₀-₉])", f"x{i}", rest)
    return rest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    root = os.path.join(os.path.expanduser(a.root), "CFSG")
    groups = defaultdict(list)
    nfiles = 0
    for d, _, fs in os.walk(root):
        if "/Certificates" in d:
            continue
        for f in fs:
            if not f.endswith(".lean"):
                continue
            nfiles += 1
            p = os.path.join(d, f)
            rel = os.path.relpath(p, root)
            folder = rel.split(os.sep)[0].removesuffix(".lean")
            s = open(p, encoding="utf-8", errors="replace").read()
            for m in DEF.finditer(s):
                key = normalize(m.group(2))
                if key and len(key) > 25 and key.count(":=") == 1:
                    groups[key].append((folder, m.group(1), rel))
    rows = []
    for key, v in groups.items():
        folders = {x[0] for x in v}
        if len(folders) >= 2:
            rows.append((len(folders), len(v), key, v))
    rows.sort(key=lambda r: (-r[0], -r[1]))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as w:
        w.write("folders\tcopies\tnormalized_definition\tnames\n")
        for nf, nc, key, v in rows:
            names = " ; ".join(f"{n} [{fo}]" for fo, n, _ in v[:12])
            w.write(f"{nf}\t{nc}\t{key[:300]}\t{names}\n")
    print(f"{nfiles} files, {sum(len(v) for v in groups.values())} definitions, "
          f"{len(rows)} groups spanning two or more folders, "
          f"{sum(r[1] for r in rows)} definitions in them", file=sys.stderr)


if __name__ == "__main__":
    main()
