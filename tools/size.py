#!/usr/bin/env python3
"""Size of Lean source that formatting cannot change.

The size of a file is the number of Lean tokens outside comments: an
identifier (however long, dots included), a number, a string literal, or one
symbol. Whitespace, line breaks and comments count for nothing, so joining
lines or shortening names does not make a file smaller; only removing actual
terms, binders, tactic steps or declarations does.

Tokens come from tools/lean_lex.py, which reads comments and strings exactly
as Lean does (a `"/-"` string does not open a comment). Symbols are grouped as
before: := => <- -> <;> .. :: || && count as one token, any other symbol
character as one. A file Lean could not lex raises lean_lex.LexError.

    python3 tools/size.py FILE...            # tokens per file and total
    python3 tools/size.py --git ROOT REV DIR # tokens of DIR at a git revision
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lean_lex import COMMENT_KINDS, LexError, tokenize  # noqa: E402

# Legacy regex tokenizer, kept for the analysis tools that split text they
# have already cut out of a file (skeletons.py, data_share.py, ...). The size
# measure itself no longer uses it.
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

__all__ = ["LexError", "TOKEN", "code_lines", "strip_comments", "tokens", "tree_size"]


def _blank_comments(src: str, toks) -> str:
    out, last = [], 0
    for t in toks:
        if t.kind in COMMENT_KINDS:
            out.append(src[last:t.start])
            out.append("\n" * t.text.count("\n"))
            last = t.end
    out.append(src[last:])
    return "".join(out)


def strip_comments(src: str) -> str:
    """src with every comment blanked out (line breaks kept). For analysis
    tools: a file Lean could not lex falls back to the old approximation."""
    src = src.replace("\r\n", "\n")
    try:
        return _blank_comments(src, tokenize(src))
    except LexError:
        prev = None
        while prev != src:
            prev = src
            src = re.sub(r"/-(?:(?!/-|-/).)*?-/", lambda m: re.sub(r"[^\n]", " ", m.group()), src, flags=re.S)
        return re.sub(r"--[^\n]*", "", src)


def tokens(src: str) -> int:
    """Number of Lean tokens outside comments. Raises LexError."""
    return sum(1 for t in tokenize(src) if t.kind not in COMMENT_KINDS)


def code_lines(src: str) -> int:
    """Number of non-blank lines once comments are removed. Raises LexError."""
    src = src.replace("\r\n", "\n")
    return sum(1 for line in _blank_comments(src, tokenize(src)).splitlines() if line.strip())


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
