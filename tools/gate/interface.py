#!/usr/bin/env python3
"""The public face of a target, and whether a patch keeps it.

Files outside a target see only what the module system exports from the
target modules they import: the exported constants (theorems as statements,
definitions with a value only when exposed), exported imports and exported
extension entries (simp lemmas, instances, reducibility, notation, ...). A
module imported with `import all` or `meta import` gives everything. If all of
that is unchanged, the files outside the target compile as before and need
not be rebuilt, which is what lets the gate check a target alone.

    entries   = target modules that a file outside the target imports
    interface = entries, closed under `public import` within the target
                (everything a module imported with `import all` or
                `meta import` imports counts in full)

The checker (`CheckEnv.lean --interface`) prints each interface module's face;
`compare` lists what a patch changed. The meaning of the public statements is
checked separately, by one statement closure over every constant of the face
(`CheckEnv.lean`, `union_roots`): a definition a public statement mentions
keeps its value even when it is not exposed.
"""

from __future__ import annotations

import os
import re

IMPORT = re.compile(r"^\s*(public\s+)?(meta\s+)?import\s+(all\s+)?((?:[A-Za-z0-9_'.«»]+\s*)+)(?:--.*)?$")

# extension entries that do not change how importers elaborate: compiled
# code, bookkeeping derived from the constants, documentation and positions
IGNORED_EXT_PREFIXES = ("Lean.Compiler.", "Lean.IR.")
IGNORED_EXTS = {
    "_private.Lean.OriginalConstKind.0.Lean.privateConstKindsExt",
    "_private.Lean.Util.CollectAxioms.0.Lean.exportedAxiomsExt",
    "_private.Lean.Namespace.0.Lean.namespacesExt",
    "_private.Lean.Compiler.ModPkgExt.0.Lean.modPkgExt",
    "_private.Lean.ExtraModUses.0.Lean.extraModUses",
    "Lean.declRangeExt",
    "Lean.docStringExt",
    "Lean.moduleDocExt",
    "Lean.versoDocStringExt",
    "Lean.versoModuleDocExt",
    "Lean.deprecatedModuleExt",
}


def ext_counted(name: str) -> bool:
    return not name.startswith(IGNORED_EXT_PREFIXES) and name not in IGNORED_EXTS


def header_imports(text: str) -> list[tuple[str, bool, bool, bool]]:
    """(module, public, meta, all) for each import of a Lean file's header."""
    out = []
    in_comment = 0
    for line in text.splitlines():
        s = line.strip()
        if in_comment:
            in_comment += s.count("/-") - s.count("-/")
            continue
        if s.startswith("/-"):
            in_comment = s.count("/-") - s.count("-/")
            continue
        if not s or s.startswith("--") or s == "module" or s.startswith("prelude"):
            continue
        m = IMPORT.match(line)
        if not m:
            break
        for mod in m.group(4).split():
            out.append((mod, bool(m.group(1)), bool(m.group(2)), bool(m.group(3))))
    return out


def module_of(root: str, path: str) -> str:
    return os.path.relpath(path, root)[:-len(".lean")].replace(os.sep, ".")


def lean_files(root: str, skip: str | None = None):
    for d, dirs, fs in os.walk(root):
        dirs[:] = sorted(x for x in dirs if not x.startswith(".") and
                         not (skip and os.path.join(d, x) == skip))
        for f in sorted(fs):
            if f.endswith(".lean"):
                yield os.path.join(d, f)


def read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def in_target(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def entries(tree: str, target: str) -> dict[str, bool]:
    """{target module: full?} for every target module that a Lean file of
    `tree` outside the target imports; full when imported with `import all`
    or `meta import`."""
    prefix = "CFSG." + target.replace("/", ".")
    folder = os.path.join(tree, "CFSG", *target.split("/"))
    out: dict[str, bool] = {}
    for p in lean_files(tree, skip=folder):
        if module_of(tree, p) == prefix:
            continue  # the target's own root file CFSG/<target>.lean
        for mod, _pub, meta, all_ in header_imports(read(p)):
            if in_target(mod, prefix):
                out[mod] = out.get(mod, False) or meta or all_
    return out


def target_headers(tree: str, target: str) -> dict[str, list[tuple[str, bool, bool, bool]]]:
    prefix = "CFSG." + target.replace("/", ".")
    folder = os.path.join(tree, "CFSG", *target.split("/"))
    out = {}
    for p in lean_files(folder):
        out[module_of(tree, p)] = header_imports(read(p))
    root_file = folder + ".lean"
    if os.path.exists(root_file):
        out[prefix] = header_imports(read(root_file))
    return out


def interface(headers: dict[str, list], entry: dict[str, bool], prefix: str) -> dict[str, bool]:
    """Close `entry` under what importers can see: `public import` from a
    module seen normally, every import from a module seen in full (and a
    module reached that way is seen in full too)."""
    seen: dict[str, bool] = {}
    todo = list(entry.items())
    while todo:
        mod, full = todo.pop()
        if mod in seen and (seen[mod] or not full):
            continue
        seen[mod] = seen.get(mod, False) or full
        for dep, pub, meta, all_ in headers.get(mod, []):
            if not in_target(dep, prefix):
                continue
            if full:
                todo.append((dep, True))
            elif pub:
                todo.append((dep, meta or all_))
    return seen


def request(levels: dict[str, bool], existing: set[str]) -> dict:
    return {"modules": [{"name": m, "full": f} for m, f in sorted(levels.items()) if m in existing]}


def roots(face: dict) -> list[str]:
    """Every constant of the face: the roots of the statement closure."""
    out = set()
    for m in (face.get("modules") or {}).values():
        out.update((m.get("constants") or {}).keys())
    return sorted(out)


def _imports(m: dict) -> list:
    imps = m.get("imports") or []
    if not m.get("full"):
        imps = [i for i in imps if i.get("exported")]
    return sorted((i["module"], i.get("all"), i.get("exported"), i.get("meta")) for i in imps)


def compare(base: dict, head: dict, max_items: int = 30) -> list[str]:
    """What the patch changed in the target's public face (problems in the
    gate's vocabulary; empty when the face is unchanged)."""
    P = "protected_unchanged: "
    problems: list[str] = []
    bmods, hmods = base.get("modules") or {}, head.get("modules") or {}
    for name in sorted(bmods):
        b = bmods[name]
        h = hmods.get(name)
        if h is None:
            problems.append(P + f"module {name} is imported, directly or through public imports, by files outside "
                            "the target; it must stay")
            continue
        if _imports(b) != _imports(h):
            problems.append(P + f"{name}: its {'imports' if b.get('full') else 'public imports'} changed; files "
                            "outside the target import this module and would see different modules")
        bc, hc = b.get("constants") or {}, h.get("constants") or {}
        for c in sorted(bc):
            if c not in hc:
                problems.append(P + f"{c} ({name}) is visible to files outside the target; it must stay")
            elif bc[c] != hc[c]:
                problems.append(P + f"{c} ({name}) is visible to files outside the target; its statement"
                                + ("" if bc[c].startswith(("theorem", "axiom")) else " or exposed value")
                                + " must stay exactly the same")
        for c in sorted(set(hc) - set(bc)):
            if b.get("full") and c.startswith("_private."):
                continue  # a new private helper of a module imported in full: invisible by name
            problems.append(P + f"{c} ({name}) would become visible to files outside the target; make it "
                            "`private`, or put it in a module that the target's public modules do not "
                            "`public import`")
        if sorted(b.get("attrs") or []) != sorted(h.get("attrs") or []):
            gone = sorted(set(b.get("attrs") or []) - set(h.get("attrs") or []))
            new = sorted(set(h.get("attrs") or []) - set(b.get("attrs") or []))
            problems.append(P + f"{name}: attributes that files outside the target use changed "
                            f"(removed {gone[:3]}, added {new[:3]}); keep @[simp], instances and "
                            "reducibility of public declarations as they are")
        be = {k: v for k, v in (b.get("ext_counts") or {}).items() if ext_counted(k)}
        he = {k: v for k, v in (h.get("ext_counts") or {}).items() if ext_counted(k)}
        if be != he:
            diff = sorted(k for k in set(be) | set(he) if be.get(k) != he.get(k))
            problems.append(P + f"{name}: entries that files outside the target see changed ({', '.join(diff[:5])}); "
                            "keep attributes, notation and instances of the public part as they are")
    for name in sorted(set(hmods) - set(bmods)):
        h = hmods[name]
        visible = [c for c in (h.get("constants") or {}) if not (h.get("full") and c.startswith("_private."))]
        if visible or h.get("attrs") or any(ext_counted(k) for k in (h.get("ext_counts") or {})):
            problems.append(P + f"{name} would become visible to files outside the target (through a public "
                            f"import) with {len(visible)} declaration(s); import it without `public`")
    return problems[:max_items] + ([P + f"... and {len(problems) - max_items} more"]
                                   if len(problems) > max_items else [])


def compare_union(base: dict | None, head: dict | None) -> list[str]:
    """The meaning of the public face: one statement closure over its
    constants, and the axioms behind them."""
    P = "protected_unchanged: "
    if not base or not head:
        return [P + "the public face could not be inspected"]
    bc, hc = base.get("closure") or {}, head.get("closure") or {}
    if bc.get("error") or hc.get("error"):
        return [P + "the statement closure of the public face could not be computed: "
                + str(bc.get("error") or hc.get("error"))[:300]]
    problems = []
    bd, hd = bc.get("dumps") or {}, hc.get("dumps") or {}
    for c in sorted(bd):
        if c not in hd:
            problems.append(P + f"{c} is part of what the target's public statements mean; it must stay")
        elif bd[c] != hd[c]:
            problems.append(P + f"{c} is part of what the target's public statements mean (a statement, or a "
                            "definition they mention); it must stay exactly the same")
    for c in sorted(set(hd) - set(bd)):
        problems.append(P + f"{c} would become part of what the target's public statements mean")
    if hc.get("missing"):
        problems.append(P + "the public face refers to missing constants: " + ", ".join(hc["missing"][:5]))
    new_ax = sorted(set(head.get("axioms") or []) - set(base.get("axioms") or []))
    if new_ax:
        problems.append("axioms_unchanged: the public statements would depend on new axioms: " + ", ".join(new_ax))
    if head.get("axioms_missing"):
        problems.append("axioms_unchanged: could not follow every dependency: "
                        + ", ".join(head["axioms_missing"][:5]))
    return problems[:30]
