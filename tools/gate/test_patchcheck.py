#!/usr/bin/env python3
"""Tests for tools/gate/patchcheck.py.

    python3 -m unittest discover -s tools -p 'test_*.py'
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from patchcheck import check_patch, touched_paths  # noqa: E402

T = "FeitThompson"
P = "CFSG/FeitThompson/Local/Example.lean"
SHA = "0123456789abcdef0123456789abcdef01234567"


def mail(diffs: str, subject: str = "Shorten a proof", sha: str = SHA, headers: str = "") -> str:
    return (f"From {sha} Mon Sep 17 00:00:00 2001\n"
            "From: A U Thor <author@example.com>\n"
            "Date: Sat, 21 Nov 2026 10:00:00 +0900\n"
            f"Subject: [PATCH] {subject}\n"
            "MIME-Version: 1.0\n"
            "Content-Type: text/plain; charset=UTF-8\n"
            "Content-Transfer-Encoding: 8bit\n"
            f"{headers}"
            "\n"
            "Replace a two-line proof by le_rfl.\n"
            "---\n"
            f" {P} | 3 +--\n"
            " 1 file changed, 1 insertion(+), 2 deletions(-)\n"
            "\n"
            f"{diffs}"
            "-- \n"
            "2.43.0\n"
            "\n")


def modify(path: str = P, a: str | None = None, b: str | None = None, mode: str = "100644") -> str:
    a, b = a or path, b or path
    return (f"diff --git a/{a} b/{b}\n"
            f"index 83db48f..bf269f4 {mode}\n"
            f"--- a/{a}\n"
            f"+++ b/{b}\n"
            "@@ -1,5 +1,3 @@\n"
            " theorem le_self' (H : Subgroup G) : H ≤ H := by\n"
            "-  intro x hx\n"
            "-  exact hx\n"
            "+  exact le_rfl\n"
            " -- removed a line comment below\n"
            "--- old comment\n")


def create(path: str, mode: str = "100644") -> str:
    return (f"diff --git a/{path} b/{path}\n"
            f"new file mode {mode}\n"
            "index 0000000..e69de29\n"
            "--- /dev/null\n"
            f"+++ b/{path}\n"
            "@@ -0,0 +1,2 @@\n"
            "+theorem t : True := trivial\n"
            "+-- note\n")


def delete(path: str) -> str:
    return (f"diff --git a/{path} b/{path}\n"
            "deleted file mode 100644\n"
            "index e69de29..0000000\n"
            f"--- a/{path}\n"
            "+++ /dev/null\n"
            "@@ -1 +0,0 @@\n"
            "-theorem t : True := trivial\n")


def rename(src: str, dst: str) -> str:
    return (f"diff --git a/{src} b/{dst}\n"
            "similarity index 100%\n"
            f"rename from {src}\n"
            f"rename to {dst}\n")


class Accepts(unittest.TestCase):
    def assertOk(self, text):
        self.assertEqual(check_patch(text, T), [])

    def test_modification(self):
        text = mail(modify())
        self.assertOk(text)
        self.assertEqual(touched_paths(text, T), [P])

    def test_create_delete_rename(self):
        new = "CFSG/FeitThompson/Local/New_2.lean"
        old = "CFSG/FeitThompson/Old.lean"
        text = mail(create(new) + delete(old) + rename(P, "CFSG/FeitThompson/Local/Moved.lean"))
        self.assertOk(text)
        self.assertEqual(touched_paths(text, T), sorted({new, old, P, "CFSG/FeitThompson/Local/Moved.lean"}))

    def test_prose_starting_with_from(self):
        self.assertOk(mail(modify()).replace("Replace a two-line", "From now on, replace a two-line"))

    def test_several_commits(self):
        self.assertOk(mail(modify()) + mail(create("CFSG/FeitThompson/A.lean"), sha="f" * 40))

    def test_no_newline_at_end(self):
        diff = modify().replace("--- old comment\n", "--- old comment\n\\ No newline at end of file\n")
        self.assertOk(mail(diff))


class Refuses(unittest.TestCase):
    def assertBad(self, text, needle=""):
        found = check_patch(text, T)
        self.assertTrue(found, "accepted")
        self.assertTrue(all(p.startswith("paths_allowed: ") for p in found), found)
        if needle:
            self.assertTrue(any(needle in p for p in found), found)
        return found

    def test_paths_outside_the_target(self):
        for path in ["CFSG/Other/X.lean", "lean/patches/FeitThompson/x.patch", ".lake/packages/mathlib/Mathlib.lean",
                     "CFSG/FeitThompson/../Other/X.lean", "CFSG/FeitThompson/.lake/X.lean", "lakefile.lean",
                     "CFSG/FeitThompson/x.py", "CFSG/FeitThompson/a-b.lean", "CFSG/FeitThompsonX/A.lean",
                     "/etc/passwd", "CFSG/FeitThompson/Évite.lean"]:
            self.assertBad(mail(modify(path)), "path")

    def test_rename_out_of_the_target(self):
        self.assertBad(mail(rename(P, "CFSG/Other/Moved.lean")), "rename to")
        self.assertBad(mail(rename(".lake/x.lean", P)), "rename from")

    def test_copy(self):
        diff = (f"diff --git a/{P} b/.lake/x.lean\nsimilarity index 100%\ncopy from {P}\ncopy to .lake/x.lean\n")
        self.assertBad(mail(diff), "copy to")

    def test_header_names_must_agree_with_the_rules(self):
        diff = modify().replace(f"+++ b/{P}", "+++ b/.lake/packages/mathlib/Mathlib.lean")
        self.assertBad(mail(diff), "+++")

    def test_modes(self):
        self.assertBad(mail(create("CFSG/FeitThompson/L.lean", mode="120000")), "symbolic link")
        self.assertBad(mail(create("CFSG/FeitThompson/S.lean", mode="160000")), "submodule")
        self.assertBad(mail(create("CFSG/FeitThompson/E.lean", mode="100755")), "executable")
        self.assertBad(mail(modify(mode="120000")), "symbolic link")
        chmod = f"diff --git a/{P} b/{P}\nold mode 100644\nnew mode 100755\n"
        self.assertBad(mail(chmod), "executable")

    def test_binary(self):
        diff = (f"diff --git a/{P} b/{P}\nindex 83db48f..bf269f4 100644\nGIT binary patch\nliteral 4\n"
                "LcmZ?d00001\n\n")
        self.assertBad(mail(diff), "binary")
        diff = f"diff --git a/{P} b/{P}\nindex 83db48f..bf269f4 100644\nBinary files a/{P} and b/{P} differ\n"
        self.assertBad(mail(diff), "binary")

    def test_quoted_paths(self):
        diff = modify().replace(f"diff --git a/{P} b/{P}", f'diff --git "a/{P}\\t" "b/{P}"')
        self.assertBad(mail(diff), "quoted")

    def test_not_a_format_patch(self):
        self.assertBad(modify(), "format-patch")
        self.assertBad(mail(""), "no `diff --git`")
        self.assertBad("From someone Sat Nov 21 10:00:00 2026\n\n" + modify(), "format-patch")

    def test_traditional_diff_hidden_in_the_patch(self):
        hidden = "--- a/.lake/x.lean\n+++ b/.lake/x.lean\n@@ -1 +1 @@\n-a\n+b\n"
        self.assertBad(mail(modify() + hidden), "diff --git")

    def test_corrupt_hunks(self):
        self.assertBad(mail(modify().replace("@@ -1,5 +1,3 @@", "@@ -1,9 +1,8 @@")), "hunk")
        self.assertBad(mail(modify().replace("+  exact le_rfl\n", "+  exact le_rfl\n+  extra\n")), "hunk")

    def test_hunk_counts_decide_what_is_a_header(self):
        # by its counts, the hunk ends before the second header: it is read as one
        second = modify("CFSG/Other/X.lean")
        self.assertBad(mail(modify() + second), "CFSG/Other/X.lean")

    def test_mail_encodings(self):
        self.assertBad(mail(modify()).replace("Content-Transfer-Encoding: 8bit", "Content-Transfer-Encoding: base64"),
                       "encoded")
        self.assertBad(mail(modify()).replace("charset=UTF-8", "charset=UTF-7"), "type")
        self.assertBad(mail(modify()).replace("text/plain; charset=UTF-8", 'multipart/mixed; boundary="x"'), "type")
        self.assertBad(mail(modify()).replace("Replace a two-line", "Content-Transfer-Encoding: quoted-printable\nReplace"),
                       "encoded")
        self.assertBad(mail(modify()).replace("Replace a two-line", "From evil Sat Nov 21 10:00:00 2026\nReplace"),
                       "another mail")

    def test_control_characters(self):
        self.assertBad(mail(modify()).replace(f"--- a/{P}", f"--- a/{P}\r"), "carriage return")
        self.assertBad(mail(modify()) + "\x00", "NUL")

    def test_size_limit(self):
        found = check_patch(mail(modify()), T, max_bytes=100)
        self.assertEqual(len(found), 1)
        self.assertIn("more than the limit of 100", found[0])

    def test_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = os.path.join(tmp, "good.patch")
            bad = os.path.join(tmp, "bad.patch")
            out = os.path.join(tmp, "out.json")
            with open(good, "w", encoding="utf-8") as fh:
                fh.write(mail(modify()))
            with open(bad, "w", encoding="utf-8") as fh:
                fh.write(mail(modify(".lake/x.lean")))
            script = os.path.join(HERE, "patchcheck.py")
            r = subprocess.run([sys.executable, script, good, "--target", T, "--json", out, "--list"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertIn(P, r.stdout)
            with open(out, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["paths"], [P])
            r = subprocess.run([sys.executable, script, bad, "--target", T], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
