# AI review rubrics

A contribution that passes the machine checks (build, protected statements
and axioms, no shortcuts or metaprogramming, at least 50 Lean tokens saved) is
correct by construction. The AI review decides whether it is also *worth
merging*. Approved pull requests are merged with no person in the loop, so
three rubrics can block.

Each rubric is one model call, built in this order: [`_common.md`](_common.md)
(the shared protocol: what the machine already checked, untrusted input,
output format) as a developer message; then the pull request as a user
message of nonce-delimited untrusted blocks; then the rubric file and the
output reminder as a last developer message. The first two parts are the same
for all four calls of a review, so the later calls read them from the prompt
cache. Hunks that only delete whole declarations are condensed to one line,
and a change that only deletes declarations (and adds nothing but
whitespace-only lines) is approved without a call. The runner is
[`tools/gate/review.py`](../../../tools/gate/review.py).

| Rubric | Question | Blocks the merge? |
|---|---|---|
| [`concept`](concept.md) | Are new definitions, structures and lemmas natural units of group theory, not bundles packed to save tokens? | yes |
| [`reuse`](reuse.md) | Does a new declaration duplicate one in Mathlib or the target? (only a clear, named duplicate) | yes |
| [`readability`](readability.md) | Is the argument still readable, or golfed into opaque one-liners with meaningless names? | yes |
| [`advisory`](advisory.md) | Proof robustness, naming conventions, docstrings of new public declarations | no |

A pull request is approved when all three blocking rubrics approve. A rubric
whose answer cannot be read (`error`) is not an approval; the gate holds the
pull request and retries the review later. A review that would
exceed the daily spending cap is `deferred`, not rejected; a change too large
to review in one call is `too_large` and must be split into smaller pull
requests.

Changing any file in this folder changes `rubrics_sha256` in the review
record and invalidates earlier reviews.
