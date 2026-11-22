#!/usr/bin/env python3
"""Delete the declarations that a change made unreachable, and nothing else.

After a proof is replaced (for example a second proof of a theorem by a call
to the first one), the declarations that only the old proof used are no
longer needed. This compares two exports of the target (tools/export_decls.py),
taken before and after the replacement, and deletes from the source exactly
the declarations that were needed before and are not needed after.
Declarations that were already unneeded before are left alone, so that the
saving is not mixed with ordinary dead-code removal.

    python3 tools/prune_unreachable.py --root ~/Codes/upstream/cfsg \
        --before out/qz_decls.tsv --after out/qz_decls_after.tsv \
        --protected data/protected/ThirdParty/QiuzhenCFSG.txt [--dry-run]

"Needed" means reachable, through the constants that types and values use,
from the protected declarations. A module left with no declaration and
imported by no kept module is deleted too; import lines of deleted modules
are removed from kept files.
"""

from __future__ import annotations

import argparse
import os
import re
from collections import defaultdict

AUX = re.compile(r"\._|\.(match_|proof_|eq_\d|eq_def)")
# a line holding only attributes, e.g. "@[simp]" or "@[simp, norm_cast]"
ATTR_ONLY = re.compile(r"^\s*@\[[^\]]*\]\s*$")


def aux(n):
    return bool(AUX.search(n.replace("_private.", "", 1)))


def load(path):
    D = {}
    for row in open(path, encoding="utf-8"):
        c = row.rstrip("\n").split("\t")
        D[c[0]] = dict(mod=c[1], s=int(c[3]), e=int(c[4]), uses=c[8].split() if len(c) > 8 and c[8] else [])
    return D


def needed(D, roots):
    seen, st = set(), [r for r in roots if r in D]
    seen.update(st)
    while st:
        u = st.pop()
        for v in D[u]["uses"]:
            if v in D and v not in seen:
                seen.add(v)
                st.append(v)
    # a declaration needed only through its auxiliary constants is needed
    for n in list(seen):
        base = n
        while "." in base:
            base = base.rsplit(".", 1)[0]
            if base in D:
                seen.add(base)
    return seen


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True)
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--protected", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    root = os.path.expanduser(a.root)
    roots = [l.strip() for l in open(a.protected) if l.strip()]
    B, A = load(a.before), load(a.after)
    nb, na = needed(B, roots), needed(A, roots)
    candidates = {n for n in nb - na if n in A and A[n]["s"] > 0}
    # everything that stays in the source (needed or not) keeps its dependencies:
    # a candidate still used by a remaining declaration is not deleted
    stays = [n for n in A if n not in candidates]
    keep = needed(A, stays)
    gone = sorted(n for n in candidates - keep if not aux(n))
    by_file = defaultdict(list)
    for n in gone:
        by_file[A[n]["mod"]].append((A[n]["s"], A[n]["e"], n))
    gone_set = set(gone)
    kept_decls = defaultdict(int)
    for n, d in A.items():
        if d["s"] > 0 and n not in gone_set and not aux(n):
            kept_decls[d["mod"]] += 1
    print(f"needed before {len(nb)}, after {len(na)}; deleting {len(gone)} declarations in {len(by_file)} modules")
    if a.dry_run:
        return
    removed_lines = 0
    for mod, spans in by_file.items():
        p = os.path.join(root, *mod.split(".")) + ".lean"
        lines = open(p, encoding="utf-8").read().split("\n")
        # lines of declarations that stay in this file are never dropped
        kept_lines = set()
        for n, d in A.items():
            if d["mod"] == mod and d["s"] > 0 and n not in gone_set:
                kept_lines.update(range(d["s"] - 1, d["e"]))
        drop = set()
        for s, e, _ in spans:
            # include the doc comment and attributes directly above
            k = s - 2
            while k >= 0 and k not in kept_lines and (ATTR_ONLY.match(lines[k]) or lines[k].lstrip().startswith("/--") or
                              (lines[k].strip() and not lines[k][:1].isspace() and lines[k].rstrip().endswith("-/")
                               and "/--" in "\n".join(lines[max(0, k - 30):k + 1]))):
                if lines[k].lstrip().startswith("/--") or ATTR_ONLY.match(lines[k]):
                    drop.update(range(k, s - 1))
                    k -= 1
                    continue
                # end of a multi-line doc comment: walk up to its start
                j = k
                while j >= 0 and "/--" not in lines[j]:
                    j -= 1
                if j >= 0:
                    drop.update(range(j, s - 1))
                    k = j - 1
                else:
                    break
            drop.update(range(s - 1, e))
        drop -= kept_lines
        removed_lines += len(drop)
        out = [l for i, l in enumerate(lines) if i not in drop]
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(out))
        open(p, "w", encoding="utf-8").write(text)
    # modules with no declaration left that no kept module imports
    imp = re.compile(r"^\s*(?:public\s+)?(?:meta\s+)?import\s+(?:all\s+)?(\S+)\s*$", re.M)
    mods = {d["mod"] for d in A.values()}
    importers = defaultdict(set)
    for m in mods:
        p = os.path.join(root, *m.split(".")) + ".lean"
        if os.path.exists(p):
            for t in imp.findall(open(p, encoding="utf-8").read()):
                importers[t].add(m)
    # also importers from anywhere in CFSG (outside the target)
    for d, _, fs in os.walk(os.path.join(root, "CFSG")):
        if "/Certificates" in d:
            continue
        for f in fs:
            if f.endswith(".lean"):
                m = os.path.relpath(os.path.join(d, f[:-5]), root).replace(os.sep, ".")
                if m in mods:
                    continue
                try:
                    for t in imp.findall(open(os.path.join(d, f), encoding="utf-8").read()):
                        if t in mods:
                            importers[t].add(m)
                except OSError:
                    pass
    dead = {m for m in mods if kept_decls[m] == 0 and m in by_file}
    changed = True
    while changed:
        changed = False
        for m in list(dead):
            if importers[m] - dead:
                dead.discard(m)
                changed = True
    for m in dead:
        os.unlink(os.path.join(root, *m.split(".")) + ".lean")
    for m in mods - dead:
        p = os.path.join(root, *m.split(".")) + ".lean"
        if not os.path.exists(p):
            continue
        s = open(p, encoding="utf-8").read()
        t = imp.sub(lambda mm: "" if mm.group(1) in dead else mm.group(0), s)
        if t != s:
            open(p, "w", encoding="utf-8").write(re.sub(r"\n{3,}", "\n\n", t))
    print(f"removed {removed_lines} lines; deleted {len(dead)} modules")


if __name__ == "__main__":
    main()
