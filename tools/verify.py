#!/usr/bin/env python3
"""Accept a change to one target folder only when it is clearly a contribution.

    python3 tools/verify.py --root ~/Codes/upstream/cfsg --base <rev> --target FeitThompson \
        [--head <rev>] [--json out/verdict.json]

The change is the difference between --base and --head (default: the working
tree, untracked files included). The phases run cheapest first and the first
failure decides; every phase fails closed.

  scope      only .lean files under CFSG/<target>/ change, and imports stay
             inside Mathlib and CFSG.<target>
  guards     added lines contain no sorry, admit, native_decide, axiom,
             unsafe, implemented_by, extern, kernel-check switches, and no
             metaprogramming that runs code at compile time (#eval, run_cmd,
             initialize, elab, macro, syntax, IO)
  size       the target's size in tokens (tools/size.py: whitespace, line
             breaks, comments and name lengths do not count) drops by at
             least --min-tokens
  build      `lake build` of every module of the target succeeds
  protected  `#check @n` and `#print axioms n` for every protected
             declaration print exactly the recorded baseline, and the axioms
             are among propext, Classical.choice, Quot.sound

Exit status: 0 accepted, 1 rejected, 75 could not be decided (setup error).
The JSON verdict has the fields documented in docs/contribute.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from size import code_lines, tokens, tree_size  # noqa: E402

REPO = os.path.dirname(HERE)
PERMITTED_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}
FORBIDDEN = re.compile(
    r"\bsorry\b|\badmit\b|\bnative_decide\b|^\s*(?:private\s+|protected\s+)?axiom\s|\bunsafe\b|implemented_by|"
    r"\bextern\b|debug\.skipKernelTC|Lean\.ofReduceBool|trustCompiler|^\s*@\[csimp\]|"
    # metaprogramming runs code while compiling; a refactor has no need for it
    r"#eval|#exit|\brun_cmd\b|\brun_tac\b|\b(?:builtin_)?initialize\b|^\s*(?:elab|macro|syntax|macro_rules|elab_rules)\b|"
    r"declare_syntax_cat|\bIO\.|\bunsafeCast\b|@\[(?:command_)?elab|^\s*(?:local\s+|scoped\s+)?(?:notation|infix[lr]?|prefix|postfix)\b|"
    # raising resource limits hides slow or looping proofs
    r"set_option\s+(?:maxHeartbeats|maxRecDepth|synthInstance\.maxHeartbeats|synthInstance\.maxSize|"
    r"maxSynthPendingDepth|exponentiation\.threshold)\b", re.M)
IMPORT = re.compile(r"^\s*(?:public\s+)?(?:meta\s+)?import\s+(?:all\s+)?(\S+)", re.M)


class Reject(Exception):
    pass


def git(root, *args):
    return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, check=True).stdout


def changed_files(root, base, head):
    if head:
        return git(root, "diff", "--name-only", base, head).split()
    out = set(git(root, "diff", "--name-only", base).split())
    out |= set(git(root, "ls-files", "--others", "--exclude-standard").split())
    return sorted(out)


def read_head(root, head, path):
    if head:
        try:
            return git(root, "show", f"{head}:{path}")
        except subprocess.CalledProcessError:
            return None
    full = os.path.join(root, path)
    return open(full, encoding="utf-8").read() if os.path.exists(full) else None


def read_base(root, base, path):
    try:
        return git(root, "show", f"{base}:{path}")
    except subprocess.CalledProcessError:
        return ""


def head_size(root, head, folder):
    if head:
        return tree_size(root, head, folder)
    tok = lines = n = 0
    for d, _, fs in os.walk(os.path.join(root, folder)):
        for f in fs:
            if f.endswith(".lean"):
                s = open(os.path.join(d, f), encoding="utf-8").read()
                tok += tokens(s)
                lines += code_lines(s)
                n += 1
    return {"tokens": tok, "code_lines": lines, "files": n}


def modules(root, folder):
    out = []
    for d, _, fs in os.walk(os.path.join(root, folder)):
        for f in fs:
            if f.endswith(".lean"):
                out.append(os.path.relpath(os.path.join(d, f[:-5]), root).replace(os.sep, "."))
    return sorted(out)


def probe(root, names, imports):
    body = "".join(f"import {m}\n" for m in imports)
    body += "".join(f"#check @{n}\n#print axioms {n}\n" for n in names)
    with tempfile.NamedTemporaryFile("w", suffix=".lean", dir=root, delete=False, encoding="utf-8") as f:
        f.write(body)
        path = f.name
    try:
        r = subprocess.run(["lake", "env", "lean", path], cwd=root, capture_output=True, text=True, timeout=3600)
        # stdout only: Lake prints unrelated notices on stderr
        return r.returncode, r.stdout.replace(path, "<probe>")
    finally:
        os.unlink(path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", default=None, help="revision to judge (default: working tree)")
    ap.add_argument("--target", required=True, help="folder under CFSG/, e.g. FeitThompson")
    ap.add_argument("--min-tokens", type=int, default=50)
    ap.add_argument("--allow-growth", type=int, default=0,
                    help="investment rule (off by default): accept a change that grows the target by at most "
                         "this many tokens; the verdict is marked investment=true and must be paid back by later "
                         "patches using the concept (tools/concept_credit.py)")
    ap.add_argument("--skip-build", action="store_true", help="cheap phases only (never accepts)")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    root = os.path.expanduser(a.root)
    folder = f"CFSG/{a.target}"
    pilot = os.path.join(REPO, "data", "pilot", a.target)
    v = {"target": a.target, "base": git(root, "rev-parse", a.base).strip(),
         "head": git(root, "rev-parse", a.head).strip() if a.head else "worktree",
         "verdict": "error", "phase": None, "reason": "",
         # check names shared with docs/scoring.md; None = not reached
         "checks": {"paths_allowed": None, "no_shortcuts": None, "build": None,
                    "protected_unchanged": None, "axioms_unchanged": None}}
    code = 75
    try:
        # scope
        v["phase"] = "scope"
        files = changed_files(root, a.base, a.head)
        v["files_changed"] = len(files)
        if not files:
            raise Reject("no change")
        outside = [f for f in files if not (f.startswith(folder + "/") and f.endswith(".lean"))]
        if outside:
            v["checks"]["paths_allowed"] = False
            raise Reject("changes outside the target: " + ", ".join(outside[:5]))
        for f in files:
            s = read_head(root, a.head, f) or ""
            before = set(IMPORT.findall(read_base(root, a.base, f)))
            for imp in set(IMPORT.findall(s)) - before:
                if not (imp.startswith("Mathlib") or imp == f"CFSG.{a.target}" or imp.startswith(f"CFSG.{a.target}.")):
                    v["checks"]["paths_allowed"] = False
                    raise Reject(f"{f} imports {imp}, outside Mathlib and CFSG.{a.target}")
        v["checks"]["paths_allowed"] = True
        # guards: only lines that the change adds
        v["phase"] = "guards"
        # file headers such as `set_option maxSynthPendingDepth 3` are the
        # project's convention, not a shortcut: allow options already used in
        # at least 100 files of the target at base
        hdr = git(root, "grep", "-h", "-E", r"^set_option ", a.base, "--", folder)
        common = {l.split(":", 1)[-1].strip() for l in hdr.splitlines()}
        counts = {}
        for l in hdr.splitlines():
            k = l.split(":", 1)[-1].strip()
            counts[k] = counts.get(k, 0) + 1
        common = {k for k, n in counts.items() if n >= 100}
        for f in files:
            new = read_head(root, a.head, f) or ""
            old = set(read_base(root, a.base, f).splitlines()) | common
            added = "\n".join(l for l in new.splitlines() if l not in old)
            m = FORBIDDEN.search(added)
            if m:
                v["checks"]["no_shortcuts"] = False
                raise Reject(f"{f} adds forbidden construct: {m.group(0).strip()}")
        v["checks"]["no_shortcuts"] = True
        # size
        v["phase"] = "size"
        b = tree_size(root, a.base, folder)
        h = head_size(root, a.head, folder)
        v.update(tokens_before=b["tokens"], tokens_after=h["tokens"], tokens_saved=b["tokens"] - h["tokens"],
                 code_lines_before=b["code_lines"], code_lines_after=h["code_lines"],
                 code_lines_saved=b["code_lines"] - h["code_lines"])
        v["investment"] = False
        if v["tokens_saved"] < a.min_tokens:
            if a.allow_growth and v["tokens_saved"] >= -a.allow_growth:
                v["investment"] = True
            else:
                raise Reject(f"saves {v['tokens_saved']} tokens, less than the required {a.min_tokens}")
        if a.skip_build:
            v["verdict"], v["reason"] = "unchecked", "cheap phases passed; build skipped"
            code = 75
            raise StopIteration
        if a.head:
            raise RuntimeError("build and protected phases judge the working tree; check out --head first")
        # build
        v["phase"] = "build"
        t0 = time.time()
        mods = modules(root, folder)
        r = subprocess.run(["nice", "-n", "15", "lake", "build", *mods], cwd=root, capture_output=True, text=True)
        v["build_seconds"] = round(time.time() - t0)
        if r.returncode != 0:
            errs = [l for l in (r.stdout + r.stderr).splitlines() if "error:" in l]
            v["log_tail"] = "\n".join(errs[:20])[-3000:]
            v["checks"]["build"] = False
            raise Reject("build failed")
        v["checks"]["build"] = True
        # protected
        v["phase"] = "protected"
        plist = os.path.join(REPO, "data", "protected", f"{a.target}.txt")
        prot = [l.strip() for l in open(plist if os.path.exists(plist) else os.path.join(pilot, "protected.txt")) if l.strip()]
        imports = [l.strip() for l in open(os.path.join(pilot, "protected_imports.txt")) if l.strip()]
        baseline = open(os.path.join(pilot, "protected_baseline.txt"), encoding="utf-8").read()
        rc, out = probe(root, prot, imports)
        if rc != 0:
            v["checks"]["protected_unchanged"] = False
            raise Reject("protected declarations do not elaborate")
        is_ax = lambda l: "depends on axioms" in l or "does not depend on any axioms" in l
        split = lambda t: ([l for l in t.splitlines() if not is_ax(l)], [l for l in t.splitlines() if is_ax(l)])
        (st_new, ax_new), (st_old, ax_old) = split(out), split(baseline)
        v["checks"]["protected_unchanged"] = st_new == st_old
        v["checks"]["axioms_unchanged"] = ax_new == ax_old
        if not v["checks"]["protected_unchanged"]:
            raise Reject("protected statement changed")
        if not v["checks"]["axioms_unchanged"]:
            raise Reject("axioms of a protected declaration changed")
        axioms = set(re.findall(r"\b(propext|Classical\.choice|Quot\.sound|[\w.]+)\b",
                                " ".join(re.findall(r"depends on axioms: \[([^\]]*)\]", out))))
        if not axioms <= PERMITTED_AXIOMS:
            raise Reject("axioms outside " + ", ".join(sorted(PERMITTED_AXIOMS)))
        v["axioms"] = sorted(axioms)
        v["verdict"], v["phase"], v["reason"] = "accept", "done", ""
        code = 0
    except Reject as e:
        v["verdict"], v["reason"] = "reject", str(e)
        code = 1
    except StopIteration:
        pass
    except Exception as e:  # noqa: BLE001
        v["verdict"], v["reason"] = "error", f"{type(e).__name__}: {e}"[:500]
        code = 75
    if a.json:
        os.makedirs(os.path.dirname(os.path.abspath(a.json)), exist_ok=True)
        json.dump(v, open(a.json, "w"), indent=2)
    print(json.dumps({k: v.get(k) for k in ("verdict", "phase", "reason", "tokens_saved", "code_lines_saved")}))
    sys.exit(code)


if __name__ == "__main__":
    main()
