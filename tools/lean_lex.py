#!/usr/bin/env python3
"""A Lean 4 lexer that follows the rules of Lean's own tokenizer (v4.35).

    tokenize(src) -> list[Token]

Every token has a kind, its source text, a 1-based line and column, and the
character offsets start/end. Comments are tokens too (kinds line_comment,
block_comment, doc_comment, mod_doc), so callers decide whether to keep them.

Where a comment or a string starts and ends is decided exactly as Lean
decides it (Lean/Parser/Basic.lean: whitespace, finishCommentBlock,
strLitFnAux, charLitFnAux, rawStrLitFnAux, numberFnAux, identFnAux), because
a lexer that disagrees with Lean there lets code hide inside what it believes
is a comment. In particular:

- comments are found before anything else at a token boundary, and inside a
  block comment only `/-` and `-/` matter (quotes do not);
- a string literal that could also be read as an interpolated string
  (`s!"…{e}…"`, `throwError "…{e}…"`, …) must end at the same place under
  both readings, otherwise LexError; the code inside `{…}` is lexed and kept
  in Token.code so a guard can scan it;
- `'x'` is a character literal only at a token boundary, so primes inside
  identifiers (h', x'') stay part of the name; `''` and the quote of
  symbols such as `⁻¹'`, `∑'`, `xs[i]'h` are symbols, and when Lean could
  read such a quote as a character literal instead (if the symbol's module is
  not imported) the two readings must not disagree about comments or strings;
- digits right after a projection dot are field indices (`h.2.1` is
  h . 2 . 1), not the decimal 2.1.

Symbols are grouped the way tools/size.py has always counted them: the
multi-character symbols := => <- -> <;> .. :: || && are one token, any other
symbol character is one token. Anything Lean itself would refuse to lex
raises LexError: unterminated comments, strings, identifier escapes or
character literals, invalid escapes (including `\\u{…}`, which Lean v4.35
does not accept), tabs, lone carriage returns, malformed numbers. Refusing
matters: after a lexical error Lean resumes in the middle of the literal and
reads its contents as code. Standard library only.
"""

from __future__ import annotations

import bisect
import re
import sys

COMMENT_KINDS = frozenset({"line_comment", "block_comment", "doc_comment", "mod_doc"})
STRING_KINDS = frozenset({"string", "interp_string"})
# identifiers that turn the string literal right after them into an interpolated one
INTERPOLATION_PREFIXES = frozenset({"s!", "m!", "f!"})
MAX_NESTING = 16
# symbols that Lean core, Mathlib or CFSG glue to a following quote into one
# token (`⁻¹'`, `∑'`, `xs[i]'h`, `Σ'`, `×'`, `⊕'`, BitVec `#'`, ...); found by
# scanning every syntax declaration of the pinned toolchain and dependencies
PRIME_STEMS = ("⁻¹", "]", "#", "=", "×", "Σ", "∀", "∃", "∇", "∏", "∑", "∘", "≺", "≼", "⊕", "⊗", "⟧",
               "𝐃", "𝐄", "𝐅", "𝐖")  # bold capitals are symbols in Lean (CFSG's `𝐖'[i]`)

_LETTER_LIKE = (
    "α-κμ-ω"          # lower Greek but lambda
    "Α-ΟΡ΢Τ-Ω"  # upper Greek but Pi and Sigma
    "ϊ-ϻ"                        # Coptic
    "ἀ-῾"                        # polytonic Greek
    "℀-⅏"                        # letterlike block
    "\U0001d49c-\U0001d59f"                # script, double-struck, fraktur
    "À-ÖØ-öø-ÿ"  # Latin-1 letters but × and ÷
    "Ā-ſ"                        # Latin Extended-A
)
_SUBSCRIPT = "₀-₉ₐ-ₜᵢ-ᵪⱼ"
_ID_FIRST = "A-Za-z_" + _LETTER_LIKE
_ID_REST = _ID_FIRST + "0-9'!?" + _SUBSCRIPT
_PART = rf"(?:«[^»]*»|[{_ID_FIRST}][{_ID_REST}]*)"
IDENT_RE = re.compile(rf"{_PART}(?:\.{_PART})*")
ID_FIRST_RE = re.compile(rf"[{_ID_FIRST}]")

_WS = re.compile(r"[ \n]+")
_MULTI = re.compile(r"<;>|:=|=>|<-|->|\.\.|::|\|\||&&")
_COMMENT_MARK = re.compile(r"-/|/-")
_PLAIN_STOP = re.compile(r'["\\]')
_INTERP_STOP = re.compile(r'["\\{]')
_DEC = re.compile(r"[0-9](?:_*[0-9])*")
_BIN = re.compile(r"(?:_*[01])+")
_OCT = re.compile(r"(?:_*[0-7])+")
_HEX = re.compile(r"(?:_*[0-9a-fA-F])+")
_HEX_DIGIT = "0123456789abcdefABCDEF"
_RAW_START = re.compile(r'#*"')


class LexError(ValueError):
    """The source is not lexically valid Lean (Lean itself would refuse it)."""

    def __init__(self, message: str, line: int = 0, col: int = 0):
        super().__init__(f"line {line}, column {col}: {message}" if line else message)
        self.reason = message
        self.line = line
        self.col = col


class Token:
    __slots__ = ("kind", "text", "line", "col", "start", "end", "value", "code")

    def __init__(self, kind, text, line, col, start, end, value=None, code=None):
        self.kind = kind
        self.text = text
        self.line = line
        self.col = col
        self.start = start
        self.end = end
        # identifiers: the name with «» escapes removed; otherwise the text
        self.value = text if value is None else value
        # strings: tokens of the code inside {…} (interpolation), else empty
        self.code = code if code is not None else []

    @property
    def is_comment(self) -> bool:
        return self.kind in COMMENT_KINDS

    def __repr__(self) -> str:
        return f"Token({self.kind!r}, {self.text!r}, {self.line}, {self.col})"

    def __eq__(self, other):
        return isinstance(other, Token) and (self.kind, self.text, self.start) == (other.kind, other.text, other.start)

    def __hash__(self):
        return hash((self.kind, self.text, self.start))


def is_id_first(ch: str) -> bool:
    return bool(ch) and ID_FIRST_RE.match(ch) is not None


def normalize_name(text: str) -> str:
    """`«a b».«c»` -> `a b.c`; plain names are returned unchanged."""
    if "«" not in text:
        return text
    return text.replace("«", "").replace("»", "")


class _Lexer:
    def __init__(self, src: str):
        self.s = src
        self.n = len(src)
        self.lines = [0] + [m.end() for m in re.finditer("\n", src)]

    # -- positions -------------------------------------------------------
    def pos(self, i: int) -> tuple[int, int]:
        line = bisect.bisect_right(self.lines, i)
        return line, i - self.lines[line - 1] + 1

    def err(self, message: str, i: int) -> LexError:
        line, col = self.pos(min(i, self.n))
        return LexError(message, line, col)

    def tok(self, kind, start, end, value=None, code=None) -> Token:
        line, col = self.pos(start)
        return Token(kind, self.s[start:end], line, col, start, end, value, code)

    # -- comments ----------------------------------------------------------
    def finish_comment(self, start: int, j: int) -> int:
        """End offset of a block comment whose body starts at j (nesting 1)."""
        s, depth = self.s, 1
        while True:
            m = _COMMENT_MARK.search(s, j)
            if m is None:
                raise self.err("unterminated comment", start)
            j = m.end()
            if m.group() == "-/":
                depth -= 1
                if depth == 0:
                    return j
            else:
                depth += 1

    # -- strings ---------------------------------------------------------
    def skip_escape(self, k: int, start: int, mode: str) -> int:
        """s[k] is a backslash; return the offset after the escape exactly as
        Lean's quotedCharCoreFn reads it (mode: "char", "string" or "interp").
        Every escape Lean refuses is a LexError: Lean would resume parsing in
        the middle of the literal, so its contents would be read as code."""
        s, n = self.s, self.n
        if k + 1 >= n:
            raise self.err("unterminated literal", start)
        c = s[k + 1]
        if c in "\\\"'rnt" or (mode == "interp" and c == "{"):
            return k + 2
        if c == "x" or c == "u":
            width = 2 if c == "x" else 4
            j = k + 2
            if j + width > n or any(ch not in _HEX_DIGIT for ch in s[j:j + width]):
                raise self.err(f"invalid \\{c} escape (Lean expects {width} hexadecimal digits)", k)
            return j + width
        if c == "\n" and mode != "char":
            # string gap: backslash, newline, then spaces without another newline
            j = k + 2
            while j < n and s[j] in " \t\r\n":
                if s[j] == "\n":
                    raise self.err("more than one newline in a string gap", k)
                j += 1
            return j
        raise self.err(f"invalid escape sequence \\{c}", k)

    def plain_string_end(self, i: int) -> int:
        s = self.s
        j = i + 1
        while True:
            m = _PLAIN_STOP.search(s, j)
            if m is None:
                raise self.err("unterminated string literal", i)
            k = m.start()
            if s[k] == '"':
                return k + 1
            j = self.skip_escape(k, i, "string")

    def interp_string(self, i: int, depth: int) -> tuple[int, list[Token]]:
        s = self.s
        j = i + 1
        code: list[Token] = []
        while True:
            m = _INTERP_STOP.search(s, j)
            if m is None:
                raise self.err("unterminated string literal", i)
            k = m.start()
            ch = s[k]
            if ch == '"':
                return k + 1, code
            if ch == "\\":
                j = self.skip_escape(k, i, "interp")
                continue
            toks, close = self.lex(k + 1, stop_at_brace=True, depth=depth + 1)
            code.extend(toks)
            j = close + 1

    def string(self, i: int, depth: int, interpolated: bool) -> tuple[int, list[Token]]:
        """Lex the string literal starting at s[i] == '"'. Returns its end and
        the interpolated code (if any)."""
        if interpolated:
            return self.interp_string(i, depth)
        end = self.plain_string_end(i)
        if "{" not in self.s[i:end]:
            return end, []
        # Some syntax (throwError, dbg_trace, trace[…], …) reads the next string
        # as interpolated: both readings must agree on where it ends.
        try:
            iend, code = self.interp_string(i, depth)
        except LexError:
            return end, []
        if iend != end:
            raise self.err("string literal reads differently as an interpolated string "
                           "(a `{` inside it opens code); rewrite the string", i)
        return end, code

    # -- main loop -------------------------------------------------------
    def lex(self, i: int, stop_at_brace: bool = False, depth: int = 0) -> tuple[list[Token], int]:
        if depth > MAX_NESTING:
            raise self.err("string interpolation nested too deeply", i)
        s, n = self.s, self.n
        out: list[Token] = []
        braces = 0
        while i < n:
            c = s[i]
            if c == " " or c == "\n":
                i = _WS.match(s, i).end()
                continue
            if c == "\t":
                raise self.err("tab character (Lean refuses tabs)", i)
            if c == "\r":
                raise self.err("isolated carriage return (Lean refuses them)", i)
            nxt = s[i + 1] if i + 1 < n else ""
            if c == "-" and nxt == "-":
                j = s.find("\n", i)
                j = n if j < 0 else j
                out.append(self.tok("line_comment", i, j))
                i = j
                continue
            if c == "/" and nxt == "-":
                third = s[i + 2] if i + 2 < n else ""
                kind = "doc_comment" if third == "-" else "mod_doc" if third == "!" else "block_comment"
                if i + 2 >= n:
                    raise self.err("unterminated comment", i)
                # Lean skips the character after `/-` (or reads the token
                # `/--`, `/-!`) before it looks for nested markers
                j = self.finish_comment(i, i + 3)
                out.append(self.tok(kind, i, j))
                i = j
                continue
            if c == '"':
                prev = out[-1] if out else None
                if (prev is not None and prev.kind == "ident" and prev.end == i
                        and prev.text in INTERPOLATION_PREFIXES):
                    end, code = self.string(i, depth, interpolated=True)
                    out.pop()
                    out.append(self.tok("interp_string", prev.start, end, code=code))
                else:
                    end, code = self.string(i, depth, interpolated=False)
                    out.append(self.tok("string", i, end, code=code))
                i = end
                continue
            if c == "'":
                if nxt == "'":
                    # `''` is Mathlib's image notation; without it Lean would read
                    # a character literal at the second quote
                    if self.prime_hazard(i + 1, stop_at_brace):
                        raise self.err("`''` followed by characters that Lean may read differently", i)
                    out.append(self.tok("symbol", i, i + 1))
                    out.append(self.tok("symbol", i + 1, i + 2))
                    i += 2
                    continue
                prev = out[-1] if out else None
                if (prev is not None and prev.kind == "symbol" and prev.end == i
                        and any(i >= len(stem) and s.startswith(stem, i - len(stem)) for stem in PRIME_STEMS)):
                    # `f ⁻¹' s`, `∑' i, f i`, `xs[i]'h`: the quote belongs to the
                    # symbol only if Lean has loaded that token, otherwise it
                    # opens a character literal, so both readings must agree
                    if self.prime_hazard(i, stop_at_brace):
                        raise self.err("a quote after a symbol, followed by characters that Lean may read "
                                       "as a character literal; add a space or rewrite", i)
                    out.append(self.tok("symbol", i, i + 1))
                    i += 1
                    continue
                j = i + 1
                if j >= n:
                    raise self.err("unterminated character literal", i)
                j = self.skip_escape(j, i, "char") if s[j] == "\\" else j + 1
                if j >= n or s[j] != "'":
                    raise self.err("missing end of character literal", i)
                out.append(self.tok("char", i, j + 1))
                i = j + 1
                continue
            if "0" <= c <= "9":
                prev = out[-1] if out else None
                if prev is not None and prev.kind == "symbol" and prev.text == "." and prev.end == i:
                    j = i + 1
                    while j < n and "0" <= s[j] <= "9":
                        j += 1
                    out.append(self.tok("field_idx", i, j))
                else:
                    j = self.number_end(i)
                    out.append(self.tok("number", i, j))
                i = j
                continue
            if c == "`":
                if is_id_first(nxt) or nxt == "«":
                    m = IDENT_RE.match(s, i + 1)
                    if m is None:
                        raise self.err("unterminated identifier escape «", i)
                    out.append(self.tok("name_lit", i, m.end(), value=normalize_name(m.group())))
                    i = m.end()
                    continue
                third = s[i + 2] if i + 2 < n else ""
                if nxt == "`" and (is_id_first(third) or third == "«"):
                    m = IDENT_RE.match(s, i + 2)
                    if m is None:
                        raise self.err("unterminated identifier escape «", i)
                    out.append(self.tok("name_lit", i, m.end(), value=normalize_name(m.group())))
                    i = m.end()
                    continue
                out.append(self.tok("syntax_quote" if nxt == "(" else "backtick", i, i + 1))
                i += 1
                continue
            if c == "r" and _RAW_START.match(s, i + 1):
                j = self.raw_string_end(i)
                out.append(self.tok("string", i, j))
                i = j
                continue
            if c == "«" or is_id_first(c):
                m = IDENT_RE.match(s, i)
                if m is None:
                    raise self.err("unterminated identifier escape «", i)
                text = m.group()
                out.append(self.tok("ident", i, m.end(), value=normalize_name(text)))
                i = m.end()
                continue
            m = _MULTI.match(s, i)
            j = m.end() if m else i + 1
            text = s[i:j]
            if stop_at_brace:
                if text == "{":
                    braces += 1
                elif text == "}":
                    if braces == 0:
                        return out, i
                    braces -= 1
            out.append(self.tok("symbol", i, j))
            i = j
        if stop_at_brace:
            raise self.err("unterminated `{` in an interpolated string", i)
        return out, i

    def prime_hazard(self, p: int, in_interpolation: bool) -> bool:
        """Lean may read s[p] == "'" as the start of a character literal (when
        the symbol token in front of it is not loaded). True if that reading
        could cover a comment, string, escape or name-quote start that this
        lexer reads differently, i.e. if the two readings could disagree on
        where code is."""
        s, n = self.s, self.n
        special = '"\\«`' + ("{}" if in_interpolation else "")
        for _ in range(64):
            a = s[p + 1] if p + 1 < n else ""
            if a == "'":
                p += 2  # `''` is read as one token
                if p < n and s[p] == "'":
                    continue
                return False
            b = s[p + 2] if p + 2 < n else ""
            if (a and a in special) or (b and b in special):
                return True
            if not a or not b:
                return False  # the file ends: nothing after it to misread
            if s.startswith(("--", "/-"), p + 1) or s.startswith(("--", "/-"), p + 2):
                return True
            if b != "'":
                return False  # Lean stops after s[p+2]; nothing special was covered
            p += 3  # a complete literal 'a'
            if p < n and s[p] == "'":
                continue
            return False
        return True

    def number_end(self, i: int) -> int:
        s, n = self.s, self.n
        if s[i] == "0" and i + 1 < n and s[i + 1] in "bBoOxX":
            rx = {"b": _BIN, "o": _OCT, "x": _HEX}[s[i + 1].lower()]
            m = rx.match(s, i + 2)
            if m is None:
                raise self.err("malformed number", i)
            j = m.end()
            if j < n and s[j] == "_":
                raise self.err("malformed number", i)
            return j
        j = _DEC.match(s, i).end()
        if j < n and s[j] == "_":
            raise self.err("malformed number", i)
        if s.startswith("..", j):
            return j
        if j < n and s[j] in ".eE":
            bare_dot = False
            if s[j] == ".":
                if j + 1 < n and "0" <= s[j + 1] <= "9":
                    j = _DEC.match(s, j + 1).end()
                    if j < n and s[j] == "_":
                        raise self.err("malformed number", i)
                else:
                    j += 1
                    bare_dot = True
            if j < n and s[j] in "eE":
                k = j + 1
                if k < n and s[k] in "+-":
                    k += 1
                if not (k < n and "0" <= s[k] <= "9"):
                    raise self.err("missing exponent digits in scientific literal", i)
                j = _DEC.match(s, k).end()
            elif bare_dot and j < n and (is_id_first(s[j]) or s[j] == "«"):
                raise self.err("identifier right after a decimal point", i)
        return j

    def raw_string_end(self, i: int) -> int:
        s = self.s
        j = i + 1
        hashes = 0
        while s[j] == "#":
            hashes += 1
            j += 1
        close = '"' + "#" * hashes
        k = s.find(close, j + 1)
        if k < 0:
            raise self.err("unterminated raw string literal", i)
        return k + len(close)


def tokenize(src: str) -> list[Token]:
    """All tokens of src, comments included, in source order."""
    src = src.replace("\r\n", "\n")
    lexer = _Lexer(src)
    try:
        toks, _ = lexer.lex(0)
    except RecursionError:
        raise LexError("nesting too deep to read") from None
    return toks


def code_tokens(src: str) -> list[Token]:
    """Tokens of src outside comments."""
    return [t for t in tokenize(src) if t.kind not in COMMENT_KINDS]


def walk(tokens):
    """Yield every non-comment token, descending into interpolated code."""
    for t in tokens:
        if t.kind in COMMENT_KINDS:
            continue
        yield t
        if t.code:
            yield from walk(t.code)


def main() -> None:
    for p in sys.argv[1:]:
        with open(p, encoding="utf-8") as fh:
            for t in tokenize(fh.read()):
                print(f"{t.line}:{t.col}\t{t.kind}\t{t.text!r}")


if __name__ == "__main__":
    main()
