#!/usr/bin/env python3
"""Step 2 of the contribution gate: apply, measure, build and inspect.

    python3 tools/gate/build_check.py --target FeitThompson --patch out/new.patch \
        --patch-name 0005-copies-foo.patch --upstream $RUNNER_TEMP/cfsg --out out/

Runs with no GitHub token at all. The patch is data until it has passed the
path check and the source guard; Lean (which runs code while compiling) only
ever runs inside the sandbox (tools/gate/sandbox.py). Phases, cheapest first;
the first failing phase ends the run:

  paths     the patch touches only CFSG/<target>/*.lean, as plain text files
  applies   base = pinned upstream + main's patches; head = the same series
            with the new patch inserted in file-name order (exactly what main
            will apply after the merge); every patch applies with `git am`
  guard     no new compile-time code, shortcuts or unusual options (count of
            each risky construct per file may not grow)
  size      the target shrinks by at least MIN_TOKENS Lean tokens
  build     base and head build in the sandbox
  inspect   the built environment (tools/gate/CheckEnv.lean, also sandboxed):
            protected statements unchanged (structural digest of the
            statement and of every CFSG definition it mentions), axioms within
            propext, Classical.choice, Quot.sound, no new metaprogramming,
            unsafe, partial, extern or implemented_by declarations

Writes out/facts.json, out/lean.diff (the source diff the AI review reads,
written before any Lean runs) and logs. Exit 0 when facts.json was written
(whatever the verdict), 75 when the run could not decide (setup failure).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, TOOLS)
import common  # noqa: E402
import env_facts  # noqa: E402
import guard  # noqa: E402
import patchcheck  # noqa: E402
import sandbox  # noqa: E402
from size import tree_size  # noqa: E402

AUX = re.compile(r"(^|\.)(_|match_\d|proof_\d|eq_\d|inst[A-Z])|\.(rec|recOn|casesOn|noConfusion|noConfusionType|"
                 r"below|brecOn|binductionOn|ibelow|inj|injEq|sizeOf_spec|ext_iff|mk\.inj\w*)$")


class Stop(Exception):
    """The verdict is decided (a check failed); facts are complete."""


class Setup(Exception):
    """The run could not decide; nothing about the pull request is implied."""


def git(root, *args, check=True, env=None):
    e = dict(os.environ, GIT_TERMINAL_PROMPT="0", **(env or {}))
    r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, env=e)
    if check and r.returncode:
        raise Setup(f"git {' '.join(args[:3])}: {r.stderr.strip()[-400:]}")
    return r


def am(root, patches: list[str]) -> str | None:
    """Apply patches in order; return the name of the first that fails."""
    ident = ["-c", "user.name=concept-mining", "-c", "user.email=concept-mining@users.noreply.github.com"]
    for p in patches:
        r = subprocess.run(["git", "-C", root, *ident, "am", "-q", "--keep-cr", p], capture_output=True, text=True)
        if r.returncode:
            subprocess.run(["git", "-C", root, "am", "--abort"], capture_output=True)
            return os.path.basename(p)
    return None


def modules(root: str, target: str) -> list[str]:
    folder = os.path.join(root, "CFSG", *target.split("/"))
    out = []
    for d, _, fs in os.walk(folder):
        for f in fs:
            if f.endswith(".lean"):
                out.append(os.path.relpath(os.path.join(d, f[:-5]), root).replace(os.sep, "."))
    if os.path.exists(folder + ".lean"):
        out.append(common.module_prefix(target))
    return sorted(out)


def header_options(root: str, rev: str, folder: str) -> set[str]:
    """`set_option NAME VALUE` lines that at least 100 files of the target use
    (the project's file-header convention, not a shortcut)."""
    r = git(root, "grep", "-h", "-E", r"^set_option [A-Za-z0-9_.]+ [A-Za-z0-9_.]+\s*$", rev, "--", folder,
            check=False)
    counts: dict[str, int] = {}
    for line in r.stdout.splitlines():
        k = " ".join(line.split(":", 1)[-1].split()[1:3])
        counts[k] = counts.get(k, 0) + 1
    return {k for k, n in counts.items() if n >= 100}


def export_tree(root: str, rev: str, folder: str, dest: str) -> None:
    os.makedirs(dest, exist_ok=True)
    tar = subprocess.run(["git", "-C", root, "archive", "--format=tar", rev, "--", folder], capture_output=True)
    if tar.returncode:
        raise Setup("git archive failed: " + tar.stderr.decode(errors="replace")[-300:])
    subprocess.run(["tar", "-x", "-C", dest], input=tar.stdout, check=True)


IMPORT = re.compile(r"^\s*(?:public\s+)?(?:meta\s+)?import\s+(?:all\s+)?([A-Za-z0-9_.'«»]+)", re.M)
MODULE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_']*(?:\.[A-Za-z0-9_']+)*")


def outside_imports(tree: str, target: str) -> list[str]:
    """Modules outside the target that the target's files under `tree` import."""
    prefix = common.module_prefix(target)
    found = set()
    for d, _, fs in os.walk(os.path.join(tree, "CFSG", *target.split("/"))):
        for fn in fs:
            if fn.endswith(".lean"):
                with open(os.path.join(d, fn), encoding="utf-8", errors="replace") as fh:
                    for m in IMPORT.findall(fh.read()):
                        if MODULE_NAME.fullmatch(m) and m != prefix and not m.startswith(prefix + "."):
                            found.add(m)
    return sorted(found)


def cleanup_tokens(root: str, base_env: dict, head_env: dict) -> int:
    """Tokens, in the base sources, of the declarations the patch deleted that
    were not reachable from the protected declarations."""
    from size import tokens
    reach = base_env.get("reachable")
    if reach is None:
        return 0
    reach = set(reach)
    ranges = base_env.get("ranges", {})
    gone = set(base_env.get("kinds", {})) - set(head_env.get("kinds", {}))
    spans: dict[str, list[tuple[int, int]]] = {}
    for n in gone:
        if n not in reach and n in ranges and not AUX.search(n):
            mod, start, end = ranges[n]
            spans.setdefault(mod, []).append((int(start), int(end)))
    total = 0
    for mod, iv in spans.items():
        r = git(root, "show", f"gate-base:{mod.replace('.', '/')}.lean", check=False)
        if r.returncode:
            continue
        lines = r.stdout.splitlines()
        merged: list[list[int]] = []
        for s, e in sorted(iv):
            if merged and s <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        for s, e in merged:
            try:
                total += tokens("\n".join(lines[s - 1:e]))
            except Exception:  # noqa: BLE001  (a range that splits a comment or string: count nothing)
                pass
    return total


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True)
    ap.add_argument("--patch", required=True, help="the pull request's patch (data)")
    ap.add_argument("--patch-name", required=True, help="its file name under lean/patches/<target>/")
    ap.add_argument("--upstream", required=True, help="work directory for the upstream checkout")
    ap.add_argument("--out", required=True)
    ap.add_argument("--build-timeout", type=int, default=150 * 60)
    ap.add_argument("--replay", action="store_true", help="kernel-replay the head environment")
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    up = os.path.abspath(os.path.expanduser(a.upstream))
    target = a.target
    folder = "CFSG/" + target
    f = {"schema": "concept-mining-facts/v1", "target": f"CFSG/{target}", "patch_name": a.patch_name,
         "candidate": common.candidate_of(a.patch_name), "fingerprint": common.fingerprint(target),
         "checks": {k: None for k in ("paths_allowed", "applies", "no_metaprogramming", "no_shortcuts",
                                      "saves_tokens", "build", "protected_unchanged", "axioms_unchanged")},
         "reasons": [], "setup_error": None, "tokens_before": None, "tokens_after": None, "cleanup_tokens": 0,
         "lines_saved": None, "concepts": [], "seconds": {}}
    upstream = dict(line.split("=", 1) for line in open(os.path.join(common.ROOT, "lean/UPSTREAM")).read().split())
    f["upstream_commit"] = upstream["commit"]
    code = 0

    def fail(check, reasons):
        f["checks"][check] = False
        f["reasons"] += [r if r.split(":", 1)[0] in f["checks"] else f"{check}: {r}" for r in reasons]
        raise Stop

    try:
        # paths
        text = open(a.patch, encoding="utf-8", errors="strict").read()
        problems = patchcheck.check_patch(text, target, max_bytes=common.MAX_PATCH_BYTES)
        if problems:
            fail("paths_allowed", problems)
        f["checks"]["paths_allowed"] = True

        # applies
        main_series = common.series(target)
        if a.patch_name in main_series:
            fail("applies", [f"{a.patch_name} already exists on main; give the patch a new name"])
        work = tempfile.mkdtemp(prefix="gate-series-")
        base_dir, head_dir = os.path.join(work, "base"), os.path.join(work, "head")
        os.makedirs(base_dir)
        os.makedirs(head_dir)
        for name in main_series:
            for d in (base_dir, head_dir):
                shutil.copyfile(os.path.join(common.ROOT, "lean/patches", target, name), os.path.join(d, name))
        shutil.copyfile(a.patch, os.path.join(head_dir, a.patch_name))
        if not os.path.isdir(os.path.join(up, ".git")):
            r = subprocess.run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", upstream["repo"], up],
                               capture_output=True, text=True)
            if r.returncode:
                raise Setup("cannot clone upstream: " + r.stderr[-300:])
            # all of CFSG: a patch may import modules outside its target (they
            # are built from source as dependencies); certificate data is not needed
            git(up, "sparse-checkout", "set", "--no-cone", "/*", "!/CFSG/Certificates/", "!/Certificates/")
        git(up, "checkout", "-q", "--force", upstream["commit"])
        git(up, "checkout", "-q", "-B", "gate-base")
        bad = am(up, [os.path.join(base_dir, n) for n in sorted(os.listdir(base_dir))])
        if bad:
            raise Setup(f"main's own patch {bad} does not apply to the pinned upstream")
        git(up, "checkout", "-q", "-B", "gate-head", upstream["commit"])
        bad = am(up, [os.path.join(head_dir, n) for n in sorted(os.listdir(head_dir))])
        if bad:
            fail("applies", [f"the series no longer applies at {bad} once your patch is inserted in file-name "
                             "order; regenerate the patch on top of the current main branch"])
        # what `git am` actually did, over the whole tree: only Lean files of
        # the target, only regular files
        raw = git(up, "diff", "--raw", "--no-renames", "-z", "gate-base", "gate-head").stdout.split("\0")
        bad = []
        for meta_, path in zip(raw[0::2], raw[1::2]):
            modes = meta_.split()[:2]
            if not (path.startswith(folder + "/") and path.endswith(".lean")) \
                    or any(m not in (":100644", "100644", ":000000", "000000") for m in modes):
                bad.append(path)
        if bad:
            fail("paths_allowed", [f"applying the patch changed {len(bad)} path(s) outside the target's Lean files: "
                                   + ", ".join(bad[:5])])
        f["checks"]["applies"] = True
        git(up, "checkout", "-q", "gate-base")

        # guard: compare the target folder of the two trees as text
        tb, th = os.path.join(work, "tree-base"), os.path.join(work, "tree-head")
        export_tree(up, "gate-base", folder, tb)
        export_tree(up, "gate-head", folder, th)
        problems = guard.check_tree(tb, th, target, header_options(up, "gate-base", folder))
        meta = [p for p in problems if not p.startswith("no_shortcuts")]
        short = [p for p in problems if p.startswith("no_shortcuts")]
        f["checks"]["no_metaprogramming"] = not meta
        f["checks"]["no_shortcuts"] = not short
        if problems:
            f["reasons"] += problems[:30]
            raise Stop

        # size, and the source diff for the review (before any Lean runs)
        b = tree_size(up, "gate-base", folder)
        h = tree_size(up, "gate-head", folder)
        f.update(tokens_before=b["tokens"], tokens_after=h["tokens"],
                 lines_saved=b["code_lines"] - h["code_lines"])
        diff = git(up, "diff", "--no-color", "--no-renames", "gate-base", "gate-head", "--", folder).stdout
        open(os.path.join(out, "lean.diff"), "w", encoding="utf-8").write(diff)
        saved = b["tokens"] - h["tokens"]
        if saved < common.MIN_TOKENS:
            fail("saves_tokens", [f"the change saves {saved} Lean tokens; at least {common.MIN_TOKENS} are "
                                  "required (comments, whitespace and name lengths do not count)"])
        f["checks"]["saves_tokens"] = True

        # build (sandboxed), base then head
        elan = os.environ.get("ELAN_HOME") or os.path.expanduser("~/.elan")
        lake = os.path.join(elan, "bin", "lake")
        r = subprocess.run([lake, "exe", "cache", "get"], cwd=up, capture_output=True, text=True, timeout=3600)
        open(os.path.join(out, "cache.log"), "w").write((r.stdout + r.stderr)[-20000:])
        ro = [p for p in (os.path.join(up, ".lake", "packages"), os.path.join(up, ".git")) if os.path.exists(p)]
        # the trusted checkout (scripts, baselines) and the gate's output must
        # not exist inside the sandbox; parents of the bind mounts do exist, empty
        sandbox.self_test(cwd=up, rw=[up], ro=ro, hidden=[common.ROOT, out], elan_home=elan)

        def build(label):
            mods = modules(up, target)
            t0 = time.time()
            r = sandbox.run([lake, "build", *mods], cwd=up, rw=[up], ro=ro, timeout=a.build_timeout, elan_home=elan)
            f["seconds"][f"build_{label}"] = round(time.time() - t0)
            open(os.path.join(out, f"build-{label}.log"), "w").write((r.stdout + r.stderr)[-200000:])
            return r, mods

        def inspect(label, mods, replay=False):
            scratch = tempfile.mkdtemp(prefix=f"gate-env-{label}-")
            req = os.path.join(scratch, "request.json")
            res = os.path.join(scratch, "facts.json")
            json.dump(env_facts.request(up, target, mods, replay=replay), open(req, "w"))
            t0 = time.time()
            r = sandbox.run(env_facts.command(up, req, res), cwd=up, rw=[scratch],
                            ro=[up, os.path.join(TOOLS, "gate")], timeout=3 * 3600, elan_home=elan,
                            env={"LEAN_PATH": env_facts.lean_path(up)})
            f["seconds"][f"inspect_{label}"] = round(time.time() - t0)
            open(os.path.join(out, f"inspect-{label}.log"), "w").write((r.stdout + r.stderr)[-50000:])
            if r.returncode or not os.path.exists(res):
                return None
            return env_facts.compact(json.load(open(res)))

        # Everything outside the target is trusted (the patch cannot touch
        # it): build the modules the target imports from outside it, and so
        # Mathlib's and the other packages' artifacts, here, outside the
        # sandbox, where Lake may write into .lake/packages and fetch widget
        # dependencies. Only module names are taken from the patched sources.
        outside = sorted(set(outside_imports(tb, target)) | set(outside_imports(th, target)))
        t0 = time.time()
        r = subprocess.run([lake, "build", *outside], cwd=up, capture_output=True, text=True, timeout=4 * 3600)
        f["seconds"]["build_outside"] = round(time.time() - t0)
        open(os.path.join(out, "build-outside.log"), "w").write((r.stdout + r.stderr)[-200000:])
        if r.returncode:
            # a missing module named by the patch fails here: that is the
            # patch's fault; anything else is a setup problem
            if any(m.startswith("CFSG.") for m in outside) and "unknown module" in (r.stdout + r.stderr):
                fail("build", ["an imported module does not exist: "
                               + ", ".join(m for m in outside if m.startswith("CFSG."))[:300]])
            raise Setup("the modules the target imports from outside it do not build")
        r, mods = build("base")
        if r.returncode:
            raise Setup("main does not build in the gate (base build failed); the maintainers must fix main")
        base_env = inspect("base", mods)
        if base_env is None:
            raise Setup("could not inspect the base environment")
        git(up, "checkout", "-q", "gate-head")
        # oleans of modules the patch deleted must not satisfy imports
        head_mods = set(modules(up, target))
        lib = os.path.join(up, ".lake", "build", "lib", "lean")
        for m in set(mods) - head_mods:
            stem = os.path.join(lib, *m.split("."))
            for ext in (".olean", ".olean.private", ".olean.server", ".ilean", ".trace", ".hash", ".c", ".ir"):
                if os.path.exists(stem + ext):
                    os.unlink(stem + ext)
        r, mods = build("head")
        if r.returncode:
            errs = [line for line in (r.stdout + r.stderr).splitlines() if "error" in line][:15]
            fail("build", ["Lean reports errors:"] + [e[:300] for e in errs])
        f["checks"]["build"] = True
        head_env = inspect("head", mods, replay=a.replay)
        if head_env is None and a.replay:
            # tell a kernel re-check that did not finish (memory, time) from
            # an environment that cannot be loaded at all
            if inspect("head-noreplay", mods) is not None:
                raise Setup("the kernel re-check of the built environment did not finish")
        if head_env is None:
            fail("build", ["the built environment could not be loaded for inspection"])
        problems = env_facts.compare(head_env, json.load(open(common.baseline_path(target))))
        for k in ("protected_unchanged", "axioms_unchanged", "no_metaprogramming"):
            mine = [p for p in problems if p.startswith(k)]
            f["checks"][k] = not mine if f["checks"].get(k) is not False else False
            f["reasons"] += mine
        f["replay"] = head_env.get("replay")
        if problems:
            raise Stop

        # cleanup: deleted declarations that nothing protected needed (dead
        # code) count at a quarter rate (docs/scoring.md)
        f["cleanup_tokens"] = min(cleanup_tokens(up, base_env, head_env), max(saved, 0))

        # concepts: new user-facing declarations and how often the target uses them
        new = sorted(set(head_env.get("kinds", {})) - set(base_env.get("kinds", {})))
        uses = head_env.get("uses", {})
        f["concepts"] = [{"name": n, "uses": int(uses.get(n, 0))} for n in new
                         if not AUX.search(n) and head_env["kinds"][n] in ("def", "theorem", "inductive", "structure")]
    except Stop:
        pass
    except Setup as e:
        f["setup_error"] = str(e)[:600]
        code = 75
    except (sandbox.SandboxError, subprocess.TimeoutExpired, UnicodeDecodeError) as e:
        if isinstance(e, UnicodeDecodeError):
            f["checks"]["paths_allowed"] = False
            f["reasons"].append("paths_allowed: the patch is not valid UTF-8 text")
        else:
            f["setup_error"] = f"{type(e).__name__}: {e}"[:600]
            code = 75
    json.dump(f, open(os.path.join(out, "facts.json"), "w"), indent=1)
    print(json.dumps({"checks": f["checks"], "reasons": f["reasons"][:5], "setup_error": f["setup_error"]}))
    sys.exit(code)


if __name__ == "__main__":
    main()
