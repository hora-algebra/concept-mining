"""Tests of the public-face check (tools/gate/interface.py).

    python3 -m unittest discover -s tools/gate -p 'test_interface.py'

The Lean cases build a small module-system project with the toolchain of
lean/UPSTREAM's checkout (skipped when that toolchain is not installed).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import interface  # noqa: E402

TOOLCHAIN = "leanprover/lean4:v4.35.0"
ELAN = os.environ.get("ELAN_HOME") or os.path.expanduser("~/.elan")
TC = os.path.join(ELAN, "toolchains", TOOLCHAIN.replace("/", "--").replace(":", "---"))
CHECKER = os.path.join(HERE, "CheckEnv.lean")


class Headers(unittest.TestCase):
    def test_header_imports(self):
        t = ("module\n\n/- doc\n -/\n-- c\npublic import Mathlib.A\nimport all CFSG.T.B\n"
             "public meta import CFSG.T.C CFSG.T.D\nimport CFSG.T.E -- note\n\npublic section\nimport CFSG.X\n")
        self.assertEqual(interface.header_imports(t), [
            ("Mathlib.A", True, False, False), ("CFSG.T.B", False, False, True), ("CFSG.T.C", True, True, False),
            ("CFSG.T.D", True, True, False), ("CFSG.T.E", False, False, False)])

    def test_interface_closure(self):
        headers = {
            "CFSG.T.A": [("CFSG.T.B", True, False, False), ("CFSG.T.C", False, False, False)],
            "CFSG.T.B": [("CFSG.T.D", True, False, False), ("Mathlib.X", True, False, False)],
            "CFSG.T.C": [("CFSG.T.E", True, False, False)],
            "CFSG.T.F": [("CFSG.T.G", False, False, False)],
            "CFSG.T.G": [("CFSG.T.H", False, True, False)],
        }
        got = interface.interface(headers, {"CFSG.T.A": False, "CFSG.T.F": True}, "CFSG.T")
        self.assertEqual(got, {"CFSG.T.A": False, "CFSG.T.B": False, "CFSG.T.D": False,
                               "CFSG.T.F": True, "CFSG.T.G": True, "CFSG.T.H": True})

    def test_entries_scan_whole_tree(self):
        with tempfile.TemporaryDirectory() as d:
            def w(rel, text):
                p = os.path.join(d, rel)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                open(p, "w").write(text)
            w("CFSG/T/A.lean", "module\nimport CFSG.T.B\n")
            w("CFSG/T.lean", "module\npublic import CFSG.T.A\n")
            w("CFSG/U/X.lean", "module\npublic import CFSG.T.A\nimport all CFSG.T.B\n")
            w("Certificates/K.lean", "meta import CFSG.T.C\n")
            w("CFSG/TT/Y.lean", "import CFSG.TT.Z\n")
            self.assertEqual(interface.entries(d, "T"), {"CFSG.T.A": False, "CFSG.T.B": True, "CFSG.T.C": True})


def face(consts, attrs=(), exts=None, imports=(), full=False):
    return {"constants": dict(consts), "attrs": list(attrs), "ext_counts": exts or {}, "full": full,
            "imports": [{"module": m, "exported": e, "all": False, "meta": False} for m, e in imports]}


class Compare(unittest.TestCase):
    def test_unchanged_and_ignored(self):
        b = {"modules": {"M": face({"c": "theorem c : P"}, exts={"Lean.IR.declMapExt": 1})}}
        h = {"modules": {"M": face({"c": "theorem c : P"}, exts={"Lean.IR.declMapExt": 3},
                                   imports=[("Private.Dep", False)])}}
        self.assertEqual(interface.compare(b, h), [])

    def test_changes_are_found(self):
        b = {"modules": {"M": face({"c": "theorem c : P", "d": "def d := 1"}, attrs=["simp c"],
                                   exts={"Lean.Meta.simpExtension": 1}, imports=[("X", True)]),
                         "N": face({})}}
        h = {"modules": {"M": face({"c": "theorem c : Q", "e": "theorem e : R"},
                                   imports=[("X", True), ("Y", True)])}}
        p = interface.compare(b, h)
        text = "\n".join(p)
        for needle in ("module N", "public imports changed", "c (M)", "d (M)", "e (M) would become visible",
                       "attributes", "entries"):
            self.assertIn(needle, text)
        self.assertTrue(all(x.startswith("protected_unchanged") for x in p))

    def test_full_module_may_gain_private_helpers(self):
        b = {"modules": {"M": face({"c": "theorem c : P"}, full=True)}}
        h = {"modules": {"M": face({"c": "theorem c : P", "_private.M.0.h": "theorem h : P"}, full=True)}}
        self.assertEqual(interface.compare(b, h), [])

    def test_new_public_module(self):
        b = {"modules": {}}
        h = {"modules": {"M": face({"x": "theorem x : P"})}}
        self.assertTrue(interface.compare(b, h))
        self.assertEqual(interface.compare(b, {"modules": {"M": face({})}}), [])

    def test_union(self):
        b = {"closure": {"dumps": {"a": "1", "b": "2"}, "error": None, "missing": []}, "axioms": ["propext"]}
        self.assertEqual(interface.compare_union(b, b), [])
        h = {"closure": {"dumps": {"a": "1", "b": "3", "c": "4"}, "error": None, "missing": []},
             "axioms": ["propext", "sorryAx"]}
        p = interface.compare_union(b, h)
        self.assertEqual(len(p), 3)
        self.assertTrue(p[-1].startswith("axioms_unchanged") and "sorryAx" in p[-1])


A = """module

public section

namespace T

theorem foo (n : Nat) : n + 0 = n := by simp

def hidden (n : Nat) : Nat := n + 2

theorem uses_hidden (n : Nat) : hidden n = hidden n := rfl

@[expose] def bar (n : Nat) : Nat := n + 1

@[simp] theorem bar_eq (n : Nat) : bar n = n + 1 := rfl

end T
"""

INTERNAL = """module

public section

theorem T.internal (n : Nat) : n = n := rfl
"""

OUTSIDE = """module

public import T.A
import T.Internal

public section

theorem O.uses (n : Nat) : T.bar n = n + 1 := by simp
"""


@unittest.skipUnless(os.path.isfile(os.path.join(TC, "bin", "lean")), f"{TOOLCHAIN} is not installed")
class Lean(unittest.TestCase):
    """The face and the statement closure computed by CheckEnv on real
    builds: a refactor of proofs passes, every visible change is caught."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="iface-test-")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def build(self, name, a=A, internal=INTERNAL):
        d = os.path.join(self.tmp, name)
        os.makedirs(os.path.join(d, "T"))
        open(os.path.join(d, "lean-toolchain"), "w").write(TOOLCHAIN + "\n")
        open(os.path.join(d, "lakefile.toml"), "w").write(
            'name = "t"\ndefaultTargets = ["T", "O"]\n[[lean_lib]]\nname = "T"\nglobs = ["T.+"]\n'
            '[[lean_lib]]\nname = "O"\n')
        open(os.path.join(d, "T", "A.lean"), "w").write(a)
        open(os.path.join(d, "T", "Internal.lean"), "w").write(internal)
        open(os.path.join(d, "O.lean"), "w").write(OUTSIDE)
        r = subprocess.run([os.path.join(ELAN, "bin", "lake"), "build", "T"], cwd=d, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return d

    def check(self, d, args, req):
        rq, out = os.path.join(d, "req.json"), os.path.join(d, "out.json")
        json.dump(req, open(rq, "w"))
        env = {"LEAN_PATH": os.pathsep.join([os.path.join(TC, "lib", "lean"),
                                             os.path.join(d, ".lake", "build", "lib", "lean")]),
               "HOME": os.environ.get("HOME", "/tmp")}
        r = subprocess.run([os.path.join(TC, "bin", "lean"), "--run", CHECKER, *args, rq, out], cwd=d, env=env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.load(open(out))

    def facts(self, d):
        # O imports T.A and T.Internal: both are entries (entries() reads
        # CFSG/<target>, so the test lists them directly)
        ent = {"T.A": False, "T.Internal": False}
        face_ = self.check(d, ["--interface"], interface.request(ent, set(ent)))
        u = self.check(d, [], {"modules": ["T.A", "T.Internal"], "target_prefix": "T", "protected": [],
                               "union_roots": interface.roots(face_), "closure_prefixes": ["T"]})
        return face_, u["union"]

    def problems(self, name, **kw):
        if not hasattr(Lean, "_base"):
            Lean._base = self.facts(self.build("base"))
        bf, bu = Lean._base
        hf, hu = self.facts(self.build(name, **kw))
        return interface.compare(bf, hf) + interface.compare_union(bu, hu)

    def test_proof_refactor_passes(self):
        a = A.replace("theorem foo (n : Nat) : n + 0 = n := by simp",
                      "private theorem helper (n : Nat) : n + 0 = n := Nat.add_zero n\n\n"
                      "theorem foo (n : Nat) : n + 0 = n := helper n")
        self.assertEqual(self.problems("refactor", a=a), [])

    def test_statement_change(self):
        a = A.replace("theorem foo (n : Nat) : n + 0 = n", "theorem foo (n : Nat) : 0 + n = n")
        self.assertTrue(any("T.foo" in p for p in self.problems("statement", a=a)))

    def test_meaning_of_hidden_definition(self):
        a = A.replace("def hidden (n : Nat) : Nat := n + 2", "def hidden (n : Nat) : Nat := n + 3")
        p = self.problems("meaning", a=a)
        self.assertTrue(any("T.hidden" in x and "mean" in x for x in p), p)

    def test_simp_attribute(self):
        a = A.replace("@[simp] theorem bar_eq", "theorem bar_eq")
        self.assertTrue(any("attributes" in p for p in self.problems("simp", a=a)))

    def test_new_public_declaration(self):
        a = A.replace("end T", "theorem extra : True := trivial\n\nend T")
        self.assertTrue(any("T.extra" in p and "visible" in p for p in self.problems("extra", a=a)))

    def test_every_module_imported_from_outside_is_the_face(self):
        internal = INTERNAL.replace("(n : Nat) : n = n := rfl", "(n : Nat) : n + 0 = n := rfl")
        self.assertTrue(any("T.internal" in p for p in self.problems("internal", internal=internal)))


if __name__ == "__main__":
    unittest.main()
