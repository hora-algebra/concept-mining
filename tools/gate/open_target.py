#!/usr/bin/env python3
"""Open a target for contributions: build it on main and write its baseline.

    python3 tools/gate/open_target.py --target ThirdParty/QiuzhenCFSG/Glauberman \
        --upstream $RUNNER_TEMP/cfsg --out out/

Everything built here is trusted (the pinned upstream and main's patches; no
pull request is involved), so nothing runs in the sandbox. The baseline
(`data/protected/<target>.json`, policy `interface`) records what may never
grow: the axioms behind the target's public face and the metaprogramming
declarations already present. The face itself is compared with main's on every
pull request (tools/gate/interface.py). Writes out/<target as file name>.json,
out/open-target.json (sizes, timings) and logs; exit 0 on success, 75 when the
target could not be opened (the reason is printed and written).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, TOOLS)
import build_check  # noqa: E402
import common  # noqa: E402
import env_facts  # noqa: E402
import interface  # noqa: E402

PERMITTED_AXIOMS = ["Classical.choice", "Quot.sound", "propext"]


class Fail(Exception):
    pass


def run(cmd, cwd, timeout, log, env=None):
    t0 = time.time()
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    open(log, "w").write((r.stdout + r.stderr)[-200000:])
    return r, round(time.time() - t0)


def checker(up, req, out, label, interface_mode=False):
    rq, res = os.path.join(out, f"{label}-request.json"), os.path.join(out, f"{label}.json")
    json.dump(req, open(rq, "w"))
    env = {"LEAN_PATH": env_facts.lean_path(up), "HOME": os.environ.get("HOME", "/tmp")}
    r, secs = run(env_facts.command(up, rq, res, interface=interface_mode), up, 4 * 3600,
                  os.path.join(out, f"{label}.log"), env=env)
    if r.returncode or not os.path.exists(res):
        raise Fail(f"{label} failed (see {label}.log)")
    return json.load(open(res)), secs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True)
    ap.add_argument("--upstream", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--build-timeout", type=int, default=5 * 3600)
    a = ap.parse_args()
    target, out = a.target, os.path.abspath(a.out)
    up = os.path.abspath(os.path.expanduser(a.upstream))
    os.makedirs(out, exist_ok=True)
    info = {"target": target, "seconds": {}, "error": None}
    code = 0
    try:
        if not common.PATCH_PATH.match(f"lean/patches/{target}/0001-x.patch"):
            raise Fail(f"{target!r} is not a target name (folders under CFSG/, letters, digits and _)")
        others = [t for t in common.supported_targets() if t != target]
        clash = common.overlapping_targets(others + [target])
        if clash:
            raise Fail("the target would overlap an open target: " + ", ".join(clash))
        upstream = dict(l.split("=", 1) for l in open(os.path.join(common.ROOT, "lean/UPSTREAM")).read().split())
        if not os.path.isdir(os.path.join(up, ".git")):
            r = subprocess.run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", upstream["repo"], up],
                               capture_output=True, text=True)
            if r.returncode:
                raise Fail("cannot clone upstream: " + r.stderr[-300:])
            build_check.git(up, "sparse-checkout", "set", "--no-cone", "/*", "!/Certificates/**",
                            "/Certificates/**/*.lean")
        build_check.git(up, "checkout", "-q", "--force", upstream["commit"])
        build_check.git(up, "checkout", "-q", "-B", "gate-main")
        patches = [os.path.join(common.ROOT, "lean/patches", t, n)
                   for t in others + [target] for n in common.series(t)]
        bad = build_check.am(up, patches)
        if bad:
            raise Fail(f"main's patch {bad} does not apply to the pinned upstream")
        folder = os.path.join(up, "CFSG", *target.split("/"))
        if not os.path.isdir(folder):
            raise Fail(f"CFSG/{target} does not exist at the pinned upstream")
        mods = build_check.modules(up, target)
        prefix = common.module_prefix(target)
        entry = interface.entries(up, target)
        levels = interface.interface(interface.target_headers(up, target), entry, prefix)
        info.update(modules=len(mods), entries=len(entry), interface_modules=len(levels),
                    full=sum(1 for v in levels.values() if v))
        elan = os.environ.get("ELAN_HOME") or os.path.expanduser("~/.elan")
        lake = os.path.join(elan, "bin", "lake")
        r, info["seconds"]["cache"] = run([lake, "exe", "cache", "get"], up, 3600, os.path.join(out, "cache.log"))
        r, info["seconds"]["build"] = run([lake, "build", *mods], up, a.build_timeout, os.path.join(out, "build.log"))
        if r.returncode:
            raise Fail("the target does not build on main (see build.log)")
        face, info["seconds"]["face"] = checker(up, interface.request(levels, set(mods)), out, "face", True)
        roots = interface.roots(face)
        raw, info["seconds"]["inspect"] = checker(
            up, env_facts.request(up, target, mods, protected=[], union_roots=roots), out, "inspect")
        facts = env_facts.compact(raw)
        u = facts.get("union") or {}
        if (u.get("closure") or {}).get("error"):
            raise Fail("the statement closure of the public face could not be computed: "
                       + str(u["closure"]["error"])[:300])
        if u.get("axioms_missing"):
            raise Fail("dependencies missing from the environment: " + ", ".join(u["axioms_missing"][:5]))
        info.update(face_constants=len(roots), closure=len((u.get("closure") or {}).get("dumps") or {}),
                    axioms=u.get("axioms"))
        baseline = {
            "schema": "concept-mining-protected/v2",
            "target": target,
            "policy": "interface",
            "lean_version": facts.get("lean_version"),
            "upstream_commit": upstream["commit"],
            "axioms": sorted(u.get("axioms") or []),
            "allowed_meta": sorted(m["name"] for m in facts.get("meta_constants") or []),
            "interface": {"entries": len(entry), "modules": len(levels), "constants": len(roots)},
        }
        dest = os.path.join(out, target.replace("/", "__") + ".json")
        json.dump(baseline, open(dest, "w"), indent=1, sort_keys=True)
        info["baseline"] = dest
        extra = sorted(set(baseline["axioms"]) - set(PERMITTED_AXIOMS))
        if extra:
            info["note"] = "the public face already depends on " + ", ".join(extra)
    except (Fail, build_check.Setup, subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
        info["error"] = str(e)[:600]
        code = 75
    json.dump(info, open(os.path.join(out, "open-target.json"), "w"), indent=1)
    print(json.dumps(info))
    sys.exit(code)


if __name__ == "__main__":
    main()
