#!/usr/bin/env python3
"""Tests for tools/prune_unreachable.py on small synthetic exports.

    python3 tools/test_prune_unreachable.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prune_unreachable  # noqa: E402

MOD = "CFSG.T.M"


def row(name, s, e, uses=()):
    # name, module, kind, start, end, -, -, -, uses
    return "\t".join([name, MOD, "theorem", str(s), str(e), "", "", "", " ".join(uses)]) + "\n"


class PruneTest(unittest.TestCase):
    def run_prune(self, source, before, after, protected):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "CFSG", "T"))
        lean = os.path.join(d, "CFSG", "T", "M.lean")
        open(lean, "w").write(source)
        files = {}
        for key, rows in (("before", before), ("after", after)):
            files[key] = os.path.join(d, key + ".tsv")
            open(files[key], "w").write("".join(rows))
        files["protected"] = os.path.join(d, "protected.txt")
        open(files["protected"], "w").write("\n".join(protected) + "\n")
        prune_unreachable.main(["--root", d, "--before", files["before"], "--after", files["after"],
                                "--protected", files["protected"]])
        return open(lean).read() if os.path.exists(lean) else None

    def test_keeps_helpers_of_remaining_unneeded_declarations(self):
        # root used helper before; afterwards only the unneeded `unused` still uses it
        src = ("theorem helper : True := trivial\n"
               "\n"
               "theorem unused : True := helper\n"
               "\n"
               "theorem root : True := trivial\n")
        before = [row("helper", 1, 1), row("unused", 3, 3, ["helper"]), row("root", 5, 5, ["helper"])]
        after = [row("helper", 1, 1), row("unused", 3, 3, ["helper"]), row("root", 5, 5)]
        out = self.run_prune(src, before, after, ["root"])
        self.assertIn("theorem helper", out)
        self.assertIn("theorem unused", out)

    def test_deletes_helper_no_one_uses(self):
        src = ("theorem helper : True := trivial\n"
               "\n"
               "theorem root : True := trivial\n")
        before = [row("helper", 1, 1), row("root", 3, 3, ["helper"])]
        after = [row("helper", 1, 1), row("root", 3, 3)]
        out = self.run_prune(src, before, after, ["root"])
        self.assertNotIn("helper", out)
        self.assertIn("theorem root", out)

    def test_attributed_declaration_above_is_not_taken_as_attribute(self):
        src = ("@[simp] theorem keep : True := trivial\n"
               "theorem helper : True := trivial\n"
               "theorem root : True := keep\n")
        before = [row("keep", 1, 1), row("helper", 2, 2), row("root", 3, 3, ["keep", "helper"])]
        after = [row("keep", 1, 1), row("helper", 2, 2), row("root", 3, 3, ["keep"])]
        out = self.run_prune(src, before, after, ["root"])
        self.assertIn("@[simp] theorem keep", out)
        self.assertNotIn("helper", out)

    def test_attribute_and_doc_lines_go_with_their_declaration(self):
        src = ("theorem root : True := trivial\n"
               "\n"
               "/-- a helper -/\n"
               "@[simp]\n"
               "theorem helper : True := trivial\n")
        before = [row("root", 1, 1, ["helper"]), row("helper", 5, 5)]
        after = [row("root", 1, 1), row("helper", 5, 5)]
        out = self.run_prune(src, before, after, ["root"])
        self.assertEqual(out.strip(), "theorem root : True := trivial")


if __name__ == "__main__":
    unittest.main()
