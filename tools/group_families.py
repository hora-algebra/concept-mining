#!/usr/bin/env python3
"""Arguments repeated group by group (source level, no build).

CFSG treats the 26 sporadic groups and the families of groups of Lie type one
at a time. When the same argument is written out again for every group, the
copies differ only in the group: `CFSG.Sporadic.J1.pt_inj` and
`CFSG.Sporadic.McL.pt_inj`, or `PairFrameExcE6Levi.lean` and
`PairFrameExcE7Levi.lean`. This tool finds such repetitions and estimates how
much one general statement (taking the group's data as a parameter) plus one
instantiation per group would remove.

A *group token* is a sporadic group (`J1`, `McL`, `Co2`, `Fi22`, `ONan`, ...),
a Lie type (`E6`, `G2`, `BCD`, `Ree`, ...) or `PSL`/`PSU`/`PSp` (see SPORADIC
and LIE). A declaration is *group-indexed* when its full name or its file path
contains one. For every group-indexed declaration the tool computes a
skeleton of its text (local names renamed by position, numbers replaced by
`n`, group tokens by `<G>`, global names kept, so that proofs calling
different lemmas do not look alike) and the set of its 6-token shingles.

Three ways of grouping, each reported separately:

  by name      declarations whose names agree once group tokens are replaced
               by `<G>` (families.tsv, themes.tsv)
  by skeleton  declarations of different groups whose shingle sets have
               Jaccard index >= 0.5, whatever their names; candidates come
               from a bottom-k sketch, clusters from single linkage
               (near_clusters.tsv, near_themes.tsv; --near)
  by file      whole files whose paths agree up to the group
               (file_families.tsv; --files)

Estimate per family, for members with similarity >= theta to the family's
medoid: one general proof of 1.15 x the largest member, and 2 lines per member
for its instantiation:

    removable(theta) = sum(lines) - 1.15 * max(lines) - 2 * members

reported at theta = 0.8 (close to a copy) and theta = 0.5 (same argument,
differing details). A family whose lines are mostly data tables (>= 60%
literal tokens, as in tools/data_share.py) is marked `data`: shortening it is
a matter of encoding, not of concepts. All figures are estimates, not
Lean-checked.

    python3 tools/group_families.py --near --files --root ~/Codes/upstream/cfsg --out data/map/group_families
    python3 tools/group_families.py --root ... --folders Sporadic Monster LieType --out ...

Standard library only. The whole of CFSG takes about 4 minutes and 2 GB.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zlib
from collections import defaultdict
from array import array
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from size import TOKEN, strip_comments  # noqa: E402
from skeletons import split_decls_ns  # noqa: E402

TOTAL_LINES = 35_093_004
# a declaration is a data table when >= 60% of its tokens are literals (tools/data_share.py)
LIT = re.compile(r'^(\d+(\.\d+)?|[\[\](),;⟨⟩!#{}|-]|"(?:[^"\\]|\\.)*")$')  # lines inside declarations of CFSG (data/map/summary.json)

# group tokens; the value is the canonical group (aliases map to one key)
SPORADIC = {
    "M11": "M11", "M12": "M12", "M22": "M22", "M23": "M23", "M24": "M24",
    "J1": "J1", "J2": "J2", "J3": "J3", "J4": "J4",
    "HS": "HS", "McL": "McL", "Mcl": "McL", "He": "He", "Held": "He",
    "Ru": "Ru", "Rudvalis": "Ru", "Suz": "Suz", "ON": "ON", "ONan": "ON",
    "Ly": "Ly", "Lyons": "Ly", "Th": "Th", "HN": "HN",
    "Fi22": "Fi22", "Fi23": "Fi23", "Fi24": "Fi24", "Fi24'": "Fi24",
    "Co1": "Co1", "Co2": "Co2", "Co3": "Co3",
}
# lower-case spellings used at the start of identifiers (j1_certificate,
# co2VecsLit, suzP); short words that are also English or Lean words are left out
LOWER = {k.lower(): v for k, v in SPORADIC.items()
         if k.lower() not in {"he", "on", "th", "ly", "ru", "held", "mcl"}} | {"mcl": "McL"}
LIE = {
    "A1": "A1", "A2": "A2", "A3": "A3", "B2": "B2", "B3": "B3", "C2": "C2", "C3": "C3",
    "D4": "D4", "E6": "E6", "E7": "E7", "E8": "E8", "E78": "E7", "F4": "F4", "G2": "G2",
    "BCD": "BCD", "Ree": "Ree", "Suzuki": "Sz", "Sz": "Sz",
    "PSL": "PSL", "PSU": "PSU", "PSp": "PSp",
}
ALL = SPORADIC | LIE
# a token is a group when it is not glued to letters on its left and not
# followed by a lower-case letter or digit (so `Th` in `Theorem` and `He` in
# `Hence` are not groups, but `HSStd`, `CentralTwoHS` and `fi24_` are)
_alts = sorted(ALL, key=len, reverse=True)
UPPER_RE = re.compile(r"(?<![A-Za-z0-9'])(?:" + "|".join(re.escape(t) for t in _alts) + r")(?![a-z0-9])"
                      r"|(?<=[a-z0-9])(?:" + "|".join(re.escape(t) for t in _alts if t[0].isupper() and len(t) > 1) +
                      r")(?![a-z0-9])")
LOWER_RE = re.compile(r"(?<![A-Za-z0-9'])(?:" + "|".join(re.escape(t) for t in sorted(LOWER, key=len, reverse=True)) +
                      r")(?![a-z0-9])")
# single letters for the Baby Monster and the Monster: only as a whole name component
SINGLE = {"B": "B", "M": "M"}


def normalize(name: str):
    """(normalized name, set of groups) for a full declaration name."""
    groups = set()
    comps = []
    for c in name.split("."):
        if c in SINGLE:
            groups.add(SINGLE[c])
            comps.append("<G>")
            continue

        def up(m):
            groups.add(ALL[m.group(0)])
            return "<G>"

        def lo(m):
            groups.add(LOWER[m.group(0)])
            return "<g>"
        c = UPPER_RE.sub(up, c)
        c = LOWER_RE.sub(lo, c)
        comps.append(c)
    return ".".join(comps), groups


def skeleton(text: str):
    toks = TOKEN.findall(text)
    local = {}
    for m in re.finditer(r"[\(\{⦃\[]\s*((?:[^\s:()\[\]{}⦃⦄]+\s+)*[^\s:()\[\]{}⦃⦄]+)\s*:", text):
        for n in m.group(1).split():
            local.setdefault(n, f"v{len(local)}")
    for m in re.finditer(r"\b(?:have|obtain|intro|rintro|fun|set)\s+([\w'₀-₉]+)", text):
        local.setdefault(m.group(1), f"v{len(local)}")
    m = re.search(r"\b(?:theorem|lemma|def|abbrev|instance|structure|class|inductive)\s+([^\s:(\[{]+)", text)
    first = m.group(1) if m else ""
    k = next((i for i, t in enumerate(toks) if t == first), 1)
    out = []
    for t in toks[k + 1:]:
        if t in local:
            out.append(local[t])
        elif t[0].isdigit():
            out.append("n")
        elif t[0].isalpha() or t[0] == "_":
            out.append(normalize(t)[0])
        else:
            out.append(t)
    return out


def shingles(sk, k=6):
    if len(sk) < k:
        return {zlib.crc32("\x1f".join(sk).encode())}
    # a stable hash: worker processes do not share Python's string hash seed
    return {zlib.crc32("\x1f".join(sk[i:i + k]).encode()) for i in range(len(sk) - k + 1)}


def scan_file(args):
    root, path, near = args
    rel = os.path.relpath(path, os.path.join(root, "CFSG"))
    try:
        src = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return []
    out = []
    theme_path, path_groups = normalize(rel.removesuffix(".lean").replace(os.sep, "."))
    for text, ns in split_decls_ns(src):
        m = re.search(r"\b(?:theorem|lemma|def|abbrev|instance|structure|class|inductive)\s+([^\s:(\[{]+)", text)
        if not m:
            continue
        short = m.group(1)
        name = short.removeprefix("_root_.") if short.startswith("_root_.") or not ns else f"{ns}.{short}"
        norm, groups = normalize(name)
        if not groups and not (near and path_groups):
            continue
        lines = sum(1 for l in text.splitlines() if l.strip())
        if near and lines < 3:
            continue
        toks = TOKEN.findall(text)
        data = bool(toks) and sum(1 for x in toks if LIT.match(x)) >= 0.6 * len(toks)
        sk = skeleton(text)
        if len(sk) < 8:
            continue
        out.append(dict(name=name, norm=norm, groups=sorted(groups), pgroups=sorted(groups | path_groups),
                        file=rel, theme=theme_path, lines=lines, tokens=len(sk), data=data,
                        sh=array("I", sorted(shingles(sk)))))
    return out


def scan_whole_file(args):
    root, path = args
    rel = os.path.relpath(path, os.path.join(root, "CFSG"))
    theme, groups = normalize(rel.removesuffix(".lean").replace(os.sep, "."))
    if not groups:
        return None
    try:
        src = strip_comments(open(path, encoding="utf-8", errors="replace").read())
    except OSError:
        return None
    lines = sum(1 for l in src.splitlines() if l.strip() and not re.match(r"\s*(public\s+)?(meta\s+)?import\b|\s*module\s*$", l))
    sk = skeleton("theorem X " + src)
    if len(sk) < 8:
        return None
    toks = TOKEN.findall(src)
    data = bool(toks) and sum(1 for x in toks if LIT.match(x)) >= 0.6 * len(toks)
    return dict(name=rel, norm=theme, groups=sorted(groups), pgroups=sorted(groups), file=rel, theme=theme,
                lines=lines, tokens=len(sk), data=data, sh=array("I", sorted(shingles(sk))))


def jaccard(a, b):
    if not a or not b:
        return 0.0
    a, b = set(a), set(b)
    return len(a & b) / len(a | b)


def estimate(ms, cap=60):
    """medoid, similarities to it, and (removable, members) at theta 0.8 and 0.5"""
    cand = ms if len(ms) <= cap else sorted(ms, key=lambda d: -d["lines"])[:cap]
    sets = [set(x["sh"]) for x in cand]
    best, bs = 0, -1.0
    for i, x in enumerate(sets):
        s = sum(len(x & y) / len(x | y) for y in sets)
        if s > bs:
            best, bs = i, s
    med = cand[best]
    ms_set = set(med["sh"])
    sims = []
    for d in ms:
        y = set(d["sh"])
        sims.append(len(ms_set & y) / len(ms_set | y))
    res = {}
    for th in (0.8, 0.5):
        sel = [d for d, s in zip(ms, sims) if s >= th]
        if len(sel) < 2 or len({g for d in sel for g in d["pgroups"]}) < 2:
            res[th] = (0, 0)
            continue
        tot = sum(d["lines"] for d in sel)
        save = tot - 1.15 * max(d["lines"] for d in sel) - 2 * len(sel)
        res[th] = (max(0, int(save)), len(sel))
    return med, sims, res


def near_clusters(decls, k=16, min_shared=4, max_bucket=300, theta=0.5):
    """Clusters of declarations from different groups whose skeletons have
    Jaccard >= theta, whatever their names. Candidate pairs come from a
    bottom-k sketch of the shingle sets."""
    idx = defaultdict(list)
    for i, d in enumerate(decls):
        if not d["pgroups"]:
            continue
        for v in d["sh"][:k]:
            idx[v].append(i)
    parent = list(range(len(decls)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    # count shared sketch values per declaration (no global table of pairs, so
    # that the whole of CFSG fits in memory)
    pairs = edges = 0
    for i, d in enumerate(decls):
        if not d["pgroups"]:
            continue
        cnt = defaultdict(int)
        for v in d["sh"][:k]:
            b = idx[v]
            if len(b) < 2 or len(b) > max_bucket:
                continue
            for j in b:
                if j > i:
                    cnt[j] += 1
        pairs += len(cnt)
        for j, c in cnt.items():
            if c < min_shared:
                continue
            dj = decls[j]
            if d["pgroups"] == dj["pgroups"]:
                continue
            if jaccard(d["sh"], dj["sh"]) >= theta:
                edges += 1
                parent[find(i)] = find(j)
    cl = defaultdict(list)
    for i in range(len(decls)):
        if decls[i]["pgroups"]:
            cl[find(i)].append(i)
    out = [[decls[i] for i in v] for v in cl.values() if len(v) > 1]
    print(f"near: {pairs} candidate pairs, {edges} edges, {len(out)} clusters", file=sys.stderr)
    return out


def write_rows(path, rows, cols, limit=5000):
    with open(path, "w") as w:
        w.write("\t".join(cols) + "\n")
        for r in rows[:limit]:
            w.write("\t".join(" ".join(r[c]) if isinstance(r[c], list) else str(r[c]) for c in cols) + "\n")


def summarize(rows, key):
    themes = defaultdict(lambda: defaultdict(float))
    for r in rows:
        t = themes[r[key]]
        t["families"] += 1
        t["lines"] += r["lines"]
        t["save80"] += r["save80"]
        t["save50"] += r["save50"]
        t["groups"] = max(t["groups"], len(r["groups"]))
    return sorted(themes.items(), key=lambda kv: -kv[1]["save50"])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--folders", nargs="*", default=None, help="folders under CFSG/ (default: all)")
    ap.add_argument("--near", action="store_true",
                    help="also cluster declarations of different groups with similar skeletons, whatever their names")
    ap.add_argument("--files", action="store_true",
                    help="also compare whole files whose paths agree up to the group (e.g. PairFrameExc<G>Levi.lean)")
    ap.add_argument("--limit", type=int, default=1000, help="rows written per table")
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    root = os.path.expanduser(a.root)
    base = os.path.join(root, "CFSG")
    tops = [os.path.join(base, f) for f in a.folders] if a.folders else [base]
    files = []
    for t in tops:
        for d, _, fs in os.walk(t):
            if "/Certificates" in d:
                continue
            files += [(root, os.path.join(d, f), a.near) for f in fs if f.endswith(".lean")]
    decls = []
    with Pool(a.jobs) as p:
        for i, r in enumerate(p.imap_unordered(scan_file, files, chunksize=100)):
            decls += r
            if i % 20000 == 0:
                print(f"{i}/{len(files)} files, {len(decls)} decls", file=sys.stderr)
    os.makedirs(a.out, exist_ok=True)
    cols = ["save50", "save80", "lines", "members", "n50", "n80", "mean_sim", "kind", "folder", "theme", "norm",
            "groups", "example", "file"]

    def kind(ms):
        return "data" if sum(d["lines"] for d in ms if d["data"]) * 2 >= sum(d["lines"] for d in ms) else "argument"

    # 1. families by name up to the group
    fam = defaultdict(list)
    for d in decls:
        if d["groups"]:
            fam[d["norm"]].append(d)
    rows = []
    for norm, ms in fam.items():
        gs = {g for d in ms for g in d["groups"]}
        if len(gs) < 2 or len(ms) < 2:
            continue
        med, sims, res = estimate(ms)
        rows.append(dict(norm=norm, members=len(ms), groups=sorted(gs), lines=sum(d["lines"] for d in ms), kind=kind(ms),
                         save80=res[0.8][0], n80=res[0.8][1], save50=res[0.5][0], n50=res[0.5][1],
                         mean_sim=round(sum(sims) / len(sims), 3), theme=med["theme"],
                         folder=med["file"].split(os.sep)[0], example=med["name"], file=med["file"]))
    rows.sort(key=lambda r: -r["save50"])
    write_rows(os.path.join(a.out, "families.tsv"), rows, cols, a.limit)
    with open(os.path.join(a.out, "themes.tsv"), "w") as w:
        w.write("save50\tsave80\tlines\tfamilies\tmax_groups\ttheme\n")
        for k, t in summarize(rows, "theme")[:a.limit]:
            w.write(f"{int(t['save50'])}\t{int(t['save80'])}\t{int(t['lines'])}\t{int(t['families'])}\t"
                    f"{int(t['groups'])}\t{k}\n")

    def by_folder(rows):
        out = defaultdict(lambda: defaultdict(int))
        for r in rows:
            f = out[r["folder"] + ("" if r["kind"] == "argument" else " (data)")]
            f["families"] += 1
            f["lines"] += r["lines"]
            f["save80"] += r["save80"]
            f["save50"] += r["save50"]
        return {k: dict(v) for k, v in sorted(out.items(), key=lambda kv: -kv[1]["save50"])}

    lines_by_folder = defaultdict(int)
    for d in decls:
        lines_by_folder[d["file"].split(os.sep)[0]] += d["lines"]
    summary = {
        "files": len(files),
        "decls_scanned": len(decls),
        "lines_scanned": sum(d["lines"] for d in decls),
        "lines_scanned_by_folder": dict(lines_by_folder),
        "cfsg_lines": TOTAL_LINES,
        "by_name": {
            "group_named_decls": sum(1 for d in decls if d["groups"]),
            "group_named_lines": sum(d["lines"] for d in decls if d["groups"]),
            "families": len(rows),
            "family_lines": sum(r["lines"] for r in rows),
            "save80": sum(r["save80"] for r in rows),
            "save50": sum(r["save50"] for r in rows),
            "argument_save80": sum(r["save80"] for r in rows if r["kind"] == "argument"),
            "argument_save50": sum(r["save50"] for r in rows if r["kind"] == "argument"),
            "by_folder": by_folder(rows),
        },
    }

    # 2. clusters by skeleton, whatever the names
    if a.near:
        crow = []
        for ms in near_clusters(decls):
            gs = {g for d in ms for g in d["pgroups"]}
            if len(gs) < 2:
                continue
            med, sims, res = estimate(ms)
            names = sorted({d["norm"] for d in ms})
            crow.append(dict(norm=" | ".join(names[:4]) + (f" | ... ({len(names)} names)" if len(names) > 4 else ""),
                             members=len(ms), groups=sorted(gs), lines=sum(d["lines"] for d in ms), kind=kind(ms),
                             save80=res[0.8][0], n80=res[0.8][1], save50=res[0.5][0], n50=res[0.5][1],
                             mean_sim=round(sum(sims) / len(sims), 3), theme=med["theme"],
                             folder=med["file"].split(os.sep)[0], example=med["name"], file=med["file"]))
        crow.sort(key=lambda r: -r["save50"])
        write_rows(os.path.join(a.out, "near_clusters.tsv"), crow, cols, a.limit)
        with open(os.path.join(a.out, "near_themes.tsv"), "w") as w:
            w.write("save50\tsave80\tlines\tclusters\tmax_groups\ttheme\n")
            for k, t in summarize(crow, "theme")[:a.limit]:
                w.write(f"{int(t['save50'])}\t{int(t['save80'])}\t{int(t['lines'])}\t{int(t['families'])}\t"
                        f"{int(t['groups'])}\t{k}\n")
        summary["by_skeleton"] = {
            "clusters": len(crow),
            "cluster_lines": sum(r["lines"] for r in crow),
            "save80": sum(r["save80"] for r in crow),
            "save50": sum(r["save50"] for r in crow),
            "argument_save80": sum(r["save80"] for r in crow if r["kind"] == "argument"),
            "argument_save50": sum(r["save50"] for r in crow if r["kind"] == "argument"),
            "by_folder": by_folder(crow),
        }
    # 3. whole files with the same path up to the group
    if a.files:
        with Pool(a.jobs) as p:
            fl = [f for f in p.imap_unordered(scan_whole_file, [(root, x[1]) for x in files], chunksize=100) if f]
        ff = defaultdict(list)
        for f in fl:
            ff[f["norm"]].append(f)
        frow = []
        for norm, ms in ff.items():
            gs = {g for d in ms for g in d["groups"]}
            if len(gs) < 2 or len(ms) < 2:
                continue
            med, sims, res = estimate(ms)
            frow.append(dict(norm=norm, members=len(ms), groups=sorted(gs), lines=sum(d["lines"] for d in ms),
                             kind=kind(ms), save80=res[0.8][0], n80=res[0.8][1], save50=res[0.5][0],
                             n50=res[0.5][1], mean_sim=round(sum(sims) / len(sims), 3), theme=norm,
                             folder=med["file"].split(os.sep)[0], example=med["name"], file=med["file"]))
        frow.sort(key=lambda r: -r["lines"])
        write_rows(os.path.join(a.out, "file_families.tsv"), frow, cols, a.limit)
        summary["by_file"] = {
            "families": len(frow),
            "family_lines": sum(r["lines"] for r in frow),
            "save80": sum(r["save80"] for r in frow),
            "save50": sum(r["save50"] for r in frow),
            "argument_save80": sum(r["save80"] for r in frow if r["kind"] == "argument"),
            "argument_save50": sum(r["save50"] for r in frow if r["kind"] == "argument"),
            "by_folder": by_folder(frow),
        }
    for k in ("by_name", "by_skeleton", "by_file"):
        if k in summary:
            summary[k]["share80"] = round(summary[k]["save80"] / TOTAL_LINES, 6)
            summary[k]["share50"] = round(summary[k]["save50"] / TOTAL_LINES, 6)
            summary[k]["argument_share50"] = round(summary[k]["argument_save50"] / TOTAL_LINES, 6)
    json.dump(summary, open(os.path.join(a.out, "summary.json"), "w"), indent=2)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
