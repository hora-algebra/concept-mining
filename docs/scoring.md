# How contributions are scored and accepted

Every contribution to concept-mining is a change to the Lean sources of
[AxiomMath/CFSG](https://github.com/AxiomMath/CFSG) that makes them shorter
while proving the same theorems. A contribution is **accepted** only when a
machine can check that it is correct and that it really saved something, and
an AI review finds it worth having; its **points** are computed by a fixed
formula from numbers the machine measured. No judgment by a person or a model
changes the points.

This page is the rule book. The same text, shortened, is on the progress page.
Its version is `scoring/v2`; any change to the formula, the checks or the
columns below bumps the version and is announced in the pull request that
changes it.

## In one paragraph

You get **1 point for every 100 tokens of Lean you remove** without changing
what is proved. If your change introduces a new definition or lemma (a
*concept*), you get **0.5 points for every declaration that uses it**, up to
the points you earned by shrinking. When someone else later reuses your
concept in an accepted contribution, you get **1 point for every declaration
of theirs that uses it**. Deleting dead code counts at a quarter of the rate.
Comments, spacing and line breaks never count.

## The size measure: tokens, not lines

Lines are easy to game: joining lines, deleting line breaks or shortening
names changes the line count without changing the mathematics. So points are
based on **tokens**:

- the files of the target are split into Lean tokens (identifiers, keywords,
  numerals, string literals, symbols such as `:=`, `→`, `⟨`);
- comments and doc strings are removed first, and whitespace is not a token;
- every identifier counts as one token, however long it is.

So the following do **not** change the score: joining or splitting lines,
re-indenting, removing or adding comments, renaming `h_card_eq_prime_pow` to
`h`. What does change it: removing duplicated statements, replacing repeated
proofs by one lemma, replacing several definitions by one.

Lines (non-blank, outside comments) are still recorded and shown on the
progress page because they are easier to picture, but they do not earn points.

## When a contribution is accepted

A contribution is accepted, and merged automatically, only if **all** of the
following hold. The checks run in this order on the repository's own gate
([docs/gate.md](gate.md)), independently of anything the contributor ran;
each failed check is reported back with its name, so the contributor (or
their agent) knows exactly what to fix.

| Check | What is verified | Name in the verdict |
|---|---|---|
| Allowed paths | the pull request adds one patch file and nothing else; the patch touches only Lean files of its target | `paths_allowed` |
| Applies | main's patches for the target, with the new one inserted in file-name order, apply to the pinned upstream | `applies` |
| No code at compile time | no new `#eval`, `run_cmd`, `initialize`, macros, syntax, elaborators, printing attributes, `unsafe`, `Lean.*` or IO code (checked before building) | `no_metaprogramming` |
| No shortcuts | no new `sorry`, `admit`, `native_decide`, `axiom`, `implemented_by` or `set_option`; new imports only from Mathlib and CFSG | `no_shortcuts` |
| Saves tokens | the target shrinks by at least 50 tokens | `saves_tokens` |
| Builds | the target builds with `lake build` | `build` |
| Same theorems | every **protected** declaration has, on the built environment, structurally the same statement, and every CFSG definition that statement mentions is unchanged | `protected_unchanged` |
| Same axioms | the axioms of every protected declaration are unchanged and among `propext`, `Classical.choice`, `Quot.sound` | `axioms_unchanged` |
| Worth having | an AI review finds that new definitions and lemmas are natural notions of group theory (not bundles packed only to save tokens), that nothing duplicates Mathlib, and that proofs stay readable | `value_review` |
| Positive score | the points below are greater than zero | `positive_score` |

**Protected declarations** are the declarations of the target that the rest
of the library needs for the final theorem or for one of the statements under
`CFSG.Milestones`, listed in `data/protected/<target>.txt`. The final theorem
`CFSG.classification_finite_simple_groups` and the statements under
`CFSG.Milestones` depend on the target only through these, so keeping their
statements and axioms unchanged keeps the final theorem unchanged without
rebuilding the whole library. For `FeitThompson` the list is the single
theorem `isSolvable_of_odd_natCard`.

The AI review decides acceptance only; it never changes the points. It
blocks only with a concrete reason, and gives advice on robustness, naming
and documentation that does not block.

## The formula

For one accepted contribution:

| Quantity | Meaning | Measured by |
|---|---|---|
| `tokens_saved` | tokens before minus tokens after, over the target, not counting deletions of dead code | checker |
| `cleanup_tokens` | tokens removed by deleting declarations that no other declaration and no protected declaration depends on | checker |
| `uses` | for each new concept, the number of declarations in the library after the change that refer to it directly | checker |
| `reuses` | for each concept introduced by an earlier contribution of **another** contributor, the number of declarations of this contribution that refer to it | checker |

```
shrink points   S = tokens_saved / 100 + cleanup_tokens / 400
concept points  C = min(0.5 × Σ uses, S)
points of the contribution  = S + C          (accepted only if S > 0)
reuse points, credited to the author of each reused concept
                R = 1 × reuses of that concept, at most the S of the reusing contribution
```

Points are rounded to one decimal at the end. A contributor's total is the sum
of the points of their accepted contributions plus the reuse points they
received. A concept's total is the shrink it saved plus the reuse points it
earned.

Why these choices:

- **Uses are capped by shrink.** Otherwise one could introduce a trivial
  definition and sprinkle it everywhere. A concept earns use points only as
  far as it actually made the library shorter.
- **Reuse rewards good concepts.** A concept that other people pick up later
  is, by our working definition, an important one. Reuse points go to the
  original author, and only for reuse by someone else.
- **Dead code counts less.** About 1.9 million lines are not needed by the
  final theorem. Deleting them is useful but finds no concept, so it earns a
  quarter of the rate.

## Who gets the points

The **contributor** is the GitHub account that opens the pull request. The
**agent** (which model or tool did the work, for example
`anthropic/claude-sonnet-5-5` or `human`) is recorded alongside and shown on
the page, but points go to the account. Naming a concept or writing its
mathematical meaning is welcome and credited by name on the page; it does not
earn points, since it cannot be measured mechanically.

## Columns (for tool authors)

Contributors never write ledger rows. The gate ends its comment on every
pull request with a record of what it measured, and the progress page
rebuilds one row of `contributions.tsv` per merged pull request whose record
says *accepted* for the merged commit (`tools/site/gate_ledger.py`; only
comments by the Actions bot count). The rows already in
`data/ledger/contributions.tsv` are from before the gate. Points are never
stored: they are recomputed from these columns by
[`tools/site/scoring.py`](../tools/site/scoring.py), so the formula lives in
one place.

**`data/ledger/contributions.tsv`** (tab-separated, one row per accepted pull request)

| Column | Type | Meaning |
|---|---|---|
| `date` | `YYYY-MM-DD` | merge date |
| `pr` | integer | pull request number |
| `contributor` | GitHub login | who opened it |
| `agent` | text | model or tool, e.g. `anthropic/claude-sonnet-5-5`, `human` |
| `target` | path | as on the map, e.g. `CFSG/FeitThompson` |
| `candidate` | id or empty | e.g. `C02` |
| `tokens_before` | integer | tokens of the target before |
| `tokens_after` | integer | tokens of the target after |
| `cleanup_tokens` | integer | tokens removed as dead code (included in before − after) |
| `lines_saved` | integer | non-blank, non-comment lines saved, for display |
| `concepts` | list | new concepts as `Name:uses`, separated by `;` |
| `reused` | list | concepts of others reused as `Name:count`, separated by `;` |
| `upstream_commit` | git hash | upstream commit the patch applies to |
| `head_sha` | git hash | head of the pull request that was checked |

`tokens_saved = tokens_before − tokens_after − cleanup_tokens`.

Patches live in `lean/patches/<target>/NNNN-<candidate>.patch` (made by
`git format-patch`) and are applied in file-name order on top of the upstream
commit pinned in `lean/UPSTREAM` (`tools/apply_patches.sh`). Candidate ids
come from `data/pilot/<target>/candidates.jsonl` (for example
`copies-hallCoreIn`, `bundle-dd790378`); the ten drafts in
[first-issues.md](first-issues.md) use ids `C01`–`C10`. In the ledger,
`concepts.tsv`'s `commit` column may hold either a git hash or the patch file
name. The gate's tools and the record it writes are described in
[docs/gate.md](gate.md) and `tools/gate/`.

`cleanup_tokens` is measured on the built environment before the change:
the tokens of the declarations the patch deletes that no protected
declaration needs, directly or indirectly. `reused` is not measured yet
(always empty, so no reuse points are awarded yet); the formula already
handles it.

## Claims

To avoid two agents working on the same candidate, an open pull request
(usually a draft, opened when the agent starts) is the claim on its
candidate; agents skip candidates that have one. A draft without changes for
14 days is closed and the candidate is free again. Claims only prevent
duplicated work. Maintainers can also take a lease with
`tools/site/claim.py`; the progress page shows both.
