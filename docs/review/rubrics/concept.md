# Concept (blocking)

Question: is every new definition, structure, class, abbreviation and lemma a
mathematically natural unit of group theory, and does the change keep the
mathematical structure of the proofs visible?

The project rewards new declarations that are used many times, so the cheap
way to earn points is to package whatever text happens to repeat. A unit is
natural when a group theorist would recognise it, could name it, or could
state it as one sentence of mathematics; it is not natural merely because it
occurs twice.

## What to do

For each new or changed declaration other than a protected one, write one
sentence in plain mathematics saying what it is or states (in your analysis,
before the marker). If you cannot write that sentence without listing the
hypotheses one by one, the declaration is a bundle, not a concept. Judge the
body and statement, never the name or docstring: a natural concept with a poor
name is a naming matter (advisory), and an arbitrary bundle with a good name
is still a bundle.

## Natural (approve)

- A definition of a standard object or property: the Fitting subgroup,
  `O_p(G)`, a component or the layer, a `p`-local subgroup, a strongly or
  tightly embedded subgroup, a signalizer functor, the `p`-rank, a minimal
  simple group, a Thompson factorization.
- A recognisable fact as a lemma: a Frattini argument, a coprime action
  lemma, a transfer or fusion statement, a counting identity, a case of the
  Three Subgroups Lemma, a bound on an order or an index.
- A general lemma of which the old copies are specializations, when its
  statement is still one coherent fact.
- A structure for a configuration that the proof itself treats as one object
  ("the hypotheses of Section 7", "a minimal counterexample", "an involution
  centralizer of type X"), with the fields that configuration has.
- A lemma extracted from proofs when its statement is a coherent intermediate
  result, even if specialised to this target.

## Not natural (block)

- A `structure`, `class`, `def` or `Prop` that conjoins hypotheses because
  they co-occur at the call sites, with no meaning beyond "the hypotheses of
  lemmas A and B".
- A lemma that is a cut-out fragment of a proof: the whole local context of
  the proof turned into hypotheses, with a conclusion that is just the next
  goal there.
- A parameter, Boolean flag or case split introduced only to merge two
  different statements into one declaration.
- An abbreviation of a term that is not an object of the theory, used to save
  tokens (for example a `def` for `H ⊓ K.normalizer ⊔ L` when that subgroup
  plays no role of its own).
- A change that hides the mathematical structure: a named intermediate result
  of the original proof replaced by an anonymous one, or a generalization that
  makes the statement harder to recognise than the copies it replaces.

## Not your angle

Duplication of existing declarations (reuse), proof layout and names of new
lemmas (readability), robustness, naming style and docstrings (advisory).

## Verdict

`block` with a finding at each unnatural declaration: say why it is not a unit
(what it bundles or cuts) and, where possible, the natural unit that would
replace it. Otherwise `approve`.
