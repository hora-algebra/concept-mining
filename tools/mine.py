#!/usr/bin/env python3
"""Baseline and concept candidates for one folder, from export_decls.py output.

    python3 tools/mine.py --decls out/ft_decls.tsv --root ~/Codes/upstream/cfsg \
        --protected data/pilot/FeitThompson/protected.txt --out data/pilot/FeitThompson

Everything is computed on the elaborated declarations of the pinned checkout:

    baseline.json         code lines of the folder (non-blank, outside
                          comments), declarations, and the same restricted to
                          what the protected theorems need
    unreachable.tsv       declarations the protected theorems do not need
    dup_statements.tsv    groups of theorems with the same elaborated
                          statement (up to bound-variable names)
    dup_definitions.tsv   groups of definitions with the same type and body
    hyp_windows.tsv       runs of k consecutive leading binders (k = 2..7)
                          repeated in many statements: a context that could
                          become one structure
    proof_clones.tsv      runs of 6 identical normalized proof lines found in
                          several declarations
    candidates.tsv        the above merged into one ranked list with an
                          estimate of the lines saved

Estimates are deliberately simple and are only used to order the trials; the
ledger records measured lines.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter, defaultdict

COMMENT = re.compile(r"/-.*?-/|--[^\n]*", re.S)
AUX = re.compile(r"\._|\.(match_|proof_|eq_\d|eq_def|inj|injEq|sizeOf_spec|rec|recOn|casesOn|noConfusion|below|brecOn|binductionOn|ibelow|mk\.inj)")


def pretty(n: str) -> str:
    m = re.match(r"_private\.[\w.]+?\.0\.(.*)", n)
    return m.group(1) if m else n


def code_lines_of(text: str) -> int:
    return sum(1 for l in COMMENT.sub("", text).splitlines() if l.strip())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--decls", required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument("--protected", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    root = os.path.expanduser(a.root)
    os.makedirs(a.out, exist_ok=True)

    D = {}
    for row in open(a.decls, encoding="utf-8"):
        c = row.rstrip("\n").split("\t")
        name, mod, kind, s, e, th, vh, bs, uses = c[:9]
        D[name] = dict(mod=mod, kind=kind, s=int(s), e=int(e), th=th, vh=vh,
                       bs=bs.split() if bs else [], uses=uses.split() if uses else [])
    user = {n for n, d in D.items() if d["s"] > 0 and not AUX.search(n.replace("_private.", "", 1))
            and d["kind"] in ("theorem", "def", "inductive", "opaque", "axiom")}

    # source text per module and per declaration
    src = {}
    for d in D.values():
        if d["mod"] not in src:
            p = os.path.join(root, *d["mod"].split(".")) + ".lean"
            src[d["mod"]] = open(p, encoding="utf-8").read().splitlines()
    total_code = sum(code_lines_of("\n".join(v)) for v in src.values())

    def text(n):
        d = D[n]
        return "\n".join(src[d["mod"]][d["s"] - 1:d["e"]])

    loc = {n: code_lines_of(text(n)) for n in user}

    # reachability from the protected theorems (through auxiliary constants too)
    prot = [l.strip() for l in open(a.protected) if l.strip()]
    seen, stack = set(prot), list(prot)
    while stack:
        u = stack.pop()
        for v in D.get(u, {}).get("uses", []):
            if v not in seen:
                seen.add(v)
                stack.append(v)
    # an auxiliary constant counts toward its parent declaration
    def parent(n):
        best = None
        for u in user:
            pass
        return best
    reach_user = {n for n in user if n in seen}
    # declarations reached only through their own auxiliaries (e.g. instances
    # used via their projections) are caught by prefix matching
    aux_seen = [n for n in seen if n not in user]
    by_prefix = set()
    for n in aux_seen:
        base = n
        while "." in base:
            base = base.rsplit(".", 1)[0]
            if base in user:
                by_prefix.add(base)
                break
    reach_user |= by_prefix
    unreach = sorted(user - reach_user, key=lambda n: (D[n]["mod"], D[n]["s"]))
    base = {
        "target": os.path.commonprefix([d["mod"] for d in D.values()]).rstrip("."),
        "modules": len(src),
        "code_lines": total_code,
        "declarations": len(user),
        "declaration_code_lines": sum(loc.values()),
        "needed_declarations": len(reach_user),
        "needed_code_lines": sum(loc[n] for n in reach_user),
        "unneeded_declarations": len(unreach),
        "unneeded_code_lines": sum(loc[n] for n in unreach),
        "protected": prot,
    }
    json.dump(base, open(os.path.join(a.out, "baseline.json"), "w"), indent=2)
    with open(os.path.join(a.out, "unreachable.tsv"), "w") as w:
        w.write("name\tkind\tmodule\tline\tcode_lines\n")
        for n in unreach:
            w.write(f"{pretty(n)}\t{D[n]['kind']}\t{D[n]['mod']}\t{D[n]['s']}\t{loc[n]}\n")

    users_of = Counter(v for n in user for v in set(D[n]["uses"]))
    cands = []  # (estimate, kind, label, detail)

    # duplicated statements
    groups = defaultdict(list)
    for n in reach_user:
        if D[n]["kind"] == "theorem":
            groups[D[n]["th"]].append(n)
    with open(os.path.join(a.out, "dup_statements.tsv"), "w") as w:
        w.write("members\tsaved_estimate\tnames\n")
        rows = []
        for g in groups.values():
            if len(g) > 1:
                g.sort(key=lambda n: loc[n])
                save = sum(loc[n] for n in g[1:])
                rows.append((save, g))
        rows.sort(key=lambda r: -r[0])
        for save, g in rows:
            w.write(f"{len(g)}\t{save}\t{' ; '.join(f'{pretty(n)} [{D[n][chr(109)+chr(111)+chr(100)].rsplit(chr(46),1)[-1]}]' for n in g)}\n")
    dup_stmt_total = sum(r[0] for r in rows)
    cands.append((dup_stmt_total, "duplicate statements", f"{len(rows)} groups of theorems with the same statement", ""))

    # duplicated definitions
    dgroups = defaultdict(list)
    for n in reach_user:
        if D[n]["kind"] == "def" and D[n]["vh"] != "0":
            dgroups[(D[n]["th"], D[n]["vh"])].append(n)
    with open(os.path.join(a.out, "dup_definitions.tsv"), "w") as w:
        w.write("members\tsaved_estimate\tuses\tnames\n")
        drows = []
        for g in dgroups.values():
            if len(g) > 1:
                g.sort(key=lambda n: loc[n])
                drows.append((sum(loc[n] for n in g[1:]), g))
        drows.sort(key=lambda r: -r[0])
        for save, g in drows:
            w.write(f"{len(g)}\t{save}\t{sum(users_of[n] for n in g)}\t{' ; '.join(pretty(n) for n in g)}\n")
    cands.append((sum(r[0] for r in drows), "duplicate definitions", f"{len(drows)} groups of identical definitions", ""))

    # repeated binder runs (elaborated, so variable names do not matter)
    win = {k: defaultdict(list) for k in range(2, 8)}
    for n in reach_user:
        if D[n]["kind"] != "theorem":
            continue
        bs = D[n]["bs"]
        for k in win:
            for i in range(len(bs) - k + 1):
                w_ = tuple(bs[i:i + k])
                if sum(1 for b in w_ if "P" in b) >= 2:  # at least two hypotheses
                    win[k][w_].append(n)
    with open(os.path.join(a.out, "hyp_windows.tsv"), "w") as w:
        w.write("k\ttheorems\tmodules\tsaved_estimate\texample\n")
        hrows = []
        for k, m in win.items():
            for key, ns in m.items():
                ns = sorted(set(ns))
                if len(ns) >= 8:
                    # a structure replaces k binders by one; about 0.5 line per binder
                    save = int(len(ns) * 0.5 * (k - 1) - (k + 3))
                    hrows.append((save, k, ns))
        hrows.sort(key=lambda r: -r[0])
        for save, k, ns in hrows[:300]:
            mods = {D[n]["mod"] for n in ns}
            w.write(f"{k}\t{len(ns)}\t{len(mods)}\t{save}\t{pretty(ns[0])}\n")

    # proof clones: windows of 6 normalized lines inside declaration bodies
    W = 6
    occ = defaultdict(set)
    for n in reach_user:
        lines = [re.sub(r"\s+", " ", l).strip() for l in COMMENT.sub("", text(n)).splitlines()]
        lines = [l for l in lines if l and not l.startswith(("theorem", "lemma", "def", "private", "@["))]
        for i in range(len(lines) - W + 1):
            occ["\n".join(lines[i:i + W])].add(n)
    crow = sorted(((len(ns), key, ns) for key, ns in occ.items() if len(ns) >= 3), key=lambda r: -r[0])
    with open(os.path.join(a.out, "proof_clones.tsv"), "w") as w:
        w.write("declarations\tfirst_line\texample\n")
        done = set()
        for cnt, key, ns in crow[:2000]:
            sig = frozenset(ns)
            if sig in done:
                continue
            done.add(sig)
            w.write(f"{cnt}\t{key.splitlines()[0][:120]}\t{pretty(sorted(ns)[0])}\n")

    with open(os.path.join(a.out, "candidates_summary.json"), "w") as w:
        json.dump({
            "duplicate_statement_groups": len(rows),
            "duplicate_statement_lines": dup_stmt_total,
            "duplicate_definition_groups": len(drows),
            "duplicate_definition_lines": sum(r[0] for r in drows),
            "hyp_windows_top": [(s, k, len(ns), pretty(ns[0])) for s, k, ns in hrows[:20]],
        }, w, indent=2)
    print(json.dumps(base | {"protected": len(prot)}, indent=2))
    print("dup statements:", len(rows), "groups,", dup_stmt_total, "lines; dup defs:", len(drows), "groups,", sum(r[0] for r in drows), "lines")


if __name__ == "__main__":
    main()
