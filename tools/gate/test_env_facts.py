"""Tests of tools/gate/env_facts.py and tools/gate/CheckEnv.lean.

    python3 -m unittest discover -s tools/gate -p 'test_env_facts.py'

The unit tests need nothing. The Lean tests need a built AxiomMath/CFSG
checkout in $CFSG_ROOT (with .lake/build oleans of CFSG.FeitThompson) and
are skipped otherwise. They never write inside it: the adversarial modules
are compiled to .olean files in a temporary directory that is put in front
of LEAN_PATH for the checker run only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import env_facts as ef  # noqa: E402

PROT = "CFSG.FeitThompson.isSolvable_of_odd_natCard"
CLOSURE = "closure-v1\ntheorem " + PROT + " u1 : (pi d (sort (s u0)) (sort 0))\n"


def const(**kw):
    c = {"k": "def", "m": "CFSG.T.A", "unsafe": False, "partial": False, "impl": None, "extern": False,
         "meta": False, "forbidden": [], "range": None, "uses": 0, "autoparam": False, "wf_rec": False}
    c.update(kw)
    return c


def raw(constants=None, closure=CLOSURE, axioms=("propext",), replay=None):
    return {
        "lean_version": "4.35.0", "target_prefix": "CFSG.T",
        "protected": {PROT: {"exists": True, "kind": "theorem", "module": "CFSG.T.A", "level_params": ["u_1"],
                             "closure": {"dump": closure, "members": [PROT], "missing": [], "error": None},
                             "axioms": list(axioms), "axioms_missing": []}},
        "constants": constants or {"CFSG.T.foo": const(range=[3, 5], uses=2)},
        "roots": [PROT], "reachable": [PROT],
        "replay": replay or {"ran": False, "ok": None, "ms": None},
        "ms": {"load": 1000, "protected": 10, "scan": 20},
    }


def baseline(closure=CLOSURE, axioms=("propext",), allowed=()):
    return {"protected": {PROT: {"closure_sha256": ef.sha256(closure), "axioms": list(axioms), "closure": closure}},
            "allowed_meta": list(allowed)}


class Locate(unittest.TestCase):
    def test_lean_path_and_command_without_lake(self):
        with tempfile.TemporaryDirectory() as d:
            root, elan = os.path.join(d, "up"), os.path.join(d, "elan")
            tc = os.path.join(elan, "toolchains", "leanprover--lean4---v4.35.0")
            for p in (os.path.join(root, ".lake", "packages", "mathlib", ".lake", "build", "lib", "lean"),
                      os.path.join(root, ".lake", "build", "lib", "lean"), os.path.join(tc, "bin"),
                      os.path.join(tc, "lib", "lean")):
                os.makedirs(p)
            ef.write_json(os.path.join(tc, "bin", "lean"), None)
            with open(os.path.join(root, "lean-toolchain"), "w") as fh:
                fh.write("leanprover/lean4:v4.35.0\n")
            old = os.environ.get("ELAN_HOME")
            os.environ["ELAN_HOME"] = elan
            try:
                lp = ef.lean_path(root).split(os.pathsep)
                cmd = ef.command(root, "req.json", "out.json")
            finally:
                if old is None:
                    del os.environ["ELAN_HOME"]
                else:
                    os.environ["ELAN_HOME"] = old
            self.assertEqual(lp, [os.path.join(root, ".lake", "packages", "mathlib", ".lake", "build", "lib", "lean"),
                                  os.path.join(root, ".lake", "build", "lib", "lean"), os.path.join(tc, "lib", "lean")])
            self.assertEqual(cmd[:3], [os.path.join(tc, "bin", "lean"), "--run", ef.CHECKER])
            self.assertTrue(os.path.isabs(cmd[3]) and os.path.isabs(cmd[4]))

    def test_request(self):
        r = ef.request("/nowhere", "FeitThompson", modules=["CFSG.FeitThompson.B", "CFSG.FeitThompson.A"],
                       roots=["CFSG.FeitThompson.x"])
        self.assertEqual(r["modules"], ["CFSG.FeitThompson.A", "CFSG.FeitThompson.B"])
        self.assertEqual(r["target_prefix"], "CFSG.FeitThompson")
        self.assertIn(PROT, r["protected"])
        self.assertEqual(r["roots"], ["CFSG.FeitThompson.x"])
        self.assertIn("Lean.Elab", r["forbidden_prefixes"])
        self.assertNotIn("Lean.Omega", r["forbidden_prefixes"])


class Compact(unittest.TestCase):
    def test_fields(self):
        f = ef.compact(raw())
        p = f["protected"][PROT]
        self.assertEqual(p["closure_sha256"], ef.sha256(CLOSURE))
        self.assertEqual(f["kinds"], {"CFSG.T.foo": "def"})
        self.assertEqual(f["uses"], {"CFSG.T.foo": 2})
        self.assertEqual(f["ranges"], {"CFSG.T.foo": ["CFSG.T.A", 3, 5]})
        self.assertEqual(f["meta_constants"], [])
        self.assertEqual(f["reachable"], [PROT])

    def test_meta_reasons(self):
        cs = {
            "a": const(unsafe=True), "b": const(partial=True), "c": const(impl="x"), "d": const(extern=True),
            "e": const(meta=True), "f": const(forbidden=["Lean.Elab.Term.TermElab"]),
            # Lean's own auxiliaries are not meta
            "g._auto_1": const(meta=True, forbidden=["Lean.Syntax"], autoparam=True),
            "h._unsafe_rec": const(partial=True, wf_rec=True),
        }
        m = {x["name"]: x["reasons"] for x in ef.compact(raw(cs))["meta_constants"]}
        self.assertEqual(sorted(m), ["a", "b", "c", "d", "e", "f"])
        self.assertEqual(m["c"], ["implemented_by x"])
        self.assertEqual(m["f"], ["refers to Lean.Elab.Term.TermElab"])


class Compare(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(ef.compare(ef.compact(raw()), baseline()), [])

    def test_statement_changed(self):
        changed = CLOSURE.replace("(sort 0)", "(sort (s 0))")
        p = ef.compare(ef.compact(raw(closure=changed)), baseline())
        self.assertEqual(len(p), 1)
        self.assertTrue(p[0].startswith("protected_unchanged: "), p)
        self.assertIn("differs at character", p[0])

    def test_new_constant_in_statement(self):
        fake = CLOSURE + "def CFSG.Fake u1 safe : (sort 0) := (const True [])\n"
        p = ef.compare(ef.compact(raw(closure=fake)), baseline())
        self.assertIn("now mentions CFSG.Fake", p[0])

    def test_missing(self):
        r = raw()
        r["protected"][PROT] = {"exists": False}
        self.assertEqual(ef.compare(ef.compact(r), baseline()), [f"protected_unchanged: {PROT} no longer exists"])

    def test_axioms(self):
        p = ef.compare(ef.compact(raw(axioms=["propext", "sorryAx"])), baseline())
        self.assertEqual([x.split(":")[0] for x in p], ["axioms_unchanged"])
        self.assertIn("sorryAx", p[0])
        p = ef.compare(ef.compact(raw(axioms=["propext", "Quot.sound"])), baseline())
        self.assertEqual([x.split(":")[0] for x in p], ["axioms_unchanged"])

    def test_meta_against_allowlist(self):
        r = raw({"CFSG.T.old": const(meta=True), "CFSG.T.new": const(impl="y")})
        p = ef.compare(ef.compact(r), baseline(allowed=["CFSG.T.old"]))
        self.assertEqual(p, ["no_metaprogramming: CFSG.T.new (implemented_by y)"])

    def test_replay_failure(self):
        r = raw(replay={"ran": True, "ok": False, "ms": 5, "error": "(kernel) declaration type mismatch"})
        p = ef.compare(ef.compact(r), baseline())
        self.assertEqual(len(p), 1)
        self.assertTrue(p[0].startswith("protected_unchanged: the kernel rejected"))

    def test_committed_baseline_shape(self):
        b = ef.read_json(os.path.join(REPO, "data", "protected", "FeitThompson.json"))
        self.assertIn(PROT, b["protected"])
        e = b["protected"][PROT]
        self.assertEqual(ef.sha256(e["closure"]), e["closure_sha256"])
        self.assertTrue(set(e["axioms"]) <= set(ef.PERMITTED_AXIOMS))


# ------------------------------------------------------------------ Lean tests

ROOT = os.environ.get("CFSG_ROOT", "")
BUILT = bool(ROOT) and os.path.isdir(os.path.join(ROOT, ".lake", "build", "lib", "lean", "CFSG", "FeitThompson"))

FAKE = textwrap.dedent("""\
    import CFSG.FeitThompson.Definitions.AlphaPrimesOfAFiniteGroup
    import Mathlib.GroupTheory.Solvable
    import Mathlib.SetTheory.Cardinal.Finite

    namespace CFSG.FeitThompson

    -- (a) a fake statement that prints exactly like the protected one
    def FakeSolvable (G : Type*) [Group G] : Prop := True

    @[app_unexpander FakeSolvable] def unexpandFakeSolvable : Lean.PrettyPrinter.Unexpander
      | `($_ $g) => `($(Lean.mkIdent `Group.IsSolvable) $g)
      | _ => throw ()

    theorem isSolvable_of_odd_natCard (G : Type*) [Group G] [Finite G] (_hG : Odd (Nat.card G)) :
        FakeSolvable G :=
      (Classical.em True).elim (fun h => h) (fun _ => trivial)

    -- (b) a definition whose type is an elaborator
    def fakeElab : Lean.Elab.Term.TermElab := fun _ _ => pure (Lean.mkConst ``Nat)

    -- (c) implemented_by
    def fastId (n : Nat) : Nat := n

    @[implemented_by fastId] def slowId (n : Nat) : Nat := n + 0

    -- (d) partial
    partial def spin (n : Nat) : Nat := spin (n + 1)

    -- controls that must not be flagged: well-founded recursion, an auto-parameter
    def wfSum (n : Nat) : Nat := if _h : n = 0 then 0 else n + wfSum (n - 1)
    termination_by n
    decreasing_by omega

    theorem autoParamUse (n : Nat) (_h : n = n := by rfl) : True := trivial

    end CFSG.FeitThompson

    #check @CFSG.FeitThompson.isSolvable_of_odd_natCard
    #print axioms CFSG.FeitThompson.isSolvable_of_odd_natCard
    """)

# a theorem the kernel never accepted, as a forged .olean would contain
FORGED = textwrap.dedent("""\
    import Lean

    open Lean Elab Command in
    set_option debug.skipKernelTC true in
    run_cmd liftCoreM do
      addDecl (.thmDecl { name := `GateAdv.forged, levelParams := [], type := mkConst ``False,
                          value := mkConst ``True.intro })
    """)


@unittest.skipUnless(BUILT, "set CFSG_ROOT to a built AxiomMath/CFSG checkout")
class Lean(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = os.path.abspath(ROOT)
        cls.tmp = tempfile.TemporaryDirectory(prefix="gate-adv-")
        cls.dir = cls.tmp.name
        os.makedirs(os.path.join(cls.dir, "GateAdv"))
        cls.printed = {}
        for name, src in (("Fake", FAKE), ("Forged", FORGED)):
            path = os.path.join(cls.dir, "GateAdv", name + ".lean")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(src)
            r = subprocess.run([ef.command(cls.root, "x", "y")[0], "-R", cls.dir, "-o", path[:-5] + ".olean", path],
                               cwd=cls.dir, env={"LEAN_PATH": ef.lean_path(cls.root), "HOME": cls.dir},
                               capture_output=True, text=True, timeout=1800)
            if r.returncode:
                raise RuntimeError(f"cannot compile {name}: {r.stdout[-2000:]}{r.stderr[-2000:]}")
            cls.printed[name] = r.stdout

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def check(self, module, protected, replay=False):
        req = ef.request(self.root, "FeitThompson", modules=[module], protected=protected, replay=replay)
        req["target_prefix"] = "GateAdv"
        return ef.compact(ef.run(self.root, req, extra_path=[self.dir], timeout=1800))

    def test_fake_statement_and_meta(self):
        # the text the old probe compared is identical ...
        old = os.path.join(REPO, "data", "pilot", "FeitThompson", "protected_baseline.txt")
        if os.path.exists(old):
            self.assertEqual(self.printed["Fake"], ef.read_text(old))
        # ... but the structural digest is not
        facts = self.check("GateAdv.Fake", [PROT])
        base = ef.read_json(os.path.join(REPO, "data", "protected", "FeitThompson.json"))
        p = facts["protected"][PROT]
        self.assertNotEqual(p["closure_sha256"], base["protected"][PROT]["closure_sha256"])
        self.assertIn("CFSG.FeitThompson.FakeSolvable", p["closure_members"])
        self.assertEqual(p["axioms"], base["protected"][PROT]["axioms"])
        meta = {m["name"]: m["reasons"] for m in facts["meta_constants"]}
        for n in ("unexpandFakeSolvable", "fakeElab", "slowId", "spin._unsafe_rec"):
            self.assertIn("CFSG.FeitThompson." + n, meta)
        self.assertTrue(meta["CFSG.FeitThompson.fakeElab"][0].startswith("refers to Lean.Elab.Term.TermElab"))
        self.assertEqual(meta["CFSG.FeitThompson.slowId"], ["implemented_by CFSG.FeitThompson.fastId"])
        for n in ("wfSum", "wfSum._unsafe_rec", "autoParamUse", "autoParamUse._auto_1", "FakeSolvable"):
            self.assertNotIn("CFSG.FeitThompson." + n, meta)
        problems = ef.compare(facts, base)
        self.assertTrue(any(x.startswith("protected_unchanged: ") for x in problems))
        self.assertEqual(sum(x.startswith("no_metaprogramming: ") for x in problems), 4)

    def test_replay_rejects_forged_constant(self):
        facts = self.check("GateAdv.Forged", ["GateAdv.forged"], replay=True)
        self.assertEqual(facts["protected"]["GateAdv.forged"]["axioms"], [])
        self.assertTrue(facts["replay"]["ran"])
        self.assertFalse(facts["replay"]["ok"])
        self.assertIn("type mismatch", facts["replay"]["error"])

    @unittest.skipUnless(os.environ.get("CFSG_FULL"), "set CFSG_FULL=1 to inspect the whole target (~30 s)")
    def test_build_matches_baseline(self):
        req = ef.request(self.root, "FeitThompson")
        facts = ef.compact(ef.run(self.root, req, timeout=3600))
        self.assertEqual(ef.compare(facts, ef.read_json(os.path.join(REPO, "data", "protected", "FeitThompson.json"))),
                         [])


if __name__ == "__main__":
    unittest.main()
