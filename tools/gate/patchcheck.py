#!/usr/bin/env python3
"""Refuse an inner patch that could write anything but Lean files of its target.

    python3 tools/gate/patchcheck.py lean/patches/<target>/<name>.patch --target FeitThompson \
        [--max-bytes N] [--json OUT] [--list]

The patch must be the output of `git format-patch` (an mbox of one or more
commits) whose diffs only add, change, rename or delete ordinary files
`CFSG/<target>/…/Name.lean` (mode 100644). It is read the way `git am` reads
it (git mailsplit, mailinfo and apply), and anything it would read
differently is refused rather than guessed: paths outside the target or with
`..`, `.lake`, quotes, escapes, control characters or unusual characters;
other file modes, symlinks (120000) and submodules (160000); binary patches;
diffs without a `diff --git` header; corrupt hunks; mail parts in base64,
quoted-printable, another charset or multipart; and patches larger than
--max-bytes. Problems start with `paths_allowed: `.

Exit status 0 if acceptable, 2 if not. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

CHECK = "paths_allowed"
FORMAT_PATCH_FROM = re.compile(r"From [0-9a-f]{40} Mon Sep 17 00:00:00 2001")
HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
INDEX = re.compile(r"index [0-9a-f]{7,64}\.\.[0-9a-f]{7,64}(?: (\d{6}))?")
SIMILARITY = re.compile(r"(?:dis)?similarity index \d{1,3}%")
OK_MODE = "100644"
HEADER_PREFIXES = ("old mode ", "new mode ", "deleted file mode ", "new file mode ", "copy from ",
                   "copy to ", "rename from ", "rename to ", "similarity index ", "dissimilarity index ",
                   "index ", "--- ", "+++ ")


def _path_re(target: str) -> re.Pattern:
    return re.compile(rf"CFSG/{re.escape(target)}/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+\.lean")


def _is_from_line(line: str) -> bool:
    """git mailsplit's is_from_line: would git am start a new mail here?"""
    if len(line) < 19 or not line.startswith("From "):
        return False
    k = len(line) - 1
    while True:
        if k < 5:
            return False
        k -= 1
        if line[k] == ":":
            break
    digit = lambda j: 0 <= j < len(line) and line[j].isdigit()  # noqa: E731
    if not all(digit(j) for j in (k - 4, k - 2, k - 1, k + 1, k + 2)):
        return False
    year = re.match(r"\s*[+-]?(\d+)", line[k + 3:])
    return bool(year) and int(year.group(1)) > 90


MIME_HEADER = re.compile(r"(?i)(content-transfer-encoding|content-type)\s*:\s*(.*)")


class _Parser:
    def __init__(self, text: str, target: str):
        self.lines = text.split("\n")
        if self.lines and self.lines[-1] == "":
            self.lines.pop()
        self.target = target
        self.path_ok = _path_re(target)
        self.problems: list[str] = []
        self.paths: list[str] = []

    def bad(self, i: int, why: str) -> None:
        self.problems.append(f"{CHECK}: patch line {i + 1}: {why}")

    def path(self, i: int, p: str, what: str) -> None:
        if p != "/dev/null":
            self.paths.append(p)
        if p == "/dev/null" and what in ("---", "+++"):
            return
        if '"' in p or "\\" in p:
            self.bad(i, f"{what} path {p[:80]!r} is quoted or escaped; use plain ASCII file names")
        elif any(ord(c) < 32 or ord(c) == 127 for c in p):
            self.bad(i, f"{what} path contains control characters")
        elif ".." in p or ".lake" in p or p.startswith("/"):
            self.bad(i, f"{what} path {p[:80]!r} leaves the target folder")
        elif not self.path_ok.fullmatch(p):
            self.bad(i, f"{what} path {p[:80]!r} is not a Lean file CFSG/{self.target}/…/Name.lean "
                        "(letters, digits and _ only)")

    def mode(self, i: int, mode: str, what: str) -> None:
        if mode != OK_MODE:
            kind = {"120000": "a symbolic link", "160000": "a submodule", "100755": "an executable file",
                    "040000": "a directory"}.get(mode, f"mode {mode}")
            self.bad(i, f"{what} makes {kind}; only ordinary files (mode 100644) may change")

    # -- mail headers ------------------------------------------------------
    def mail_headers(self, i: int) -> int:
        """Check the header block of the message whose From line is i;
        return the index of the first body line."""
        j = i + 1
        headers = []
        while j < len(self.lines) and self.lines[j] != "":
            line = self.lines[j]
            if line[:1] in (" ", "\t") and headers:
                headers[-1] = (headers[-1][0], headers[-1][1] + " " + line.strip())
            else:
                name, _, value = line.partition(":")
                headers.append((j, name.strip().lower() + ":" + value.strip()))
            j += 1
        for k, h in headers:
            name, _, value = h.partition(":")
            self.mime(k, name, value)
        return j

    def mime(self, k: int, name: str, value: str) -> None:
        """git mailinfo decodes base64/quoted-printable parts, other charsets
        and multipart mails before git apply sees them: refuse all of that."""
        name, v = name.lower(), value.strip().lower()
        if name == "content-transfer-encoding" and v not in ("7bit", "8bit"):
            self.bad(k, f"mail part is encoded ({value.strip()[:40]}); send the plain output of git format-patch")
        elif name == "content-type":
            charset = re.search(r"charset\s*=\s*\"?([^\";\s]+)", v)
            if not v.startswith("text/plain") or (charset and charset.group(1) not in
                                                  ("utf-8", "utf8", "us-ascii")):
                self.bad(k, f"mail part has type {value.strip()[:60]!r}; send plain UTF-8 text from git format-patch")

    # -- diffs -------------------------------------------------------------------
    def git_header(self, i: int) -> int:
        line = self.lines[i]
        rest = line[len("diff --git "):]
        if '"' in rest or "\\" in rest:
            self.bad(i, "diff header has quoted or escaped paths; use plain ASCII file names")
        parts = rest.split(" ")
        if len(parts) != 2 or not parts[0].startswith("a/") or not parts[1].startswith("b/"):
            self.bad(i, f"cannot read the diff header {line[:100]!r}")
        else:
            self.path(i, parts[0][2:], "diff a/")
            self.path(i, parts[1][2:], "diff b/")
        j = i + 1
        saw_names = False
        while j < len(self.lines):
            h = self.lines[j]
            if h.startswith("GIT binary patch") or (h.startswith("Binary files ") and h.endswith(" differ")):
                self.bad(j, "binary patch; only text changes to .lean files are accepted")
                j += 1
                continue
            if not h.startswith(HEADER_PREFIXES):
                break
            if h.startswith(("old mode ", "new mode ", "deleted file mode ", "new file mode ")):
                what, _, mode = h.rpartition(" ")
                self.mode(j, mode, what)
            elif h.startswith(("copy from ", "copy to ", "rename from ", "rename to ")):
                what = " ".join(h.split(" ", 2)[:2])
                self.path(j, h[len(what) + 1:], what)
            elif h.startswith("index "):
                m = INDEX.fullmatch(h)
                if not m:
                    self.bad(j, f"cannot read {h[:80]!r}")
                elif m.group(1):
                    self.mode(j, m.group(1), "index line")
            elif h.startswith(("similarity index ", "dissimilarity index ")):
                if not SIMILARITY.fullmatch(h):
                    self.bad(j, f"cannot read {h[:80]!r}")
            elif h.startswith("--- "):
                p = h[4:]
                self.path(j, p[2:] if p.startswith("a/") else p, "---")
                if not (p.startswith("a/") or p == "/dev/null"):
                    self.bad(j, f"cannot read {h[:80]!r}")
                saw_names = True
            elif h.startswith("+++ "):
                p = h[4:]
                self.path(j, p[2:] if p.startswith("b/") else p, "+++")
                if not (p.startswith("b/") or p == "/dev/null"):
                    self.bad(j, f"cannot read {h[:80]!r}")
                saw_names = True
            j += 1
        if j < len(self.lines) and self.lines[j].startswith("@@ -"):
            if not saw_names:
                self.bad(j, "hunk without ---/+++ lines")
            j = self.hunks(j)
        return j

    def hunks(self, j: int) -> int:
        """Consume consecutive hunks the way git apply counts their lines."""
        while j < len(self.lines) and self.lines[j].startswith("@@ -"):
            m = HUNK.match(self.lines[j])
            if not m:
                self.bad(j, f"cannot read the hunk header {self.lines[j][:80]!r}")
                return j + 1
            old = int(m.group(2)) if m.group(2) is not None else 1
            new = int(m.group(4)) if m.group(4) is not None else 1
            j += 1
            while old > 0 or new > 0:
                if j >= len(self.lines):
                    self.bad(j - 1, "the last hunk is cut short")
                    return j
                line = self.lines[j]
                c = line[:1]
                if c in (" ", ""):
                    old -= 1
                    new -= 1
                elif c == "-":
                    old -= 1
                elif c == "+":
                    new -= 1
                elif c == "\\":
                    pass
                else:
                    self.bad(j, "corrupt hunk (a line does not start with space, + or -)")
                    return j
                if old < 0 or new < 0:
                    self.bad(j, "corrupt hunk (more lines than its header says)")
                    return j + 1
                j += 1
            if j < len(self.lines) and self.lines[j].startswith("\\ "):
                j += 1
        return j

    def run(self) -> None:
        lines = self.lines
        if not lines or not FORMAT_PATCH_FROM.fullmatch(lines[0]):
            self.bad(0, "not a git format-patch file (it must start with `From <commit sha> Mon Sep 17 "
                        "00:00:00 2001`); create it with git format-patch")
            return
        diffs = 0
        i = 0
        while i < len(lines):
            line = lines[i]
            if FORMAT_PATCH_FROM.fullmatch(line):
                i = self.mail_headers(i)
                continue
            if _is_from_line(line):
                self.bad(i, "a line that git am would take for the start of another mail; reword it")
            m = MIME_HEADER.match(line)
            if m:
                self.mime(i, m.group(1), m.group(2))
            if line.startswith("diff --git "):
                diffs += 1
                i = self.git_header(i)
                continue
            if line.startswith("diff ") or line.startswith("Index: "):
                self.bad(i, f"diff that is not in git format: {line[:80]!r}")
            elif line.startswith("@@ -"):
                self.bad(i, "hunk without a diff --git header")
                i = self.hunks(i)
                continue
            elif line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
                self.bad(i, "diff without a diff --git header")
            elif line.startswith("GIT binary patch") or (line.startswith("Binary files ")
                                                          and line.endswith(" differ")):
                self.bad(i, "binary patch; only text changes to .lean files are accepted")
            i += 1
        if diffs == 0:
            self.bad(0, "no `diff --git` in the patch")


def _parse(text: str, target: str) -> _Parser:
    p = _Parser(text, target)
    if not re.fullmatch(r"[A-Za-z0-9_]+", target):
        p.problems.append(f"{CHECK}: invalid target {target!r}")
        return p
    if "\x00" in text:
        p.problems.append(f"{CHECK}: the patch contains NUL bytes (binary data)")
        return p
    if "\r" in text:
        line = text[:text.index("\r")].count("\n") + 1
        p.problems.append(f"{CHECK}: patch line {line}: carriage return in the patch; use Unix line endings")
        return p
    p.run()
    return p


def check_patch(text: str, target: str, max_bytes: int = 1_000_000) -> list[str]:
    """Problems of a format-patch mbox for CFSG/<target>/ (empty if fine)."""
    size = len(text.encode("utf-8", "surrogateescape"))
    if size > max_bytes:
        return [f"{CHECK}: the patch is {size} bytes, more than the limit of {max_bytes}; split it"]
    return _parse(text, target).problems


def touched_paths(text: str, target: str) -> list[str]:
    """Every path named by the diff headers (a/ and b/ sides, renames and
    copies), sorted, without /dev/null. Meaningful once check_patch passed."""
    return sorted(set(_parse(text, target).paths))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("patch")
    ap.add_argument("--target", required=True)
    ap.add_argument("--max-bytes", type=int, default=1_000_000)
    ap.add_argument("--json")
    ap.add_argument("--list", action="store_true", help="print the touched paths when acceptable")
    a = ap.parse_args()
    with open(a.patch, "rb") as fh:
        raw = fh.read(a.max_bytes + 1)
    try:
        text = raw.decode("utf-8")
        problems = check_patch(text, a.target, a.max_bytes)
    except UnicodeDecodeError:
        problems = [f"{CHECK}: the patch is not UTF-8 text"]
    if len(raw) > a.max_bytes:
        problems = [f"{CHECK}: the patch is larger than the limit of {a.max_bytes} bytes; split it"]
    paths = [] if problems else touched_paths(text, a.target)
    for p in problems:
        print(p)
    if a.list:
        for p in paths:
            print(p)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump({"ok": not problems, "reasons": problems, "paths": paths}, fh, indent=1)
    sys.exit(2 if problems else 0)


if __name__ == "__main__":
    main()
