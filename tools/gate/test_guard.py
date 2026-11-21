#!/usr/bin/env python3
"""Tests for tools/gate/guard.py.

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
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from guard import GuardSetupError, check_file, check_tree  # noqa: E402

PATH = "CFSG/FeitThompson/Local/Example.lean"
HEADER_OPTIONS = {"autoImplicit true", "maxSynthPendingDepth 3"}

BASE = """module

public import Mathlib.GroupTheory.Sylow
import CFSG.FeitThompson.Local.Basic

public section

set_option autoImplicit true
set_option maxSynthPendingDepth 3

namespace CFSG.FeitThompson

open Subgroup Pointwise

variable {G : Type*} [Group G]

/-- Every subgroup is below itself. -/
@[simp]
theorem le_self' (H : Subgroup G) : H ≤ H := by
  intro x hx
  exact hx

theorem le_of_le (H K : Subgroup G) (h : H ≤ K) : H ≤ K := by
  have h' := h
  exact h'

theorem card_le (s t : Finset G) (h : s ⊆ t) : #s ≤ #t := Finset.card_le_card h

set_option maxHeartbeats 400000 in
theorem slow (p : Prop × Prop) (h : p.1 ∧ p.2) : p.2 := h.2

end CFSG.FeitThompson
"""


# a new file: the project header, no resource options
NEW_FILE = BASE.replace("set_option maxHeartbeats 400000 in\n", "")


def head_with(extra: str, base: str = BASE) -> str:
    """BASE with `extra` inserted just before the final `end`."""
    return base.replace("end CFSG.FeitThompson", extra + "\nend CFSG.FeitThompson")


def problems(head: str, base: str = BASE, allowed=HEADER_OPTIONS) -> list[str]:
    return check_file(base, head, PATH, "FeitThompson", set(allowed))


class Accepts(unittest.TestCase):
    def assertClean(self, head, base=BASE):
        self.assertEqual(problems(head, base), [])

    def test_unchanged(self):
        self.assertClean(BASE)

    def test_shorter_proofs(self):
        head = BASE.replace("by\n  intro x hx\n  exact hx", "le_rfl")
        head = head.replace("by\n  have h' := h\n  exact h'", "h")
        self.assertClean(head)

    def test_deleted_declaration(self):
        start = BASE.index("theorem le_of_le")
        end = BASE.index("theorem card_le")
        self.assertClean(BASE[:start] + BASE[end:])

    def test_new_lemmas_with_plain_attributes(self):
        self.assertClean(head_with("""
@[simp, norm_cast] theorem a1 (H : Subgroup G) : H ≤ H := le_rfl
@[to_additive (attr := simp)] theorem a2 (x : G) : x * 1 = x := mul_one x
@[local simp] theorem a3 : True := trivial
attribute [local simp] le_self'
attribute [-simp] le_self'
attribute [local instance 100] Classical.propDecidable
@[ext, aesop safe apply, gcongr, instance_reducible, expose] theorem a4 : True := trivial
@[deprecated le_self' (since := "2026-01-01")] theorem a5 : True := trivial
"""))

    def test_ordinary_notation(self):
        self.assertClean(head_with("""
theorem n1 (f : G →* G) (s : Set G) (h : ∀ x ∈ f ⁻¹' s, x = 1) (p : (Prop ∧ Prop) ∧ Prop)
    (hp : p.1.2) : p.1.2 := hp
theorem n2 (s : Finset G) : #s = #s := rfl
theorem n3 (xs : List ℕ) (i : ℕ) (h : i < xs.length) : xs[i]'h = xs[i]'h := rfl
theorem n4 (f : G → G) (s : Set G) : f '' s = f '' s := rfl
"""))

    def test_new_imports_inside_mathlib_and_cfsg(self):
        head = BASE.replace("import CFSG.FeitThompson.Local.Basic",
                            "import CFSG.FeitThompson.Local.Basic\nimport Mathlib.Data.Set.Basic\n"
                            "public import CFSG.Foundations.Basic\nimport Batteries.Data.List.Basic")
        self.assertClean(head)

    def test_new_file_with_project_header(self):
        self.assertClean(NEW_FILE, base="")

    def test_existing_upstream_uses_are_tolerated(self):
        base = head_with("theorem todo : False := sorry\nopen Lean in\ntheorem t2 : True := trivial")
        moved = base.replace("theorem todo : False := sorry\n", "").replace(
            "namespace CFSG.FeitThompson", "namespace CFSG.FeitThompson\ntheorem todo : False := sorry")
        self.assertClean(moved, base=base)
        self.assertTrue(problems(head_with("theorem todo2 : False := sorry", base=base), base=base))

    def test_same_set_option_kept(self):
        head = BASE.replace("theorem slow (p", "theorem slow' (p")
        self.assertClean(head)


class Refuses(unittest.TestCase):
    def assertRefused(self, extra, check="no_metaprogramming", base=BASE, head=None):
        found = problems(head if head is not None else head_with(extra, base), base)
        self.assertTrue(found, f"accepted: {extra!r}")
        self.assertTrue(any(p.startswith(check + ": " + PATH + ":") for p in found), found)
        return found

    # red-team payloads -----------------------------------------------------------
    def test_comment_tricks(self):
        self.assertRefused("/- -- -/ run_elab do pure ()")
        self.assertRefused("/- -/ axiom cheat : False", check="no_shortcuts")
        self.assertRefused('/-- d -/ elab "foo" : term => pure default')
        self.assertRefused('/-- d -/ macro "foo" : term => `(1)')

    def test_sorry_ax(self):
        self.assertRefused("theorem t : False := by exact sorryAx _ false", check="no_shortcuts")
        self.assertRefused("theorem t : False := by exact @«sorryAx» _ false", check="no_shortcuts")

    def test_set_option_in_guillemets(self):
        found = self.assertRefused("set_option «maxHeartbeats» 0 in\ntheorem t : True := trivial",
                                   check="no_shortcuts")
        self.assertIn("maxHeartbeats 0", found[0])
        self.assertRefused("set_option maxHeartbeats 400000 in\ntheorem t : True := trivial",
                           check="no_shortcuts")
        self.assertRefused("set_option debug.skipKernelTC true in\ntheorem t : True := trivial",
                           check="no_shortcuts")
        self.assertRefused("set_option pp.all true", check="no_shortcuts")

    def test_printing_attributes(self):
        self.assertRefused("@[app_unexpander Subgroup] def u : Nat := 1")
        self.assertRefused("@[delab app.Subgroup] def d : Nat := 1")
        self.assertRefused("attribute [command_elab Foo] le_self'")
        self.assertRefused("@[inline, command_elab Foo] def g : Nat := 1")
        self.assertRefused("@[simp, pp_nodot] def g : Nat := 1")
        self.assertRefused("@[coe] def g (x : G) : G := x")

    def test_code_attributes(self):
        for attr in ["implemented_by g", 'extern "c_fun"', "csimp", "norm_num Nat.succ _", "positivity _",
                     "init", "export foo", "macro_inline", "simproc", "term_elab foo"]:
            self.assertRefused(f"@[{attr}] def g : Nat := 1")
        self.assertRefused("@[aesop safe tactic] def g : Nat := 1")
        self.assertRefused("@[to_additive (attr := command_elab foo)] theorem g : True := trivial")
        self.assertRefused("@[local simp, scoped delab foo] def g : Nat := 1")
        self.assertRefused("attribute [local instance, -app_unexpander] le_self'")

    def test_hash_commands(self):
        self.assertRefused("theorem x : True := trivial #eval IO.println 1")
        self.assertRefused("#exit")
        self.assertRefused("#evalx 1")
        self.assertRefused("#print axioms le_self'")
        self.assertRefused("#check le_self'")
        self.assertRefused("#guard_msgs in #check 1")
        self.assertRefused("#kc_items foo include_bytes \"f\" 1 2")

    def test_code_running_keywords(self):
        for src in ["run_cmd pure ()", "run_meta pure ()", "initialize pure ()", "builtin_initialize pure ()",
                    "theorem t : True := by run_tac pure ()", "def x : Nat := by_elab pure default",
                    "def x : Nat := eval% 1", 'def x : String := include_str "secret"',
                    'def x := include_hex_bytes% "secret"', "def x := some_new_loader% 1",
                    "def x : Nat := by_elabq pure q(1)", "local notation \"𝔵\" => 1",
                    "scoped[Foo] infix:50 \" ~~ \" => HAdd.hAdd", "macro_rules | `(tactic| trivial) => `(tactic| rfl)",
                    "syntax \"foo\" : term", "declare_syntax_cat foo", "notation3 \"y\" => 1",
                    "unsafe def u : Nat := 1", "partial def p : Nat → Nat := p", "opaque o : Nat",
                    "export Nat (succ)", "meta def m : Nat := 1", "simproc foo (_) := fun _ => pure .continue"]:
            self.assertRefused(src)

    def test_shortcuts(self):
        for src in ["theorem t : 2 + 2 = 4 := by native_decide", "theorem t : 2 + 2 = 4 := by decide +native",
                    "theorem t : False := by admit", "theorem t : False := by stop\n  trivial",
                    "theorem t : False := sorry", "theorem t : True := Lean.ofReduceBool _ _ rfl ▸ trivial",
                    "theorem t (b : BitVec 8) : b = b := by bv_decide", "axiom cheat : False"]:
            self.assertRefused(src, check="no_shortcuts")

    def test_lean_and_os_internals(self):
        for src in ["def x := IO.println 1", "def x := _root_.IO.FS.readFile \"f\"", "def x := «IO».println 1",
                    "def x := System.FilePath.mk \"f\"", "def x := unsafeBaseIO (pure 1)",
                    "def x := Lean.Elab.Command.liftTermElabM", "def x := ST.Ref.get"]:
            self.assertRefused(src)

    def test_namespaces(self):
        for src in ["open Lean in\ntheorem t : True := trivial", "open Lean.Elab Command",
                    "open Classical Lean", "namespace Lean\nend Lean", "open scoped ProofWidgets.Jsx",
                    "open Qq in\ntheorem t : True := trivial", "export Lean (Name)"]:
            self.assertRefused(src)

    def test_quotations(self):
        self.assertRefused("def x := `(term| 1)")
        self.assertRefused("def x := `foo")
        self.assertRefused("def x := ``Nat.succ")

    def test_imports(self):
        for imp in ["import Lean.Elab.Command", "meta import Mathlib.Tactic.Ring", "import all Mathlib.Logic.Basic",
                    "public meta import CFSG.Foundations.Basic", "import ProofWidgets.Component.HtmlDisplay",
                    "import Lake", "import Plausible"]:
            head = BASE.replace("import CFSG.FeitThompson.Local.Basic", "import CFSG.FeitThompson.Local.Basic\n" + imp)
            self.assertRefused(None, head=head)

    def test_parser_recovery_tricks(self):
        # Lean skips raw characters after a bad declaration name and resumes there
        self.assertRefused('theorem "a #eval IO.println 1 -- " : True := trivial')
        self.assertRefused("theorem 1--a #eval IO.println 1")
        self.assertRefused("theorem fun--a #eval IO.println 1")
        self.assertRefused("def x.{u, 1--a #eval IO.println 1\n}")
        # a parse error inside {…} resumes inside the string
        self.assertRefused('def y := s!"{ ) } #eval IO.println 8 "')
        self.assertRefused('def y : String := "{ ) } #eval IO.println 8 "')

    def test_lexical_errors_are_refused(self):
        found = self.assertRefused(None, head=head_with("/- unterminated"))
        self.assertIn("could not be read as Lean source", found[0])
        self.assertRefused(None, head=head_with('def s := "\\q #eval x"'))
        self.assertRefused(None, head=head_with("theorem t (s : Set G) (f : G → G) : f ⁻¹'-- #eval x\n s = s := rfl"))

    def test_interpolated_code_is_scanned(self):
        self.assertRefused('def s := s!"{IO.println 1}"')

    def test_count_increase(self):
        base = head_with("theorem old : False := sorry")
        self.assertRefused("theorem new : False := sorry", check="no_shortcuts", base=base)

    def test_messages_point_at_the_new_line(self):
        head = head_with("theorem t : True := by\n  exact (sorry : True)")
        found = problems(head)
        line = head.splitlines().index("  exact (sorry : True)") + 1
        self.assertEqual(found, [f"no_shortcuts: {PATH}:{line}: adds `sorry`, which skips a proof or trusts "
                                 "the compiler instead of the kernel; give a real proof"])


class Trees(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = os.path.join(self.tmp.name, "base")
        self.head = os.path.join(self.tmp.name, "head")
        for root in (self.base, self.head):
            os.makedirs(os.path.join(root, "CFSG/FeitThompson/Local"))
            os.makedirs(os.path.join(root, "CFSG/Other"))
        self.write(self.base, "Local/Example.lean", BASE)
        self.write(self.base, "Local/Gone.lean", BASE)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, root, rel, text, mode="w"):
        path = os.path.join(root, "CFSG/FeitThompson", rel)
        with open(path, mode) as fh:
            fh.write(text)
        return path

    def run_cli(self, *extra):
        out = os.path.join(self.tmp.name, "out.json")
        opts = os.path.join(self.tmp.name, "opts.txt")
        with open(opts, "w") as fh:
            fh.write("set_option autoImplicit true\nmaxSynthPendingDepth 3\n")
        r = subprocess.run([sys.executable, os.path.join(HERE, "guard.py"), "--base-dir", self.base,
                            "--head-dir", self.head, "--target", "FeitThompson",
                            "--allowed-set-options", opts, "--json", out, *extra], capture_output=True, text=True)
        data = None
        if os.path.exists(out):
            with open(out, encoding="utf-8") as fh:
                data = json.load(fh)
        return r.returncode, data

    def test_added_removed_and_changed_files(self):
        self.write(self.head, "Local/Example.lean", BASE.replace("by\n  intro x hx\n  exact hx", "le_rfl"))
        self.write(self.head, "Local/New.lean", NEW_FILE)
        self.assertEqual(check_tree(self.base, self.head, "FeitThompson", HEADER_OPTIONS), [])
        code, data = self.run_cli()
        self.assertEqual((code, data["ok"]), (0, True))

    def test_problems_exit_2(self):
        self.write(self.head, "Local/New.lean", head_with("#eval 1", NEW_FILE))
        code, data = self.run_cli()
        self.assertEqual(code, 2)
        self.assertTrue(data["reasons"][0].startswith("no_metaprogramming: CFSG/FeitThompson/Local/New.lean:"))

    def test_other_targets_are_ignored(self):
        with open(os.path.join(self.head, "CFSG/Other/X.lean"), "w") as fh:
            fh.write("#eval 1")
        self.assertEqual(check_tree(self.base, self.head, "FeitThompson", HEADER_OPTIONS), [])

    def test_symlinks_and_bad_encoding(self):
        os.symlink("/etc/hosts", os.path.join(self.head, "CFSG/FeitThompson/Local/Link.lean"))
        self.write(self.head, "Local/Latin1.lean", "theorem caf\xe9 : True := trivial".encode("latin-1"), mode="wb")
        found = check_tree(self.base, self.head, "FeitThompson", HEADER_OPTIONS)
        self.assertTrue(any("symbolic link" in p for p in found), found)
        self.assertTrue(any("not valid UTF-8" in p for p in found), found)

    def test_base_lexer_error_is_a_setup_error(self):
        self.write(self.base, "Local/Example.lean", "/- broken")
        self.write(self.head, "Local/Example.lean", BASE)
        with self.assertRaises(GuardSetupError):
            check_tree(self.base, self.head, "FeitThompson", HEADER_OPTIONS)
        code, data = self.run_cli()
        self.assertEqual((code, data["ok"]), (75, False))


if __name__ == "__main__":
    unittest.main()
