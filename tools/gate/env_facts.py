#!/usr/bin/env python3
"""Facts about a built target, read from its Lean environment as data.

    python3 tools/gate/env_facts.py facts --root ~/Codes/upstream/cfsg --target FeitThompson \
        --out out/env.json [--replay] [--raw out/env-raw.json] [--roots NAME ...]
    python3 tools/gate/env_facts.py compare --facts out/env.json [--baseline data/protected/FeitThompson.json]
    python3 tools/gate/env_facts.py baseline --facts out/env.json --out data/protected/FeitThompson.json

The facts come from tools/gate/CheckEnv.lean, which imports only `Lean`, loads
the target's modules at run time with `importModules` (every module as if by
`import all`, no environment extension initialised, no initializer run) and
reads `ConstantInfo` values. Statements are compared through a structural
printer (not the pretty-printer), so notation, unexpanders or delaborators
added by a pull request cannot make a changed statement look unchanged.

Library use (tools/gate/build_check.py): `request`, `lean_path`, `command`,
`compact`, `compare`.

Compact facts (`compact`):

    protected      {name: {exists, kind, module, level_params, closure_sha256,
                   closure (the structural dump), closure_members,
                   closure_missing, closure_error, axioms, axioms_missing}}
    meta_constants [{name, module, reasons}] target constants that are
                   unsafe, partial, implemented_by, extern, marked `meta`, or
                   refer to a constant under FORBIDDEN_PREFIXES that is not a
                   proof; Lean's own auto-parameter syntax (`f._auto_n`) and
                   well-founded `f._unsafe_rec` copies are not meta
    constants      number of target constants
    kinds          {name: def | theorem | inductive | structure | ctor |
                   recursor | axiom | opaque | quot} for every target constant
                   (instances are defs)
    uses           {name: number of other target constants whose type or
                   value refers to it} (names with 0 omitted)
    ranges         {name: [module, start line, end line]} for constants with a
                   declaration range (user-facing declarations)
    roots          the protected declarations and the extra roots
    reachable      target constants reachable from the roots through types
                   and values (the rest is cleanup material)
    replay         {ran, ok, seconds, error}
    seconds        {load, protected, scan, total}

Baseline (data/protected/<target>.json): {"protected": {name:
{"closure_sha256", "axioms", "kind", "closure"}}, "allowed_meta": [names of
meta constants present at the pinned upstream]}.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
CHECKER = os.path.join(HERE, "CheckEnv.lean")
PERMITTED_AXIOMS = ("propext", "Classical.choice", "Quot.sound")
CLOSURE_PREFIXES = ["CFSG"]

# A target constant whose type or value refers to a constant under one of
# these prefixes (by name components) is metaprogramming, unless the referred
# constant is a proof. What the pinned FeitThompson build refers to under them
# (32,437 constants): Lean.Syntax, Lean.Name, Lean.SourceInfo only from the 7
# auto-parameter syntax constants, Lean.Meta only through proofs
# (Lean.Meta.FastSubsingleton.elim and its instances, used by congr!), nothing
# else. Not listed because ordinary proofs use them: Lean.Omega, Lean.Grind,
# Lean.Data.AC, Mathlib.Tactic, Mathlib.Meta (ring, linarith, norm_num lemmas).
FORBIDDEN_PREFIXES = sorted([
    "Lean.Elab", "Lean.Meta", "Lean.Syntax", "Lean.TSyntax", "Lean.SyntaxNodeKind", "Lean.SourceInfo",
    "Lean.Macro", "Lean.MacroM", "Lean.MacroScope", "Lean.MonadQuotation", "Lean.MonadRef", "Lean.Unhygienic",
    "Lean.Quote", "Lean.PrettyPrinter", "Lean.Parser", "Lean.ParserDescr", "Lean.TrailingParserDescr",
    "Lean.Environment", "Lean.Expr", "Lean.Name", "Lean.Level", "Lean.MVarId", "Lean.FVarId",
    "Lean.LocalContext", "Lean.MetavarContext", "Lean.Core", "Lean.CoreM", "Lean.Compiler", "Lean.IR",
    "Lean.Kernel", "Lean.Declaration", "Lean.ConstantInfo", "Lean.Server", "Lean.Lsp", "Lean.Widget",
    "Lean.Language", "Lean.Json", "Lean.ToExpr", "Lean.Options", "Lean.KVMap", "Lean.DataValue",
    "Lean.MessageData", "Lean.Exception", "Lean.Linter", "Lean.EnvExtension", "Lean.PersistentEnvExtension",
    "Lean.SimplePersistentEnvExtension", "Lean.ScopedEnvExtension", "Lean.Attribute", "Lean.AttributeImpl",
    "Lean.ofReduceBool", "Lean.ofReduceNat", "Lean.reduceBool", "Lean.reduceNat", "Lean.trustCompiler",
    "Lean.Internal", "Qq", "ProofWidgets",
    "IO", "EIO", "BaseIO", "EStateM", "ST", "System",
    "unsafeCast", "unsafeBaseIO", "unsafeIO", "unsafeEIO", "ptrAddrUnsafe", "withPtrAddrUnsafe", "ptrEq",
])

# What the syntax constant of an auto-parameter `(h : P := by tac)` may refer to.
AUTOPARAM_REFS = sorted([
    "Lean.Syntax", "Lean.SourceInfo", "Lean.Name", "Lean.SyntaxNodeKind", "Lean.mkAtom", "Lean.mkAtomFrom",
    "Lean.mkIdent", "Lean.mkCIdent", "Lean.mkNode", "Lean.mkNullNode", "Array", "List", "String", "Substring",
    "Nat", "Option",
])


class CheckerError(Exception):
    pass


def read_text(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def read_json(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: str, data, **kw) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, **kw)
        fh.write("\n")


# ---------------------------------------------------------------- locating Lean

def module_prefix(target: str) -> str:
    return "CFSG." + target.replace("/", ".")


def target_modules(root: str, target: str) -> list[str]:
    folder = os.path.join(root, "CFSG", *target.split("/"))
    out = []
    for d, _, fs in os.walk(folder):
        for f in fs:
            if f.endswith(".lean"):
                out.append(os.path.relpath(os.path.join(d, f[:-5]), root).replace(os.sep, "."))
    if os.path.exists(folder + ".lean"):
        out.append(module_prefix(target))
    return sorted(out)


def elan_home() -> str:
    return os.environ.get("ELAN_HOME") or os.path.expanduser("~/.elan")


def toolchain_dir(root: str) -> str:
    """The elan toolchain named in <root>/lean-toolchain, e.g.
    leanprover/lean4:v4.35.0 -> $ELAN_HOME/toolchains/leanprover--lean4---v4.35.0."""
    name = read_text(os.path.join(root, "lean-toolchain")).strip()
    d = os.path.join(elan_home(), "toolchains", name.replace("/", "--").replace(":", "---"))
    if not os.path.isfile(os.path.join(d, "bin", "lean")):
        raise CheckerError(f"toolchain {name} is not installed at {d}")
    return d


def lean_path(root: str) -> str:
    """LEAN_PATH for a built checkout, without running lake."""
    root = os.path.abspath(root)
    parts = sorted(glob.glob(os.path.join(root, ".lake", "packages", "*", ".lake", "build", "lib", "lean")))
    parts.append(os.path.join(root, ".lake", "build", "lib", "lean"))
    parts.append(os.path.join(toolchain_dir(root), "lib", "lean"))
    return os.pathsep.join(parts)


def command(root: str, request_path: str, out_path: str) -> list[str]:
    """argv of the checker: the toolchain's own `lean` (not the elan proxy, not
    lake); run it with cwd = root and LEAN_PATH = lean_path(root)."""
    return [os.path.join(toolchain_dir(root), "bin", "lean"), "--run", CHECKER,
            os.path.abspath(request_path), os.path.abspath(out_path)]


def protected_names(target: str, repo: str = REPO) -> list[str]:
    txt = os.path.join(repo, "data", "protected", target + ".txt")
    if os.path.exists(txt):
        return [l.strip() for l in read_text(txt).splitlines() if l.strip() and not l.startswith("#")]
    return sorted(read_json(os.path.join(repo, "data", "protected", target + ".json")).get("protected", {}))


def request(root: str, target: str, modules: list[str] | None = None, replay: bool = False,
            roots: list[str] | None = None, protected: list[str] | None = None, emit_refs: bool = True) -> dict:
    return {
        "modules": sorted(modules if modules is not None else target_modules(root, target)),
        "target_prefix": module_prefix(target),
        "protected": list(protected if protected is not None else protected_names(target)),
        "roots": list(roots or []),
        "closure_prefixes": CLOSURE_PREFIXES,
        "forbidden_prefixes": FORBIDDEN_PREFIXES,
        "autoparam_refs": AUTOPARAM_REFS,
        "replay": bool(replay),
        "emit_refs": bool(emit_refs),
    }


def run(root: str, req: dict, timeout: int = 4 * 3600, extra_path: list[str] | None = None,
        log=None) -> dict:
    """Run the checker on `req` and return its raw output."""
    root = os.path.abspath(os.path.expanduser(root))
    with tempfile.TemporaryDirectory(prefix="envfacts-") as tmp:
        rq, out = os.path.join(tmp, "request.json"), os.path.join(tmp, "out.json")
        write_json(rq, req)
        lp = os.pathsep.join(list(extra_path or []) + [lean_path(root)])
        env = {"LEAN_PATH": lp, "HOME": os.environ.get("HOME", "/tmp")}
        r = subprocess.run(command(root, rq, out), cwd=root, env=env, capture_output=True, text=True,
                           timeout=timeout)
        if log:
            log.write(r.stdout + r.stderr)
        if r.returncode or not os.path.exists(out):
            raise CheckerError(f"CheckEnv exited with {r.returncode}: {(r.stdout + r.stderr).strip()[-2000:]}")
        return read_json(out)


# ---------------------------------------------------------------- facts

def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def meta_reasons(c: dict) -> list[str]:
    reasons = []
    if c.get("unsafe"):
        reasons.append("unsafe")
    if c.get("partial") and not c.get("wf_rec"):
        reasons.append("partial")
    if c.get("impl"):
        reasons.append("implemented_by " + c["impl"])
    if c.get("extern"):
        reasons.append("extern")
    if not c.get("autoparam"):
        if c.get("meta"):
            reasons.append("meta")
        forb = c.get("forbidden") or []
        if forb:
            reasons.append("refers to " + ", ".join(forb[:6]) + (f" and {len(forb) - 6} more" if len(forb) > 6 else ""))
    return reasons


def compact(raw: dict) -> dict:
    prot = {}
    for name, p in raw.get("protected", {}).items():
        if not p.get("exists"):
            prot[name] = {"exists": False}
            continue
        cl = p.get("closure") or {}
        dump = cl.get("dump")
        prot[name] = {
            "exists": True, "kind": p.get("kind"), "module": p.get("module"),
            "level_params": p.get("level_params", []),
            "closure_sha256": sha256(dump) if isinstance(dump, str) else None,
            "closure": dump, "closure_members": cl.get("members", []), "closure_missing": cl.get("missing", []),
            "closure_error": cl.get("error"),
            "axioms": p.get("axioms", []), "axioms_missing": p.get("axioms_missing", []),
        }
    meta, kinds, uses, ranges = [], {}, {}, {}
    for name, c in raw.get("constants", {}).items():
        kinds[name] = c["k"]
        if c.get("uses"):
            uses[name] = c["uses"]
        if c.get("range"):
            ranges[name] = [c["m"], c["range"][0], c["range"][1]]
        reasons = meta_reasons(c)
        if reasons:
            meta.append({"name": name, "module": c["m"], "reasons": reasons})
    rp = raw.get("replay") or {}
    ms = raw.get("ms") or {}
    return {
        "schema": "concept-mining-env-facts/v1",
        "lean_version": raw.get("lean_version"),
        "target_prefix": raw.get("target_prefix"),
        "modules_loaded": raw.get("modules_loaded"),
        "target_modules": raw.get("target_modules"),
        "protected": prot,
        "meta_constants": sorted(meta, key=lambda m: m["name"]),
        "constants": len(kinds),
        "kinds": kinds,
        "uses": uses,
        "ranges": ranges,
        "roots": raw.get("roots", []),
        "reachable": raw.get("reachable", []),
        "replay": {"ran": bool(rp.get("ran")), "ok": rp.get("ok"),
                   "seconds": round(rp["ms"] / 1000, 1) if rp.get("ms") is not None else None,
                   "error": rp.get("error")},
        "seconds": {k: round(v / 1000, 1) for k, v in ms.items() if isinstance(v, (int, float))},
    }


def _closure_lines(dump: str) -> dict[str, str]:
    """name -> line of a structural dump (`<kind> <name> …`)."""
    out = {}
    for line in (dump or "").splitlines()[1:]:
        parts = line.split(" ", 2)
        if len(parts) >= 2:
            out[parts[1]] = line
    return out


def explain_closure(found: str, expected: str) -> str:
    """A short human-readable account of how two structural dumps differ."""
    f, e = _closure_lines(found), _closure_lines(expected)
    notes = []
    added, removed = sorted(set(f) - set(e)), sorted(set(e) - set(f))
    if added:
        notes.append("now mentions " + ", ".join(added[:3]) + (" …" if len(added) > 3 else ""))
    if removed:
        notes.append("no longer mentions " + ", ".join(removed[:3]) + (" …" if len(removed) > 3 else ""))
    for n in sorted(set(f) & set(e)):
        x, y = f[n], e[n]
        if x != y:
            i = next((k for k in range(min(len(x), len(y))) if x[k] != y[k]), min(len(x), len(y)))
            lo = max(0, i - 40)
            notes.append(f"{n} differs at character {i}: expected …{y[lo:i + 60]}…, found …{x[lo:i + 60]}…")
            break
    return "; ".join(notes)


def compare(facts: dict, baseline: dict, max_meta: int = 30) -> list[str]:
    """Problems of `facts` against the baseline, in the gate's vocabulary."""
    problems: list[str] = []
    bprot = baseline.get("protected") or {}
    fprot = facts.get("protected") or {}
    if not bprot:
        problems.append("protected_unchanged: the baseline lists no protected declarations")
    for name in sorted(bprot):
        b, f = bprot[name], fprot.get(name)
        if not f:
            problems.append(f"protected_unchanged: {name} was not inspected")
            continue
        if not f.get("exists"):
            problems.append(f"protected_unchanged: {name} no longer exists")
            continue
        if f.get("closure_error"):
            problems.append(f"protected_unchanged: the statement of {name} could not be read: {f['closure_error']}")
        elif f.get("closure_sha256") != b.get("closure_sha256"):
            hint = explain_closure(f.get("closure") or "", b.get("closure") or "") if b.get("closure") else ""
            problems.append(f"protected_unchanged: the statement of {name} (or a CFSG definition it mentions) "
                            f"changed: digest {str(f.get('closure_sha256'))[:12]}, expected "
                            f"{str(b.get('closure_sha256'))[:12]}" + (f"; {hint}" if hint else ""))
        if f.get("closure_missing"):
            problems.append(f"protected_unchanged: the statement of {name} mentions constants missing from the "
                            "environment: " + ", ".join(f["closure_missing"][:5]))
        axs = f.get("axioms") or []
        if f.get("axioms_missing"):
            problems.append(f"axioms_unchanged: {name} depends on constants missing from the environment: "
                            + ", ".join(f["axioms_missing"][:5]))
        outside = sorted(set(axs) - set(PERMITTED_AXIOMS))
        if outside:
            problems.append(f"axioms_unchanged: {name} depends on {', '.join(outside)}, outside "
                            + ", ".join(PERMITTED_AXIOMS))
        elif sorted(axs) != sorted(b.get("axioms") or []):
            problems.append(f"axioms_unchanged: {name} depends on [{', '.join(axs)}], expected "
                            f"[{', '.join(b.get('axioms') or [])}]")
    for name in sorted(set(fprot) - set(bprot)):
        problems.append(f"protected_unchanged: {name} has no baseline entry")
    allowed = set(baseline.get("allowed_meta") or [])
    new_meta = [m for m in facts.get("meta_constants") or [] if m["name"] not in allowed]
    for m in new_meta[:max_meta]:
        problems.append(f"no_metaprogramming: {m['name']} ({'; '.join(m['reasons'])})")
    if len(new_meta) > max_meta:
        problems.append(f"no_metaprogramming: and {len(new_meta) - max_meta} more such declarations")
    rp = facts.get("replay") or {}
    if rp.get("ran") and not rp.get("ok"):
        problems.append("protected_unchanged: the kernel rejected the built environment on replay: "
                        + str(rp.get("error") or "")[:400])
    return problems


def make_baseline(facts: dict, target: str) -> dict:
    prot = {}
    for name, p in sorted(facts["protected"].items()):
        if not p.get("exists") or p.get("closure_error") or p.get("closure_missing") or p.get("axioms_missing"):
            raise CheckerError(f"{name}: not a usable baseline ({p})")
        prot[name] = {"kind": p["kind"], "closure_sha256": p["closure_sha256"], "axioms": p["axioms"],
                      "closure": p["closure"]}
    return {
        "schema": "concept-mining-protected/v1",
        "target": target,
        "lean_version": facts.get("lean_version"),
        "printer": "closure-v1 (tools/gate/CheckEnv.lean)",
        "closure_prefixes": CLOSURE_PREFIXES,
        "protected": prot,
        "allowed_meta": sorted(m["name"] for m in facts.get("meta_constants") or []),
    }


# ---------------------------------------------------------------- CLI

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("facts", help="inspect a built checkout")
    f.add_argument("--root", required=True)
    f.add_argument("--target", required=True)
    f.add_argument("--out", required=True)
    f.add_argument("--raw", default=None, help="also keep the checker's raw output")
    f.add_argument("--replay", action="store_true", help="re-check every target constant in the kernel")
    f.add_argument("--roots", nargs="*", default=[], help="extra roots for `reachable`")
    f.add_argument("--timeout", type=int, default=4 * 3600)
    c = sub.add_parser("compare", help="problems against the baseline (exit 1 if any)")
    c.add_argument("--facts", required=True)
    c.add_argument("--baseline", default=None)
    c.add_argument("--target", default=None, help="baseline data/protected/<target>.json")
    b = sub.add_parser("baseline", help="write data/protected/<target>.json from facts")
    b.add_argument("--facts", required=True)
    b.add_argument("--target", required=True)
    b.add_argument("--out", default=None)
    a = ap.parse_args()

    if a.cmd == "facts":
        root = os.path.abspath(os.path.expanduser(a.root))
        t0 = time.time()
        raw = run(root, request(root, a.target, replay=a.replay, roots=a.roots, emit_refs=bool(a.raw)),
                  timeout=a.timeout, log=sys.stderr)
        if a.raw:
            write_json(a.raw, raw)
        facts = compact(raw)
        facts["target"] = a.target
        facts["seconds"]["total"] = round(time.time() - t0, 1)
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        write_json(a.out, facts, indent=1, sort_keys=True)
        summary = {k: facts[k] for k in ("constants", "seconds", "replay")}
        summary["protected"] = {n: {k: p.get(k) for k in ("exists", "closure_sha256", "axioms")}
                                for n, p in facts["protected"].items()}
        summary["meta_constants"] = len(facts["meta_constants"])
        summary["reachable"] = len(facts["reachable"])
        print(json.dumps(summary, indent=1))
    elif a.cmd == "compare":
        path = a.baseline or os.path.join(REPO, "data", "protected", f"{a.target}.json")
        problems = compare(read_json(a.facts), read_json(path))
        for p in problems:
            print(p)
        sys.exit(1 if problems else 0)
    else:
        out = a.out or os.path.join(REPO, "data", "protected", f"{a.target}.json")
        write_json(out, make_baseline(read_json(a.facts), a.target), indent=1, sort_keys=True, ensure_ascii=False)
        print(out)


if __name__ == "__main__":
    main()
