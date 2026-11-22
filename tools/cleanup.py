#!/usr/bin/env python3
"""Delete the declarations of a target that nothing outside the target needs.

    python3 tools/export_decls.py --root ~/Codes/upstream/cfsg-work --prefix CFSG.Permutation --out out/perm.decls.tsv
    python3 tools/cleanup.py --root ~/Codes/upstream/cfsg-work --target Permutation --decls out/perm.decls.tsv

This is step 2 of docs/plan-one-percent.md. It edits the working tree of the
checkout at --root and does not commit; judge the result with tools/verify.py.

What is kept:

  * every protected declaration of the target (data/protected/<target>.txt:
    every declaration that something outside the target uses), and every
    declaration of the target they use, directly or through auxiliary
    constants; a kept declaration keeps its constructors, projections and
    other constants whose names extend its own;
  * every module that a file outside the target imports
    (data/pilot/<target>/protected_imports.txt), with its import lines;
  * every line that is not inside a deleted declaration (namespaces,
    sections, `open`, `variable`, comments between declarations).

What is deleted:

  * the source lines of every other declaration of the target (its full
    range: doc string, attributes and body), together with a `... in`
    prefix line (`omit ... in`, `set_option ... in`) that belonged to it;
  * modules left without declarations that no remaining file imports. A
    file that imported such a module imports that module's imports instead,
    so the set of modules visible from every remaining file is unchanged
    (minus the deleted modules). If the deleted module imported something
    outside Mathlib and the target, it is kept as a file holding only its
    imports, since a new cross-folder import is not allowed.

Line ranges shared with a kept declaration are never deleted. Run
`--dry-run` to print the counts without touching files.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
AUX = re.compile(r"\._|\.(match_|proof_|eq_\d|eq_def|inj|injEq|sizeOf_spec|rec|recOn|casesOn|noConfusion|below|brecOn|binductionOn|ibelow|mk\.inj)")
IMPORT = re.compile(r"^\s*(public\s+)?(meta\s+)?import\s+(all\s+)?(\S+)\s*$")
IN_PREFIX = re.compile(r"^\s*(omit|include|set_option|open|variable|unseal|seal)\b.*\bin\s*$")


def load(path):
    D = {}
    for row in open(path, encoding="utf-8"):
        c = row.rstrip("\n").split("\t")
        name, mod, kind, s, e = c[:5]
        D[name] = dict(mod=mod, kind=kind, s=int(s), e=int(e), uses=c[8].split() if len(c) > 8 and c[8] else [])
    return D


def needed(D, prot):
    by_parent = {}
    for n in D:
        p = n
        while "." in p:
            p = p.rsplit(".", 1)[0]
            by_parent.setdefault(p, []).append(n)
    seen, stack = set(), list(prot)
    while stack:
        u = stack.pop()
        if u in seen:
            continue
        seen.add(u)
        stack.extend(v for v in D.get(u, {}).get("uses", []) if v not in seen)
        stack.extend(v for v in by_parent.get(u, []) if v not in seen)  # constructors, projections, ...
        p = u
        while "." in p:  # an auxiliary constant needs its parent declaration
            p = p.rsplit(".", 1)[0]
            if p in D and D[p]["s"] > 0:
                stack.append(p)
                break
    return seen


def mod_path(root, m):
    return os.path.join(root, *m.split(".")) + ".lean"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--decls", required=True, help="export_decls.py output for the target at the current checkout")
    ap.add_argument("--only", default=None, help="restrict deletions to modules with this prefix")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(os.path.expanduser(a.root))
    prefix = "CFSG." + a.target.replace("/", ".")
    pilot = os.path.join(REPO, "data", "pilot", a.target)
    plist = os.path.join(REPO, "data", "protected", a.target + ".txt")
    prot = [l.strip() for l in open(plist if os.path.exists(plist) else os.path.join(pilot, "protected.txt")) if l.strip()]
    keep_mods = {l.strip() for l in open(os.path.join(pilot, "protected_imports.txt")) if l.strip()}
    D = load(a.decls)
    missing = [n for n in prot if n not in D]
    if missing:
        raise SystemExit(f"{len(missing)} protected declarations are not in the export, e.g. {missing[:3]}")
    seen = needed(D, prot)

    # line ranges per module
    keep, drop = {}, {}
    for n, d in D.items():
        if d["s"] <= 0:
            continue
        (keep if n in seen else drop).setdefault(d["mod"], []).append((d["s"], d["e"], n))
    mods = sorted({d["mod"] for d in D.values()})
    deleted_lines = {}
    for m in mods:
        if a.only and not (m == a.only or m.startswith(a.only + ".")):
            continue
        kept = keep.get(m, [])
        rm = set()
        for s, e, n in drop.get(m, []):
            if any(not (e < ks or ke < s) for ks, ke, _ in kept):
                continue
            rm.update(range(s, e + 1))
        if rm:
            deleted_lines[m] = rm

    # every module of the folder, also those without declarations (import hubs)
    folder = os.path.join(root, *prefix.split("."))
    all_mods = []
    for d, _, fs in os.walk(folder):
        for f in fs:
            if f.endswith(".lean"):
                all_mods.append(os.path.relpath(os.path.join(d, f[:-5]), root).replace(os.sep, "."))
    text = {m: open(mod_path(root, m), encoding="utf-8").read().split("\n") for m in all_mods}
    in_scope = (lambda m: m == a.only or m.startswith(a.only + ".")) if a.only else (lambda m: True)
    # a module is empty when it has no kept declaration and all its declarations are deleted
    empty = {m for m in all_mods if in_scope(m) and not keep.get(m)
             and all(set(range(s, e + 1)) <= deleted_lines.get(m, set()) for s, e, _ in drop.get(m, []))}

    def imports(m):
        out = []
        for l in text[m]:
            g = IMPORT.match(l)
            if g:
                out.append((l.strip(), g.group(4)))
        return out

    def internal(i):
        return i.startswith("Mathlib") or i == prefix or i.startswith(prefix + ".")

    importers = {}
    for m in all_mods:
        for _, i in imports(m):
            importers.setdefault(i, set()).add(m)
    # a module is removed when it is empty, not imported from outside, and all its imports can be
    # inlined into its importers without a new cross-folder import
    removed = set()
    changed = True
    while changed:
        changed = False
        for m in sorted(empty - removed):
            if m in keep_mods:
                continue
            if all(internal(i) or i in removed for _, i in imports(m)):
                removed.add(m)
                changed = True

    memo = {}

    def expansion(i):
        """{module: re-exported?} that replaces `public import i` of a removed module i"""
        if i in memo:
            return memo[i]
        out = {}
        for line, j in imports(i):
            pub = line.startswith("public")
            sub = expansion(j) if j in removed else {j: True}
            for k, v in sub.items():
                out[k] = out.get(k, False) or (pub and v)
        memo[i] = out
        return out

    def expand(i, public, acc):
        """import lines that replace `import i` in a remaining file: the modules it made
        visible stay visible (a non-re-exported import becomes a plain import)"""
        for k, v in sorted(expansion(i).items()):
            acc.append(("public " if public and v else "") + "import " + k)

    new_text = {}
    for m in all_mods:
        if m in removed:
            continue
        lines = list(text[m])
        rm = set(deleted_lines.get(m, set()))
        # `... in` prefixes of deleted declarations
        for ln in sorted(rm):
            if ln - 1 not in rm:
                k = ln - 1
                while k >= 1 and lines[k - 1].strip() == "":
                    k -= 1
                while k >= 1 and IN_PREFIX.match(lines[k - 1]) and k not in rm:
                    rm.add(k)
                    k -= 1
        # imports: original lines of remaining modules, then the expansions of removed ones;
        # one line per module, re-exported if any line re-exported it
        orig, added = {}, {}
        for l in lines:
            g = IMPORT.match(l)
            if not g:
                continue
            if g.group(4) in removed:
                acc = []
                expand(g.group(4), bool(g.group(1)), acc)
                for x in acc:
                    pub, mod = x.startswith("public "), x.split()[-1]
                    added[mod] = added.get(mod, False) or pub
            else:
                orig.setdefault(g.group(4), l)
        import_block = list(orig.values())
        for mod, pub in added.items():
            if mod in orig:
                if pub and not orig[mod].lstrip().startswith("public"):
                    import_block[import_block.index(orig[mod])] = "public import " + mod
                continue
            import_block.append(("public " if pub else "") + "import " + mod)
        out, placed = [], False
        for idx, l in enumerate(lines, start=1):
            if idx in rm:
                continue
            if IMPORT.match(l):
                if not placed:
                    out.extend(import_block)
                    placed = True
                continue
            out.append(l)
        # collapse runs of blank lines left behind
        res = []
        for l in out:
            if l.strip() == "" and res and res[-1].strip() == "":
                continue
            res.append(l)
        if res != text[m]:
            new_text[m] = res

    n_del = sum(len(v) for v in deleted_lines.values())
    report = {"declarations": len([n for n in D if D[n]["s"] > 0]),
              "kept_declarations": len([n for n in D if D[n]["s"] > 0 and n in seen]),
              "modules_removed": len(removed), "modules_changed": len(new_text),
              "declaration_lines_deleted": n_del}
    print(json.dumps(report, indent=2))
    if a.dry_run:
        return
    for m in removed:
        os.unlink(mod_path(root, m))
    for m, res in new_text.items():
        open(mod_path(root, m), "w", encoding="utf-8").write("\n".join(res))


if __name__ == "__main__":
    main()
