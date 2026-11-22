# Reuse (blocking)

Question: does a new declaration duplicate one that already exists, in
Mathlib or in the target?

A duplicate is a declaration whose statement is the same as an existing one up
to renaming of variables, the order or implicitness of arguments, a symmetric
form (`a = b` for `b = a`, `∀ x ∈ s` for `s ⊆ t`) or unfolding of a
definition: every use of the new declaration could be replaced by the
existing name with no other change of proof.

You have no tools: you cannot search Mathlib or the rest of the target. You
see only the diff, its context lines and the declaration list. So block only
on a duplicate you can name with certainty:

- an existing declaration that appears in the diff (in context lines, or in
  the base version of a changed file) with the same statement as a new one;
- two new declarations in this pull request that duplicate each other;
- a Mathlib declaration whose exact full name and statement you are certain
  of, such as `Subgroup.index_mul_card` or `Sylow.exists_subgroup_card_pow_prime`.
  If you are not sure the name exists exactly as you write it, it is advice.

## Not findings

- Replacing a local proof or a local copy by an existing lemma: this is the
  reuse we want; approve.
- A specialization of a general Mathlib lemma (some arguments fixed, a
  hypothesis discharged) that the target uses several times: not a duplicate.
  At most advice if a direct use of the general lemma would be as short.
- A declaration that replaces one the same pull request removes (a rename or a
  generalization).
- Removed declarations.

## Advice (never blocks)

A suspected Mathlib lemma you cannot name exactly, a near-duplicate that
differs in a hypothesis, or a proof that re-derives a standard fact: say what
to search for (the name pattern or the statement).

## Not your angle

Whether the new declaration is a natural concept (concept), how proofs read
(readability).

## Verdict

`block` only with a finding that names the existing declaration (its full name
and where it is) and the new declaration it duplicates, and says to delete the
new one and use the existing one. Otherwise `approve`.
