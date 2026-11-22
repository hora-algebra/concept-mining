#!/usr/bin/env python3
"""Cases for the gate's self-test workflow (branch only).

    python3 tools/gate/selftest_cases.py CASE OUTDIR          # make out/new.patch
    python3 tools/gate/selftest_cases.py --check CASE OUTDIR  # compare facts.json
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common  # noqa: E402

TARGET = "FeitThompson"
EXPECT = {
    "resubmit": {"paths_allowed": True, "applies": True, "no_metaprogramming": True, "no_shortcuts": True,
                 "saves_tokens": True, "build": True, "protected_unchanged": True, "axioms_unchanged": True},
    "eval": {"no_metaprogramming": False},
    "unexpander": {"no_metaprogramming": False},
    "string-comment": {"saves_tokens": False},
    "outside-path": {"paths_allowed": False},
    "new-public": {"paths_allowed": True, "applies": True, "saves_tokens": True, "build": True,
                   "protected_unchanged": False},
}


def sh(*cmd, cwd=None):
    subprocess.run(cmd, cwd=cwd, check=True)


def craft(out: str, edit) -> None:
    """A format-patch on top of main's series, made by `edit(root)`."""
    root = os.path.join(os.environ.get("RUNNER_TEMP", "/tmp"), "craft")
    env = dict(os.environ, SPARSE_TARGET_ONLY="1")
    subprocess.run([os.path.join(common.ROOT, "tools/apply_patches.sh"), root, TARGET], env=env, check=True)
    edit(root)
    sh("git", "-C", root, "add", "-A")
    sh("git", "-C", root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "selftest")
    p = subprocess.run(["git", "-C", root, "format-patch", "-1", "--stdout"], capture_output=True, text=True,
                       check=True).stdout
    open(os.path.join(out, "new.patch"), "w").write(p)
    open(os.path.join(out, "patch_name"), "w").write("9999-selftest.patch")


def first_file(root):
    d = os.path.join(root, "CFSG", TARGET)
    for dd, _, fs in sorted(os.walk(d)):
        for f in sorted(fs):
            if f.endswith(".lean"):
                return os.path.join(dd, f)


def append(text):
    def edit(root):
        with open(first_file(root), "a") as fh:
            fh.write(text)
    return edit


def main() -> None:
    if sys.argv[1] == "--check":
        case, out = sys.argv[2], sys.argv[3]
        f = json.load(open(os.path.join(out, "facts.json")))
        bad = {k: (v, f["checks"].get(k)) for k, v in EXPECT[case].items() if f["checks"].get(k) is not v}
        if bad or f.get("setup_error"):
            sys.exit(f"{case}: unexpected {bad} setup_error={f.get('setup_error')} reasons={f['reasons'][:5]}")
        print(f"{case}: as expected; reasons: {f['reasons'][:3]}")
        return
    case, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    if case == "resubmit":
        name = common.series(TARGET)[-1]
        src = os.path.join(common.ROOT, "lean/patches", TARGET, name)
        open(os.path.join(out, "new.patch"), "w").write(open(src).read())
        os.unlink(src)  # main without it; the gate sees it as new
        open(os.path.join(out, "patch_name"), "w").write(name)
    elif case == "new-public":
        # main's latest patch as new, plus a declaration that files outside the
        # target would see: the public face changes
        name = common.series(TARGET)[-1]
        src = os.path.join(common.ROOT, "lean/patches", TARGET, name)
        data = open(src).read()
        os.unlink(src)

        def edit(root):
            subprocess.run(["git", "-C", root, "-c", "user.name=t", "-c", "user.email=t@t", "am", "-q", "--keep-cr"],
                           input=data, text=True, check=True)
            sh("git", "-C", root, "reset", "-q", "--soft", "HEAD~1")
            with open(os.path.join(root, "CFSG", TARGET, "OddOrderTheorem.lean"), "a") as fh:
                fh.write("\ntheorem selftestPublic : True := trivial\n")
        craft(out, edit)
    elif case == "eval":
        craft(out, append("\n#eval (1 : Nat) + 1\n"))
    elif case == "unexpander":
        craft(out, append("\n/- -- -/ @[app_unexpander Nat.succ] def selftestU : Lean.PrettyPrinter.Unexpander :="
                          " fun _ => throw ()\n"))
    elif case == "string-comment":
        def edit(root):
            p = first_file(root)
            s = open(p).read()
            head, _, rest = s.partition("\n\n")
            open(p, "w").write(head + '\n\ndef selftestH1 := "/-"\n\n' + rest + '\ndef selftestH2 := "-/"\n')
        craft(out, edit)
    elif case == "outside-path":
        def edit(root):
            with open(os.path.join(root, "lakefile.toml"), "a") as fh:
                fh.write("\n# selftest\n")
        craft(out, edit)
    else:
        sys.exit(f"unknown case {case}")


if __name__ == "__main__":
    main()
