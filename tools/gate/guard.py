#!/usr/bin/env python3
"""Refuse Lean changes that add compile-time code or proof shortcuts.

    python3 tools/gate/guard.py --base-dir BASE --head-dir HEAD --target FeitThompson \
        [--allowed-set-options FILE] [--json OUT]

Every .lean file under CFSG/<target>/ of the head tree is compared with the
same file of the base tree (an added file is compared with ""; a removed
file is fine). Each file is read with tools/lean_lex.py, never with regular
expressions over raw text, and its risky features are counted: commands that
run code (#eval, run_cmd, initialize, ...), new syntax (macro, elab,
notation, ...), compiled or foreign code (unsafe, extern, implemented_by),
shortcuts (sorry, native_decide, axiom, sorryAx, ofReduceBool, ...), Lean or
operating-system internals (Lean.*, IO, System.*), opening metaprogramming
namespaces, name literals and syntax quotations, set_option, attributes other
than plain ones such as @[simp], imports outside Mathlib/CFSG/Batteries/
Aesop/Qq/Std, and constructs that Lean's parser recovery could read
differently from this lexer. A feature whose count grows is a problem;
features the base already had are tolerated (upstream may use them).

Problems start with `no_metaprogramming: ` or `no_shortcuts: ` and name the
file, the line and a fix. Exit status: 0 clean, 2 problems, 75 could not
decide (a base file Lean could not lex, missing directories). Standard
library only.
"""

from __future__ import annotations

import argparse
import bisect
import json
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from lean_lex import COMMENT_KINDS, STRING_KINDS, LexError, Token, tokenize  # noqa: E402

META = "no_metaprogramming"
SHORT = "no_shortcuts"

# -- tables ------------------------------------------------------------------

# keywords (exact identifier text) that run code, define syntax, or compile
# foreign code while Lean elaborates the file
CODE_KEYWORDS = frozenset("""
run_cmd run_elab run_meta run_tac by_elab by_elabq run_tacq initialize builtin_initialize
include_str include_str_chunks test_extern polyrith
elab elab_rules macro macro_rules syntax declare_syntax_cat notation notation3
infix infixl infixr prefix postfix binder_predicate
simproc simproc_decl dsimproc dsimproc_decl builtin_simproc builtin_simproc_decl
builtin_dsimproc builtin_dsimproc_decl cbv_simproc cbv_simproc_decl builtin_cbv_simproc
builtin_cbv_simproc_decl grind_propagator builtin_grind_propagator unif_hint
register_simp_attr register_option register_builtin_option register_label_attr
declare_aesop_rule_sets declare_simp_like_tactic declare_config_elab
declare_command_config_elab register_tactic_tag register_try?_tactic tactic_extension
register_error_explanation
unsafe partial implemented_by extern export opaque meta prelude
""".split())

# `name%` term elaborators (Lean, Mathlib, CFSG) that evaluate code, read
# files or reach elaborator internals; `x%2` and the notation-like ones
# (`T%`, `binop%`, `reassoc_of%`, ...) are not here
PERCENT_CODE = frozenset("""
eval include_hex_bytes giant_archive giant_archive_eq hn_orbit_data gl83_local gs_grammar matrix_model
yardstone_type compile_def compile_inductive elabToSyntax reset_grind_attrs private_decl rawProj
reduceProj let_mvar wait_for_expected_type wait_if_contains_mvar wait_if_type_contains_mvar
wait_if_type_mvar with_decl_name decl_name clear clean no_error_if_unused simproc_pattern
builtin_simproc_pattern cbv_simproc_pattern builtin_cbv_simproc_pattern struct_inst_default
satisfies_binder_pred value_of map_of full_standard derive_fintype gen_injective_theorems
expand_binders expand_foldl expand_foldr for_in simpTerm default_or_ofNonempty
""".split())
PERCENT_HARMLESS = frozenset("""
binop_lazy binrel_no_prop no_implicit_lambda ensure_type_of ensure_expected_type reassoc_of elementwise_of
to_app_of prod_assoc proxy_equiv fast_instance
""".split())

# keywords that stand in for a proof or trust the compiler instead of the kernel
SHORTCUT_KEYWORDS = frozenset("sorry admit stop native_decide axiom native bv_decide".split())

# identifier components that reach the kernel's escape hatches
SHORTCUT_NAMES = frozenset("sorryAx ofReduceBool ofReduceNat reduceBool reduceNat trustCompiler "
                           "skipKernelTC".split())
# identifier components that reach Lean's internals or the operating system
META_NAMES = frozenset("Lean Lake IO EIO BaseIO unsafeCast unsafeIO unsafeBaseIO unsafeEIO "
                       "ptrAddrUnsafe withPtrAddr unsafePerformIO".split())
# namespaces whose members reach the operating system: `System.FilePath`,
# `ST.Ref` (a bare `section System` is fine)
META_FIRST_NAMES = frozenset({"System", "ST"})

# opening or entering these namespaces exposes metaprogramming or extra syntax
# (ProofWidgets.Jsx reads raw text, Qq has run_tacq)
FORBIDDEN_NAMESPACES = frozenset("Lean Lake IO System Elab Meta Parser PrettyPrinter ProofWidgets Jsx "
                                 "Qq".split())

# `#` commands of the pinned toolchain, Mathlib, Batteries, Aesop, Qq,
# LeanSearchClient and CFSG (scanned from their syntax declarations). Lean
# matches symbol tokens by longest prefix, so `#evalx` is `#eval x`.
HASH_COMMANDS = tuple(sorted(set("""
#adaptation_note #aesop_rules #aesop_stats #allow_unused_tactic #browse #check #check_assertions
#check_copyright #check_failure #check_simp #check_tactic #check_tactic_failure #check_title
#checkh #clear_deprecations #click_suggestions #collapse #computability #conv #copy
#count_heartbeats #defeq_abuse #deprecate #discr_tree_key #discr_tree_simp_key #dlmf_tags
#dump_async_env_state #ensure_defeq #eval #exit #explode #expr_graph #find #find_home
#find_syntax #grind_lint #guard #guard_computable #guard_expr #guard_msgs #guard_panic #help
#html #import_bumps #import_diff #import_path #info_trees #instances #kerodon_tags #lang
#leansearch #lint #list_linters #lmfdb_tags #load_decls #load_ktree #log_keys #long_instances
#long_names #loogle #min_imports #minimize_imports #norm_imports #norm_num #parse #pibase_tags
#postprocess_traces #pretty_current_imports #print #print_fun_prop_theorems #pull #push
#push_discr_tree #reduce #redundant_imports #reexport #reset_min_imports #rw?? #sample #search
#show_deprecated_modules #show_kind #show_new_reserved #show_unused #simp #stacks_tags
#statesearch #string_diagram #synth #test #time #trans_imports #unfold? #unused_transitive_imports
#version #whats_new #where #whnf #whnfR #widget #wikidata_tags #with_exporting
""".split()), key=lambda c: -len(c)))
# an unknown `#word` that looks like a command (lowercase with `_`, or six
# letters or more) is treated as one too: Lean reads `#s` as the card
# notation, but nothing in a proof looks like `#foo_bar`
UNKNOWN_HASH = re.compile(r"[a-z][a-z0-9_]{5,}[!?]*|[a-z][a-z0-9]*_[a-z0-9_]*[!?]*")

# attributes that only register lemmas, set reducibility or add metadata.
# Anything that registers an elaborator, delaborator, unexpander, macro,
# tactic, simproc, norm_num/positivity extension, coercion (it changes how
# statements print), init hook, extern/export/implemented_by, csimp or a
# linter is not here.
ALLOWED_ATTRIBUTES = frozenset("""
simp ext norm_cast push_cast instance reducible irreducible semireducible instance_reducible
inline specialize simps to_additive to_dual mk_iff gcongr aesop fun_prop continuity
measurability nolint deprecated refl symm trans congr elab_as_elim elab_without_expected_type
induction_eliminator cases_eliminator nontriviality field_simps mono expose inherit_doc grind
bound reassoc elementwise zify_simps qify_simps rify_simps mfld_simps parity_simps match_pattern
class
""".split())
# words that must not appear inside the arguments of an allowed attribute
# (`@[aesop safe tactic]` registers a tactic; `(attr := …)` nests attributes)
DANGEROUS_ATTRIBUTE_WORDS = frozenset("""
command_elab term_elab tactic macro delab app_delab app_unexpander extern implemented_by export
csimp init builtin_init env_linter linter simproc sevalproc coe norm_num positivity pp_nodot
pp_using_anonymous_constructor combinator_formatter combinator_parenthesizer
run_builtin_parser_attribute_hooks builtin_doc never_extract macro_inline default_instance
command_parser term_parser builtin_command_parser builtin_term_parser builtin_tactic
builtin_term_elab builtin_command_elab builtin_macro builtin_delab
""".split())

ALLOWED_IMPORT_ROOTS = frozenset("Mathlib CFSG Batteries Aesop Qq Std".split())

# declaration keywords whose name Lean recovers from by skipping raw
# characters up to whitespace or one of ( ) : { } | (Lean/Parser/Command.lean)
RAW_SKIP_KEYWORDS = frozenset("def theorem opaque axiom inductive coinductive".split())
RAW_SKIP_DELIMS = frozenset(" \t\r\n():{}|")
UNIVERSE_SKIP_DELIMS = frozenset(" \t\r\n,}")
INERT_KINDS = frozenset({"ident", "number", "field_idx", "symbol"})

HINTS = {
    "hash": (META, "adds the command `{x}`, which runs or prints code while Lean compiles",
             "delete it; a refactor never needs it"),
    "code": (META, "adds `{x}`, which runs code, defines new syntax or compiles foreign code",
             "remove it and use existing definitions and tactics"),
    "shortcut": (SHORT, "adds `{x}`, which skips a proof or trusts the compiler instead of the kernel",
                 "give a real proof"),
    "meta_name": (META, "uses `{x}`, which reaches Lean's internals or the operating system",
                  "remove it"),
    "shortcut_name": (SHORT, "uses `{x}`, which bypasses the kernel or stands in for a proof",
                      "give a real proof"),
    "namespace": (META, "uses {x}, which exposes metaprogramming or extra syntax", "remove it"),
    "quotation": (META, "adds the quotation {x}, which only metaprograms use", "remove it"),
    "set_option": (SHORT, "adds `set_option {x}`, which changes how Lean checks or prints this file",
                   "remove it; only options the file already had are accepted"),
    "attribute": (META, "adds the attribute `{x}`, which can change how Lean elaborates, compiles or "
                        "prints declarations", "use only plain attributes such as @[simp] or @[ext]"),
    "import": (META, "adds `{x}`",
               "import only Mathlib, CFSG, Batteries, Aesop, Qq or Std modules, without `meta` or `all`"),
    "brace_string": (META, "adds the string literal {x}, whose `{{…}}` Lean may read as code",
                     "remove the string; proofs do not need it"),
    "raw_skip": (META, "puts {x} right after `{kw}`; Lean would skip it character by character and could "
                       "read a comment or string after it as code", "write a plain name right after `{kw}`"),
}


class GuardSetupError(Exception):
    """The guard cannot decide (e.g. a base file Lean could not lex)."""


class Feature:
    __slots__ = ("key", "kind", "x", "line", "kw")

    def __init__(self, key, kind, x, line, kw=""):
        self.key, self.kind, self.x, self.line, self.kw = key, kind, x, line, kw


# -- feature extraction --------------------------------------------------------

def _components(name: str) -> list[str]:
    return [c for c in name.split(".") if c and c != "_root_"]


def _split_entries(toks: list[Token]) -> list[list[Token]]:
    """Split a bracketed list at commas outside nested brackets."""
    out, cur, depth = [], [], 0
    for t in toks:
        if t.kind == "symbol" and t.text in "([{⟨":
            depth += 1
        elif t.kind == "symbol" and t.text in ")]}⟩":
            depth -= 1
        if depth == 0 and t.kind == "symbol" and t.text == ",":
            out.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        out.append(cur)
    return out


def _bracket_body(code: list[Token], k: int, open_: str, close: str) -> tuple[list[Token], int]:
    """code[k] is the opening bracket; return the tokens inside and the index
    after the matching closer (or the end)."""
    depth = 0
    for j in range(k, len(code)):
        t = code[j]
        if t.kind == "symbol" and t.text == open_:
            depth += 1
        elif t.kind == "symbol" and t.text == close:
            depth -= 1
            if depth == 0:
                return code[k + 1:j], j + 1
    return code[k + 1:], len(code)


def _attribute_features(entries: list[list[Token]], line: int, out: list[Feature]) -> None:
    for entry in entries:
        toks = list(entry)
        while toks and ((toks[0].kind == "ident" and toks[0].value in ("local", "scoped"))
                        or (toks[0].kind == "symbol" and toks[0].text == "-")):
            toks.pop(0)
        if not toks:
            continue
        name = toks[0].value if toks[0].kind == "ident" else toks[0].text
        args = toks[1:]
        bad = [t.value for t in args if t.kind == "ident" and t.value in DANGEROUS_ATTRIBUTE_WORDS]
        if name not in ALLOWED_ATTRIBUTES or bad:
            x = name if not bad else f"{name} … {bad[0]}"
            out.append(Feature(f"attribute {x}", "attribute", x, toks[0].line))
        # nested attribute lists: `(attr := simp, norm_cast)`
        for j in range(len(args) - 2):
            if (args[j].kind == "symbol" and args[j].text == "(" and args[j + 1].kind == "ident"
                    and args[j + 1].value == "attr" and args[j + 2].text == ":="):
                inner, _ = _bracket_body(args, j, "(", ")")
                _attribute_features(_split_entries(inner[2:]), line, out)


def _raw_skip_hazard(src: str, toks: list[Token], starts: list[int], start: int,
                     delims: frozenset) -> tuple[bool, str]:
    """Lean skips raw characters from src[start] (a token start) up to
    whitespace or a delimiter. True if that stretch is not made of whole
    identifiers, numbers and plain symbols, i.e. if Lean would resume inside
    something this lexer reads as a comment, string or literal."""
    q = start
    while q < len(src) and src[q] not in delims:
        q += 1
    j = bisect.bisect_left(starts, start)
    while j < len(toks) and toks[j].start < q:
        t = toks[j]
        if t.kind not in INERT_KINDS or t.end > q:
            return True, src[start:min(q, start + 30)]
        j += 1
    return False, ""


def features(src: str) -> list[Feature]:
    """Risky features of one file, in source order. Raises LexError."""
    src = src.replace("\r\n", "\n")
    all_toks = tokenize(src)
    out: list[Feature] = []
    _scan(src, all_toks, out)
    return out


def _scan(src: str, all_toks: list[Token], out: list[Feature]) -> None:
    code = [t for t in all_toks if t.kind not in COMMENT_KINDS]
    starts = [t.start for t in all_toks]
    n = len(code)
    for k, t in enumerate(code):
        nxt = code[k + 1] if k + 1 < n else None
        if t.code:
            _scan(src, t.code, out)
        if t.kind in STRING_KINDS and (t.code or "{" in t.text):
            out.append(Feature(f"brace_string {t.text}", "brace_string", t.text[:40], t.line))
        if t.kind in ("name_lit", "syntax_quote", "backtick"):
            x = {"syntax_quote": "`(…)", "backtick": "`"}.get(t.kind, t.text)
            out.append(Feature(f"quotation {t.text}", "quotation", x, t.line))
            continue
        if t.kind == "symbol":
            if t.text == "#" and nxt is not None and nxt.kind == "ident" and nxt.start == t.end:
                word = "#" + nxt.text
                cmd = next((c for c in HASH_COMMANDS if word.startswith(c)), None)
                if cmd is None and UNKNOWN_HASH.fullmatch(nxt.text.split(".")[0]):
                    cmd = "#" + nxt.text.split(".")[0]
                if cmd is not None:
                    out.append(Feature(f"hash {cmd}", "hash", cmd, t.line))
            elif t.text == "@" and nxt is not None and nxt.text == "[" and nxt.start == t.end:
                body, _ = _bracket_body(code, k + 1, "[", "]")
                _attribute_features(_split_entries(body), t.line, out)
            continue
        if t.kind != "ident":
            continue
        v = t.value
        if (nxt is not None and nxt.text == "%" and nxt.start == t.end
                and (v in PERCENT_CODE or ("_" in v and v not in PERCENT_HARMLESS))):
            out.append(Feature(f"code {v}%", "code", f"{v}%", t.line))
        if v in CODE_KEYWORDS:
            out.append(Feature(f"code {v}", "code", v, t.line))
        if v in SHORTCUT_KEYWORDS:
            out.append(Feature(f"shortcut {v}", "shortcut", v, t.line))
        parts = _components(v)
        if any(p in SHORTCUT_NAMES for p in parts):
            out.append(Feature(f"shortcut_name {v}", "shortcut_name", v, t.line))
        elif any(p in META_NAMES for p in parts) or (len(parts) > 1 and parts[0] in META_FIRST_NAMES):
            out.append(Feature(f"meta_name {v}", "meta_name", v, t.line))
        if v in ("open", "namespace", "export"):
            j = k + 1
            while j < n:
                a = code[j]
                if a.line != t.line and a.col <= t.col:
                    break
                if a.kind == "ident":
                    if a.value == "in":
                        break
                    if any(p in FORBIDDEN_NAMESPACES for p in _components(a.value)):
                        x = f"`{v} {a.value}`"
                        out.append(Feature(f"namespace {v} {a.value}", "namespace", x, a.line))
                elif not (a.kind == "symbol" and a.text in "(),→"):
                    break
                j += 1
                if v == "namespace":
                    break
        elif v == "set_option":
            name = code[k + 1].value if k + 1 < n else "?"
            value = code[k + 2].text if k + 2 < n else "?"
            x = f"{name} {value}"
            out.append(Feature(f"set_option {x}", "set_option", x, t.line))
        elif v == "attribute" and nxt is not None and nxt.text == "[":
            body, _ = _bracket_body(code, k + 1, "[", "]")
            _attribute_features(_split_entries(body), t.line, out)
        elif v == "import":
            mods = []
            j = k - 1
            while j >= 0 and code[j].kind == "ident" and code[j].value in ("public", "meta") \
                    and code[j].line == t.line:
                mods.insert(0, code[j].value)
                j -= 1
            j = k + 1
            if j < n and code[j].kind == "ident" and code[j].value == "all":
                mods.append("all")
                j += 1
            module = code[j].value if j < n and code[j].kind == "ident" else "?"
            parts = _components(module)
            if "meta" in mods or "all" in mods or not parts or parts[0] not in ALLOWED_IMPORT_ROOTS:
                x = ("meta " if "meta" in mods else "") + "import " + ("all " if "all" in mods else "") + module
                out.append(Feature(x, "import", x, t.line))
        if v in RAW_SKIP_KEYWORDS and nxt is not None:
            bad, what = _raw_skip_hazard(src, all_toks, starts, nxt.start, RAW_SKIP_DELIMS)
            if bad:
                out.append(Feature(f"raw_skip {v} {what}", "raw_skip", f"`{what}`", t.line, kw=v))
        # universe lists `foo.{u, v}`: Lean recovers from a bad entry the same way
        if (nxt is not None and nxt.text == "." and nxt.start == t.end and k + 2 < n
                and code[k + 2].text == "{" and code[k + 2].start == nxt.end):
            body, _ = _bracket_body(code, k + 2, "{", "}")
            items = [body[0].start] if body else []
            items += [body[i + 1].start for i, b in enumerate(body[:-1]) if b.text == ","]
            for st in items:
                bad, what = _raw_skip_hazard(src, all_toks, starts, st, UNIVERSE_SKIP_DELIMS)
                if bad:
                    out.append(Feature(f"raw_skip .{{ {what}", "raw_skip", f"`{what}`", t.line, kw=".{"))


# -- comparison --------------------------------------------------------------------

def _message(f: Feature, path: str, line: int, extra: int) -> str:
    check, what, hint = HINTS[f.kind]
    what = what.format(x=f.x, kw=f.kw)
    hint = hint.format(kw=f.kw)
    more = f" ({extra + 1} new uses)" if extra else ""
    return f"{check}: {path}:{line}: {what}{more}; {hint}"


def check_file(base: str, head: str, path: str, target: str, allowed_set_options: set[str]) -> list[str]:
    """Problems that head adds over base (both whole file texts)."""
    try:
        base_f = features(base) if base else []
    except LexError as e:
        raise GuardSetupError(f"{path}: the base version could not be read as Lean source ({e})") from e
    try:
        head_f = features(head)
    except LexError as e:
        return [f"{META}: {path}:{e.line or 1}: could not be read as Lean source ({e.reason}); "
                "fix the file so Lean itself can read it"]
    allowed = {" ".join(o.split()) for o in allowed_set_options}
    keep = lambda fs: [f for f in fs if not (f.kind == "set_option" and f.x in allowed)]  # noqa: E731
    base_f, head_f = keep(base_f), keep(head_f)
    base_n = Counter(f.key for f in base_f)
    head_n = Counter(f.key for f in head_f)
    base_lines = {}
    blines = base.replace("\r\n", "\n").splitlines()
    for f in base_f:
        base_lines.setdefault(f.key, set()).add(blines[f.line - 1].strip() if f.line <= len(blines) else "")
    hlines = head.replace("\r\n", "\n").splitlines()
    problems = []
    seen = set()
    for f in head_f:
        if f.key in seen or head_n[f.key] <= base_n[f.key]:
            continue
        seen.add(f.key)
        occ = [g for g in head_f if g.key == f.key]
        old = base_lines.get(f.key, set())
        fresh = [g for g in occ if (hlines[g.line - 1].strip() if g.line <= len(hlines) else "") not in old]
        where = (fresh or occ[base_n[f.key]:] or occ)[0]
        problems.append(_message(f, path, where.line, head_n[f.key] - base_n[f.key] - 1))
    return problems


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def check_tree(base_dir: str, head_dir: str, target: str, allowed_set_options: set[str]) -> list[str]:
    """Problems of every .lean file under CFSG/<target>/ of head_dir."""
    if not re.fullmatch(r"[A-Za-z0-9_]+", target):
        raise GuardSetupError(f"invalid target {target!r}")
    rel_root = os.path.join("CFSG", target)
    head_root = os.path.join(head_dir, rel_root)
    if not os.path.isdir(head_dir) or not os.path.isdir(base_dir):
        raise GuardSetupError("base or head directory missing")
    problems = []
    if not os.path.isdir(head_root):
        return problems
    for d, dirs, files in os.walk(head_root):
        for name in sorted(dirs + files):
            full = os.path.join(d, name)
            rel = os.path.relpath(full, head_dir).replace(os.sep, "/")
            if os.path.islink(full):
                problems.append(f"{META}: {rel}:1: is a symbolic link; replace it with an ordinary file")
                continue
            if name not in files or not name.endswith(".lean"):
                continue
            try:
                head = _read(full)
            except UnicodeDecodeError:
                problems.append(f"{META}: {rel}:1: is not valid UTF-8; save it as UTF-8 text")
                continue
            bpath = os.path.join(base_dir, rel)
            base = ""
            if os.path.isfile(bpath) and not os.path.islink(bpath):
                try:
                    base = _read(bpath)
                except UnicodeDecodeError as e:
                    raise GuardSetupError(f"{rel}: base version is not valid UTF-8") from e
            problems += check_file(base, head, rel, target, allowed_set_options)
        dirs[:] = [x for x in dirs if not os.path.islink(os.path.join(d, x))]
    return problems


def read_allowed_set_options(path: str | None) -> set[str]:
    if not path:
        return set()
    out = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            words = line.split()
            if words[:1] == ["set_option"]:
                words = words[1:]
            if len(words) >= 2 and not words[0].startswith("#"):
                out.add(f"{words[0].replace('«', '').replace('»', '')} {words[1]}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-dir", required=True)
    ap.add_argument("--head-dir", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--allowed-set-options", help="file with one `NAME VALUE` per line")
    ap.add_argument("--json")
    a = ap.parse_args()
    try:
        allowed = read_allowed_set_options(a.allowed_set_options)
        problems = check_tree(a.base_dir, a.head_dir, a.target, allowed)
    except (GuardSetupError, OSError) as e:
        print(f"setup error: {e}", file=sys.stderr)
        if a.json:
            with open(a.json, "w", encoding="utf-8") as fh:
                json.dump({"ok": False, "error": str(e), "reasons": []}, fh, indent=1)
        sys.exit(75)
    for p in problems:
        print(p)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump({"ok": not problems, "reasons": problems}, fh, indent=1, ensure_ascii=False)
    sys.exit(2 if problems else 0)


if __name__ == "__main__":
    main()
