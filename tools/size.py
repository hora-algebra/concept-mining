#!/usr/bin/env python3
"""Size of Lean source that formatting cannot change.

The size of a file is the number of Lean tokens outside comments: an
identifier (however long, dots included), a number, a string literal, or one
symbol. Whitespace, line breaks and comments count for nothing, so joining
lines or shortening names does not make a file smaller; only removing actual
terms, binders, tactic steps or declarations does.

    python3 tools/size.py FILE...            # tokens per file and total
    python3 tools/size.py --git ROOT REV DIR # tokens of DIR at a git revision
"""

from __future__ import annotations

import re
import subprocess
import sys

COMMENT = re.compile(r"/-.*?-/|--[^\n]*", re.S)
TOKEN = re.compile(
    r"""
    "(?:[^"\\]|\\.)*"                                   # string literal
  | «[^»]*»                                             # quoted name
  | [A-Za-z_À-ɏͰ-Ͽἀ-῿℀-⅏\U0001D400-\U0001D7FF]
    [\w'!?₀-₉À-ɏͰ-Ͽἀ-῿℀-⅏\U0001D400-\U0001D7FF]*
    (?:\.[A-Za-z_À-ɏͰ-Ͽἀ-῿℀-⅏\U0001D400-\U0001D7FF]
       [\w'!?₀-₉À-ɏͰ-Ͽἀ-῿℀-⅏\U0001D400-\U0001D7FF]*)*  # name
  | \d+(?:\.\d+)?                                       # number
  | :=|=>|<-|->|<;>|\.\.|::|\|\||&&|≠|≤|≥                # common multi-char symbols
  | \S                                                  # any other symbol
    """,
    re.X,
)


def strip_comments(src: str) -> str:
    # nested block comments: remove innermost first
    prev = None
    while prev != src:
        prev = src
        src = re.sub(r"/-(?:(?!/-|-/).)*?-/", " ", src, flags=re.S)
    return re.sub(r"--[^\n]*", " ", src)


def tokens(src: str) -> int:
    return len(TOKEN.findall(strip_comments(src)))


def code_lines(src: str) -> int:
    return sum(1 for l in strip_comments(src).splitlines() if l.strip())


def tree_size(root: str, rev: str, directory: str) -> dict:
    """Tokens and code lines of every .lean file under directory at rev."""
    files = subprocess.run(["git", "-C", root, "ls-tree", "-r", "--name-only", rev, directory],
                           capture_output=True, text=True, check=True).stdout.split()
    tok = lines = 0
    per = {}
    for f in files:
        if f.endswith(".lean"):
            s = subprocess.run(["git", "-C", root, "show", f"{rev}:{f}"], capture_output=True,
                               text=True, check=True).stdout
            t = tokens(s)
            per[f] = t
            tok += t
            lines += code_lines(s)
    return {"tokens": tok, "code_lines": lines, "files": len(per), "per_file": per}


def main() -> None:
    a = sys.argv[1:]
    if a[:1] == ["--git"]:
        r = tree_size(a[1], a[2], a[3])
        print(r["tokens"], r["code_lines"], r["files"])
        return
    total = 0
    for p in a:
        t = tokens(open(p, encoding="utf-8").read())
        total += t
        print(t, p)
    print(total, "total")


if __name__ == "__main__":
    main()
