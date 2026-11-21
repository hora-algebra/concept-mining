#!/usr/bin/env python3
"""Tests for tools/lean_lex.py and the token counter in tools/size.py.

    python3 -m unittest discover -s tools -p 'test_*.py'
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lean_lex import LexError, code_tokens, tokenize, walk  # noqa: E402
from size import code_lines, strip_comments, tokens  # noqa: E402


def kinds(src):
    return [(t.kind, t.text) for t in tokenize(src)]


def code(src):
    return [t.text for t in code_tokens(src)]


class Comments(unittest.TestCase):
    def test_nested_block_comment(self):
        self.assertEqual(kinds("a /- x /- y -/ z -/ b"),
                         [("ident", "a"), ("block_comment", "/- x /- y -/ z -/"), ("ident", "b")])

    def test_doc_and_module_doc(self):
        self.assertEqual(kinds("/-- d -/ /-! m -/"), [("doc_comment", "/-- d -/"), ("mod_doc", "/-! m -/")])
        # `/--/` does not close itself; the doc comment runs to the next `-/`
        self.assertEqual(kinds("/--/ x -/ y"), [("doc_comment", "/--/ x -/"), ("ident", "y")])

    def test_line_comment_inside_block_is_ignored(self):
        self.assertEqual(code("/- -- -/ run_elab foo"), ["run_elab", "foo"])

    def test_quotes_do_not_matter_inside_comments(self):
        self.assertEqual(code('/- " -/ x "y"'), ["x", '"y"'])

    def test_character_after_open_is_skipped_like_lean(self):
        # Lean skips the character after `/-`, so `/-/-/` is a whole comment
        self.assertEqual(code("/-/-/ x -/"), ["x", "-", "/"])

    def test_line_comment(self):
        self.assertEqual(kinds("a -- b\nc"), [("ident", "a"), ("line_comment", "-- b"), ("ident", "c")])

    def test_unterminated_comment(self):
        with self.assertRaises(LexError):
            tokenize("a /- b /- c -/")
        with self.assertRaises(LexError):
            tokenize("a /-")


class Strings(unittest.TestCase):
    def test_comment_markers_inside_strings(self):
        self.assertEqual(code('def h₁ := "/-"\ntheorem t : 1 = 1 := rfl\ndef h₂ := "-/"'),
                         ["def", "h₁", ":=", '"/-"', "theorem", "t", ":", "1", "=", "1", ":=", "rfl",
                          "def", "h₂", ":=", '"-/"'])
        self.assertEqual(code('"--" x'), ['"--"', "x"])

    def test_escapes(self):
        for lit in [r'"a\"b"', r'"\\"', r'"\x41"', r'"α"', r'"\n\t\r\'"']:
            self.assertEqual(code(lit + " x"), [lit, "x"], lit)

    def test_string_gap(self):
        self.assertEqual(code('"a\\\n   b" x'), ['"a\\\n   b"', "x"])
        with self.assertRaises(LexError):
            tokenize('"a\\\n\n b"')

    def test_invalid_escapes_are_refused(self):
        # Lean v4.35 rejects these and would then read the rest of the string as code
        for lit in [r'"\q"', r'"\x4"', r'"\u12"', r'"\u{1F600}"', r'"\{"']:
            with self.assertRaises(LexError, msg=lit):
                tokenize(lit)

    def test_unterminated_string(self):
        with self.assertRaises(LexError):
            tokenize('def x := "abc')

    def test_interpolated_string_is_one_token_with_code(self):
        toks = code_tokens('s!"a {x + "}"} b" y')
        self.assertEqual([t.kind for t in toks], ["interp_string", "ident"])
        self.assertEqual([t.text for t in toks[0].code], ["x", "+", '"}"'])
        for p in ("m!", "f!"):
            self.assertEqual(code_tokens(p + '"{e}"')[0].kind, "interp_string")
        self.assertEqual([t.text for t in walk(tokenize('s!"{f "{g}"}"'))], ['s!"{f "{g}"}"', "f", '"{g}"', "g"])

    def test_interpolation_escape(self):
        self.assertEqual(code(r's!"\{x}" y'), [r's!"\{x}"', "y"])

    def test_ambiguous_string_is_refused(self):
        # read plainly it ends at the second quote; as an interpolated string
        # (after throwError, dbg_trace, ...) it ends at the last one
        with self.assertRaises(LexError):
            tokenize('throwError "{ \'"\' }" ; #eval danger "')
        # when both readings agree the braces' code is exposed
        toks = code_tokens('throwError "a {b} c"')
        self.assertEqual([t.text for t in toks[1].code], ["b"])

    def test_raw_strings(self):
        self.assertEqual(code('r"a\\b" x'), ['r"a\\b"', "x"])
        self.assertEqual(code('r#"a "quoted" b"# x'), ['r#"a "quoted" b"#', "x"])
        self.assertEqual(code('r##"a "# b"## x'), ['r##"a "# b"##', "x"])
        self.assertEqual(code('for"x"'), ["for", '"x"'])
        with self.assertRaises(LexError):
            tokenize('r#"abc"')


class Characters(unittest.TestCase):
    def test_char_literals(self):
        self.assertEqual(kinds("'a' '\\n' '\\'' '\"'"),
                         [("char", "'a'"), ("char", "'\\n'"), ("char", "'\\''"), ("char", "'\"'")])

    def test_primes_in_names(self):
        self.assertEqual(code("h' x'' f'.symm"), ["h'", "x''", "f'.symm"])

    def test_symbol_primes(self):
        self.assertEqual(code("f ⁻¹' s"), ["f", "⁻", "¹", "'", "s"])
        self.assertEqual(code("∑' i, f i"), ["∑", "'", "i", ",", "f", "i"])
        self.assertEqual(code("xs[i]'h"), ["xs", "[", "i", "]", "'", "h"])
        self.assertEqual(code("f '' s"), ["f", "'", "'", "s"])

    def test_symbol_prime_hazard(self):
        # without Mathlib's `⁻¹'` token Lean would read `'-` as a character
        # literal and resume inside what is a comment here
        for src in ["f ⁻¹'-- c", "f ⁻¹' -- c", "f ⁻¹'/- c -/", "f ⁻¹'a\"s\"", "f '' \"s\""]:
            with self.assertRaises(LexError, msg=src):
                tokenize(src)

    def test_bad_char_literal(self):
        with self.assertRaises(LexError):
            tokenize("('ab')")


class NamesAndNumbers(unittest.TestCase):
    def test_unicode_identifiers(self):
        self.assertEqual(code("α₁ hσ' 𝔽ₚ x.y.z ℕ Ω"), ["α₁", "hσ'", "𝔽ₚ", "x.y.z", "ℕ", "Ω"])
        # λ, Π, Σ are symbols, not letters; ˣ and ᶜ are postfix notation
        self.assertEqual(code("λx Σi Fˣ sᶜ"), ["λ", "x", "Σ", "i", "F", "ˣ", "s", "ᶜ"])

    def test_suffixes(self):
        self.assertEqual(code("exact? simp! h.1"), ["exact?", "simp!", "h", ".", "1"])

    def test_guillemets(self):
        toks = code_tokens("«a b».«c» x.«d»")
        self.assertEqual([t.text for t in toks], ["«a b».«c»", "x.«d»"])
        self.assertEqual([t.value for t in toks], ["a b.c", "x.d"])
        with self.assertRaises(LexError):
            tokenize("«abc")

    def test_name_literals_and_quotations(self):
        self.assertEqual(kinds("`foo ``Bar.baz `(x) `«a b»"),
                         [("name_lit", "`foo"), ("name_lit", "``Bar.baz"), ("syntax_quote", "`"),
                          ("symbol", "("), ("ident", "x"), ("symbol", ")"), ("name_lit", "`«a b»")])

    def test_numbers(self):
        self.assertEqual(kinds("0x1F 0b101 0o17 1_000 1.5e-3 2e10 3. 7"),
                         [("number", t) for t in ["0x1F", "0b101", "0o17", "1_000", "1.5e-3", "2e10", "3.", "7"]])
        self.assertEqual(code("[1..5]"), ["[", "1", "..", "5", "]"])
        for bad in ["0x", "1_", "2e", "2.foo"]:
            with self.assertRaises(LexError, msg=bad):
                tokenize(bad)

    def test_field_indices(self):
        self.assertEqual(kinds("h.2.1"), [("ident", "h"), ("symbol", "."), ("field_idx", "2"),
                                           ("symbol", "."), ("field_idx", "1")])
        self.assertEqual(code("(f x).2.1"), ["(", "f", "x", ")", ".", "2", ".", "1"])

    def test_symbol_grouping(self):
        self.assertEqual(code("a := b <;> c => d ← e ≤ f"), ["a", ":=", "b", "<;>", "c", "=>", "d", "←", "e",
                                                             "≤", "f"])

    def test_positions(self):
        toks = tokenize("a\n  bc -- x\n")
        self.assertEqual([(t.line, t.col) for t in toks], [(1, 1), (2, 3), (2, 6)])

    def test_whitespace_errors(self):
        with self.assertRaises(LexError):
            tokenize("a\tb")
        with self.assertRaises(LexError):
            tokenize("a\rb")
        self.assertEqual(code("a\r\nb"), ["a", "b"])


class Counter(unittest.TestCase):
    def test_string_trick_no_longer_hides_code(self):
        hidden = "theorem big : 1 + 1 = 2 := by\n  norm_num\n"
        src = f'def h₁ := "/-"\n{hidden}def h₂ := "-/"\n'
        self.assertEqual(tokens(src), 4 + tokens(hidden) + 4)

    def test_comments_and_layout_do_not_count(self):
        a = "theorem t : 1 = 1 := rfl"
        b = "/-- doc -/\ntheorem   t :\n  1 = 1 :=\n    rfl -- done\n"
        self.assertEqual(tokens(a), 8)
        self.assertEqual(tokens(a), tokens(b))

    def test_grouping_matches_old_counter(self):
        self.assertEqual(tokens("x ≠ y ∧ a ≤ b || c && d :: e .. f -> g <- h"), 19)
        # a projection chain is one token whether written with indices or names
        self.assertEqual(tokens("Finset.sum_comm' h.1"), 2)
        self.assertEqual(tokens("h.2.1 x.1.symm"), tokens("h.right.left x.fst.symm"))
        self.assertEqual(tokens("(f x).1"), tokens("(f x).fst"))
        self.assertEqual(tokens("h . 2"), 3)
        self.assertEqual(tokens('"a string -- with stuff"'), 1)

    def test_code_lines(self):
        src = "/- a\nb -/\ntheorem t :\n\n  True := -- x\n  trivial\n-- y\n"
        self.assertEqual(code_lines(src), 3)
        self.assertEqual(code_lines('def s := "a\n\nb"'), 2)
        self.assertEqual(strip_comments("a /- x\ny -/ b"), "a \n b")


if __name__ == "__main__":
    unittest.main()
