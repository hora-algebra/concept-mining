#!/usr/bin/env python3
"""Fix the baseline of a new target folder, so that contribute.py and verify.py can work on it.

    python3 tools/setup_target.py --target Permutation --root ~/Codes/upstream/cfsg-work \
        --cache ~/.cache/concept-mining/proofmap [--skip-probe] [--skip-measure]

The checkout at --root must be the pinned upstream commit with the target's
patches applied, and the target must be built (`lake build` of its modules).

Writes
    data/pilot/<target>/decls.tsv, summary.json, unreachable_modules.tsv
                          from the proof-map graph (tools/island.py)
    data/protected/<target>.txt and data/pilot/<target>/protected.txt
                          every declaration of the target that a declaration
                          outside the target uses, whether or not the final
                          theorem needs it (stricter than island.py, so that
                          no other folder can stop building)
    data/pilot/<target>/protected_imports.txt
                          the modules that hold those declarations, and every
                          module of the target that a file outside the target
                          imports (the probe fails if one of them disappears)
    data/pilot/<target>/protected_baseline.txt
                          `#check @n` and `#print axioms n` of the protected
                          declarations at the base (the same probe as verify.py)
    data/pilot/<target>/baseline.json
                          code lines and needed code lines (tools/ledger.py measure)

The target may be nested (ThirdParty/QiuzhenCFSG).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from verify import probe  # noqa: E402

IMPORT = re.compile(r"^\s*(?:public\s+)?(?:meta\s+)?import\s+(?:all\s+)?(\S+)", re.M)


def outside_imports(root: str, prefix: str) -> set[str]:
    """Modules under `prefix` imported by some .lean file of CFSG outside `prefix`."""
    folder = os.path.join(root, *prefix.split("."))
    out = set()
    for d, dirs, fs in os.walk(os.path.join(root, "CFSG")):
        if os.path.abspath(d) == os.path.abspath(folder):
            dirs[:] = []
            continue
        for f in fs:
            if not f.endswith(".lean"):
                continue
            p = os.path.join(d, f)
            if p == folder + ".lean":
                continue
            head = open(p, encoding="utf-8", errors="replace").read(20000)
            for m in IMPORT.findall(head):
                if m == prefix or m.startswith(prefix + "."):
                    out.add(m)
    for top in ("CFSG.lean", "CFSGWithCertificates.lean", "Certificates.lean"):
        p = os.path.join(root, top)
        if os.path.exists(p):
            for m in IMPORT.findall(open(p, encoding="utf-8").read()):
                if m == prefix or m.startswith(prefix + "."):
                    out.add(m)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True, help="folder under CFSG/, e.g. Permutation")
    ap.add_argument("--root", required=True)
    ap.add_argument("--cache", default="~/.cache/concept-mining/proofmap")
    ap.add_argument("--skip-probe", action="store_true")
    ap.add_argument("--skip-measure", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(os.path.expanduser(a.root))
    prefix = "CFSG." + a.target.replace("/", ".")
    pilot = os.path.join(REPO, "data", "pilot", a.target)
    os.makedirs(pilot, exist_ok=True)
    subprocess.run([sys.executable, os.path.join(HERE, "island.py"), "--cache", os.path.expanduser(a.cache),
                    "--prefix", prefix, "--out", pilot], check=True, stdout=subprocess.DEVNULL)
    rows = list(csv.DictReader(open(os.path.join(pilot, "decls.tsv"), encoding="utf-8"), delimiter="\t"))
    prot = sorted({r["name"] for r in rows if int(r["users_outside"]) > 0})
    mods = {r["module"] for r in rows if int(r["users_outside"]) > 0}
    mods |= outside_imports(root, prefix)
    # modules that no longer exist at this commit would make the probe fail for the wrong reason
    missing = [m for m in mods if not os.path.exists(os.path.join(root, *m.split(".")) + ".lean")]
    if missing:
        raise SystemExit(f"modules of the graph missing in the checkout: {missing[:5]}")
    text = "\n".join(prot) + "\n"
    for p in (os.path.join(pilot, "protected.txt"), os.path.join(REPO, "data", "protected", a.target + ".txt")):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(text)
    open(os.path.join(pilot, "protected_imports.txt"), "w").write("\n".join(sorted(mods)) + "\n")
    spath = os.path.join(pilot, "summary.json")
    s = json.load(open(spath))
    s.update(protected=len(prot), protected_rule="used outside the target (needed by the final theorem or not)",
             protected_modules=len(mods))
    json.dump(s, open(spath, "w"), indent=2)
    print(f"{len(prot)} protected declarations in {len(mods)} modules")
    if not a.skip_probe:
        code, out = probe(root, prot, sorted(mods))
        if code != 0:
            sys.stderr.write(out[-3000:])
            raise SystemExit("the protected declarations do not elaborate at the base")
        open(os.path.join(pilot, "protected_baseline.txt"), "w", encoding="utf-8").write(out)
        print("protected_baseline.txt written")
    if not a.skip_measure:
        subprocess.run([sys.executable, os.path.join(HERE, "ledger.py"), "measure", "--root", root,
                        "--prefix", prefix, "--protected", os.path.join(pilot, "protected.txt"),
                        "--out", os.path.join(pilot, "baseline.json")], check=True)
        os.replace(os.path.join(pilot, "baseline.json") + ".decls.tsv", os.path.join(REPO, "out", f"{a.target.replace('/', '_')}-base.decls.tsv")) \
            if os.path.isdir(os.path.join(REPO, "out")) else None
        print(json.dumps(json.load(open(os.path.join(pilot, "baseline.json")))["needed_code_lines"]))


if __name__ == "__main__":
    main()
