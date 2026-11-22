#!/usr/bin/env python3
"""Accept a change to one target folder only when it is clearly a contribution.

    python3 tools/verify.py --root ~/Codes/upstream/cfsg --base <rev> --target FeitThompson \
        [--head <rev>] [--json out/verdict.json]

The change is the difference between --base and --head (default: the working
tree, untracked files included). The phases run cheapest first and the first
failure decides; every phase fails closed.

  scope      only .lean files under CFSG/<target>/ change, and new imports
             come from Mathlib or CFSG
  guards     the gate's source guard (tools/gate/guard.py): no new sorry,
             admit, native_decide, axiom, unsafe, implemented_by, extern,
             set_option, and no metaprogramming that runs code at compile
             time (#eval, run_cmd, initialize, elab, macro, syntax, printing
             attributes, Lean.* or IO code)
  size       the target's size in tokens (tools/size.py: whitespace, line
             breaks, comments and name lengths do not count) drops by at
             least --min-tokens
  build      `lake build` of every module of the target succeeds
  protected  on the built environment (tools/gate/CheckEnv.lean): every
             protected declaration has the recorded statement digest, its
             axioms are among propext, Classical.choice, Quot.sound, and no
             declaration of the target is metaprogramming

These are the gate's checks (docs/gate.md) minus the AI review and the
sandbox; passing them here means the gate's machine checks should pass.

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
sys.path.insert(0, os.path.join(HERE, "gate"))
from size import code_lines, tokens, tree_size  # noqa: E402
import env_facts  # noqa: E402
import guard  # noqa: E402

REPO = os.path.dirname(HERE)
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
                if not (imp.startswith("Mathlib") or imp.startswith("CFSG.")):
                    v["checks"]["paths_allowed"] = False
                    raise Reject(f"{f} imports {imp}, outside Mathlib and CFSG")
        v["checks"]["paths_allowed"] = True
        # guards: the gate's source guard, on the target folder before and after
        v["phase"] = "guards"
        hdr = subprocess.run(["git", "-C", root, "grep", "-h", "-E", r"^set_option [A-Za-z0-9_.]+ [A-Za-z0-9_.]+\s*$",
                              a.base, "--", folder], capture_output=True, text=True).stdout  # exit 1: no match
        counts = {}
        for l in hdr.splitlines():
            k = " ".join(l.split(":", 1)[-1].split()[1:3])
            counts[k] = counts.get(k, 0) + 1
        common = {k for k, n in counts.items() if n >= 100}
        with tempfile.TemporaryDirectory() as tmp:
            tb, th = os.path.join(tmp, "base"), os.path.join(tmp, "head")
            for f in files:
                for d, text in ((tb, read_base(root, a.base, f)), (th, read_head(root, a.head, f))):
                    if text is None:
                        continue
                    os.makedirs(os.path.dirname(os.path.join(d, f)), exist_ok=True)
                    open(os.path.join(d, f), "w", encoding="utf-8").write(text)
            os.makedirs(os.path.join(tb, folder), exist_ok=True)
            os.makedirs(os.path.join(th, folder), exist_ok=True)
            problems = guard.check_tree(tb, th, a.target, common)
        if problems:
            short = [p for p in problems if p.startswith("no_shortcuts")]
            v["checks"]["no_shortcuts"] = not short
            v["problems"] = problems[:30]
            raise Reject(problems[0])
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
        # protected: on the built environment, by the gate's checker
        v["phase"] = "protected"
        baseline_file = os.path.join(REPO, "data", "protected", f"{a.target}.json")
        with tempfile.TemporaryDirectory() as tmp:
            req, res = os.path.join(tmp, "request.json"), os.path.join(tmp, "facts.json")
            json.dump(env_facts.request(root, a.target, modules(root, folder)), open(req, "w"))
            r = subprocess.run(env_facts.command(root, req, res), cwd=root, capture_output=True, text=True,
                               timeout=3600, env=dict(os.environ, LEAN_PATH=env_facts.lean_path(root)))
            if r.returncode or not os.path.exists(res):
                v["checks"]["protected_unchanged"] = False
                v["log_tail"] = (r.stdout + r.stderr)[-3000:]
                raise Reject("the built environment could not be inspected")
            facts = env_facts.compact(json.load(open(res)))
        problems = env_facts.compare(facts, json.load(open(baseline_file)))
        v["checks"]["protected_unchanged"] = not any(p.startswith("protected_unchanged") for p in problems)
        v["checks"]["axioms_unchanged"] = not any(p.startswith("axioms_unchanged") for p in problems)
        if problems:
            v["problems"] = problems[:30]
            raise Reject(problems[0])
        v["axioms"] = sorted({ax for p in facts["protected"].values() for ax in p.get("axioms") or []})
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
