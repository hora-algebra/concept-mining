#!/usr/bin/env python3
"""Refuse patches that could run code while Lean compiles them.

Lean can execute arbitrary code at compile time (#eval, run_cmd, initialize,
new macros and elaborators, ...). A pull request that does so could tamper
with its own verdict, so the trusted workflow scans the added lines of every
patch BEFORE building, and does not build at all if one of these appears.
Refactoring proofs and definitions never needs them.

    python3 tools/site/scan_patch.py patches/C02/change.patch [...] [--json out.json]

Exit status 0 if clean, 2 if something forbidden was added. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

FORBIDDEN = [
    (r"#eval\b|#exit\b|run_cmd\b|run_elab\b|run_meta\b", "runs code at compile time"),
    (r"^\s*(?:@\[[^\]]*\]\s*)*(?:local\s+|scoped\s+)?(?:macro|macro_rules|syntax|elab|elab_rules|declare_syntax_cat|notation3?)\b",
     "defines new syntax, macros or elaborators"),
    (r"\binitialize\b|\bbuiltin_initialize\b", "runs code when the module is loaded"),
    (r"\bunsafe\b|implemented_by|@\[extern|\bopaque\b.*IO", "unsafe or foreign code"),
    (r"\bIO\b|\bIO\.|System\.|\bProcess\b", "uses IO or the operating system"),
    (r"^\s*import\s+(?!Mathlib|CFSG|Certificates|TauCeti|Batteries|Aesop|Qq|Plausible|ProofWidgets)", "imports a new package"),
    (r"\bsorry\b|\badmit\b|native_decide|^\s*axiom\b", "shortcut that is not a proof"),
    (r"set_option\s+(?:maxHeartbeats|maxRecDepth|synthInstance\.maxHeartbeats)", "raises a resource limit"),
]
COMPILED = [(re.compile(p, re.M), why) for p, why in FORBIDDEN]


def scan(text: str, name: str) -> list[str]:
    problems = []
    file = name
    for i, line in enumerate(text.splitlines(), start=1):
        if line.startswith("+++ "):
            file = line[4:].strip().removeprefix("b/")
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        code = re.sub(r"--.*$", "", line[1:])
        for rx, why in COMPILED:
            if rx.search(code):
                problems.append(f"no_metaprogramming: {file}: added line {code.strip()[:80]!r} {why}")
                break
    return problems


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("patches", nargs="*")
    ap.add_argument("--json")
    a = ap.parse_args()
    problems = []
    for p in a.patches:
        with open(p, encoding="utf-8", errors="replace") as fh:
            problems += scan(fh.read(), p)
    for p in problems:
        print(p)
    if a.json:
        with open(a.json, "w") as fh:
            json.dump({"ok": not problems, "reasons": problems}, fh, indent=1)
    sys.exit(2 if problems else 0)


if __name__ == "__main__":
    main()
