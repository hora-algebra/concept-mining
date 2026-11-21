#!/usr/bin/env python3
"""Export the elaborated declarations of one folder of a built CFSG checkout.

    python3 tools/export_decls.py --root ~/Codes/upstream/cfsg \
        --prefix CFSG.FeitThompson --out out/ft_decls.tsv

Generates a Lean file that imports every module of the folder followed by
tools/lean/ExportDecls.lean, runs it with `lake env lean` (niced), and leaves
the TSV described there. The folder must have been built (`lake build`).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def modules(root: str, prefix: str) -> list[str]:
    base = os.path.join(root, *prefix.split("."))
    mods = []
    for d, _, fs in os.walk(base):
        for f in fs:
            if f.endswith(".lean"):
                rel = os.path.relpath(os.path.join(d, f[:-5]), root)
                mods.append(rel.replace(os.sep, "."))
    if os.path.exists(base + ".lean"):
        mods.append(prefix)
    return sorted(mods)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    root = os.path.expanduser(a.root)
    out = os.path.abspath(a.out)
    body = open(os.path.join(HERE, "lean", "ExportDecls.lean"), encoding="utf-8").read()
    src = "".join(f"import {m}\n" for m in modules(root, a.prefix)) + body
    # the export walks every constant of the folder; no heartbeat limit for this tool run
    src += f'\nset_option maxHeartbeats 0 in\n#eval exportDecls `{a.prefix} "{out}"\n'
    with tempfile.NamedTemporaryFile("w", suffix=".lean", dir=root, delete=False, encoding="utf-8") as f:
        f.write(src)
        path = f.name
    try:
        subprocess.run(["nice", "-n", "15", "lake", "env", "lean", path], cwd=root, check=True)
    finally:
        os.unlink(path)


if __name__ == "__main__":
    main()
