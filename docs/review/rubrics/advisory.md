# Advisory (never blocks)

Notes that help the author or a later contributor, but never stop a merge.
Your verdict is always `approve` and every finding has severity `advice`.
Report at most eight notes, the most useful first; none is fine.

## Proof robustness

- Heavy automation replacing explicit steps where a later upstream or Mathlib
  change could break it: a non-terminal `simp` without `only` followed by
  further tactics, `simp_all` or `aesop` doing a long search, a `decide` or
  `simp` over a large finite structure, `grind` with many supplied lemmas.
- Build-time risk: a proof that now unfolds a large definition, a `decide` on a
  big group, an elaboration-heavy term that replaced a few short steps.
- Reliance on definitional unfolding across a new definition (`rfl`, `show`,
  `change` through it) where a characterising lemma would be stabler.

## Naming conventions

Mathlib style: theorems and lemmas in `snake_case` describing the conclusion
(`Subgroup.normal_of_index_eq_two`, `Subgroup.index_mul_card`); `Prop`-valued definitions as
`IsFoo`; structures and types in `UpperCamelCase`; other definitions in
`lowerCamelCase`; group-theory terms as Mathlib already uses them
(`normalizer`, `centralizer`, `IsPGroup`, `Sylow`, `index`). A name must not
promise more than the statement (`_iff` for one direction). Meaningless names
are a readability block, not advice; do not repeat them here.

## Documentation of new public declarations

A new public definition, structure or general lemma should have a docstring
saying in mathematical terms what it is, and the standard name or a reference
when there is one (for example "the generalized Fitting subgroup F*(G)").
Do not ask for docstrings on private helpers.

## Not findings

Correctness, build, token counts, protected statements (machine-checked);
whether a concept is natural, duplication, golfed proofs (the blocking
reviewers).
