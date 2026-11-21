# The contribution gate

Every pull request to this repository goes through one workflow,
[`contribution-gate.yml`](../.github/workflows/contribution-gate.yml). For a
contribution it decides, without a person, whether the change is correct and
worth having, posts one comment with the result, and merges it if it is
accepted. Points follow from the measurements by
[docs/scoring.md](scoring.md).

## What a contribution is

A pull request that adds **exactly one file**,
`lean/patches/<target>/<NNNN>-<candidate>.patch`: a `git format-patch` file
that rewrites Lean files under `CFSG/<target>/` of the pinned upstream
commit ([`lean/UPSTREAM`](../lean/UPSTREAM)). Nothing else may change: no
ledger rows, no other patches, no tools. The gate writes everything else.
The contribution tools ([docs/contribute.md](contribute.md)) produce this
pull request for you.

A target is open for contributions when it has a baseline
`data/protected/<target>.json`.

## What happens, in order

| Step | Checks | Fails when |
|---|---|---|
| Shape | the pull request adds one patch file and changes nothing else | other files change, the patch is over 30 MB, the target is not open |
| Paths | the patch touches only `CFSG/<target>/*.lean`, as ordinary text files | any other path, a symlink, a binary or a mode change |
| Applies | main's patches for the target, with yours inserted in file-name order, all apply to the pinned upstream | the series does not apply; regenerate on the current main |
| Guard | no new compile-time code (`#eval`, `macro`, `elab`, `syntax`, `initialize`, attributes that register elaborators or printers, `Lean.*`/`IO` code), no shortcuts (`sorry`, `axiom`, `native_decide`, `implemented_by`, …), no new `set_option`; new imports only from Mathlib and CFSG | a count of any of these grows in some file |
| Size | the target shrinks by at least 50 Lean tokens | it does not; comments, whitespace and name lengths never count |
| Build | the target builds, first without and then with your patch | Lean reports an error |
| Inspect | on the built environment: the protected statements are structurally identical, their axioms are within `propext`, `Classical.choice`, `Quot.sound`, and no new declaration is metaprogramming, unsafe, partial, extern or `implemented_by` | anything differs |
| AI review | value, on three points that block: new definitions and lemmas are natural notions of group theory, not bundles packed only to save tokens; nothing duplicates Mathlib; proofs stay readable. Robustness, naming and documentation get advice that does not block | a blocking point is not met |
| Merge | the checked commit is still the head, and main has not changed since the check | main changed: the check starts again by itself |

The comment on the pull request lists every check, what to fix, and the AI
review's findings. Push a fix to the same branch and everything runs again.
The protected statements are the declarations of the target that the rest of
CFSG needs for the final theorem (`data/protected/<target>.txt`); the
baseline records a digest of each one's statement and of every CFSG
definition it mentions.

## Limits that keep the gate fair

- An author without write access has at most 5 open contributions checked at
  a time; later ones wait and are checked automatically.
- Each pull request gets at most 5 AI reviews (one per new head commit; an
  unchanged patch keeps its approval). After that it is closed; open a new
  one with a different approach.
- The AI review spends at most a daily budget (10 USD); when it is used up,
  reviews wait until the next day. Waiting is never a rejection.
- A draft pull request is a claim on its candidate and is not built. Drafts
  of outside contributors that see no change for 14 days are closed, and so
  are pull requests that stay not accepted for 14 days. The label `keep`
  stops both.
- Every 3 hours a sweep restarts checks that did not finish, and after each
  merge it re-checks the other open contributions to the same target.

## Why it is safe to merge without a person

- The workflow and every script come from the default branch, never from
  the pull request (`pull_request_target`). The patch is read as data
  through the API at the exact head commit.
- Lean runs code while it compiles, so the guard refuses compile-time code
  before anything is built, and Lean only ever runs in a job **without any
  GitHub token**, inside a [bubblewrap](https://github.com/containers/bubblewrap)
  sandbox with no network, an empty environment and only the build directory
  writable. The sandbox tests itself before every build.
- The protected statements are compared on the built environment by a
  checker that is compiled without your code and loads your modules only as
  data, so notation or printing tricks cannot make a changed statement look
  the same.
- The jobs that can comment, label and merge run none of your content. The
  ledger and the points are rebuilt from the gate's own comments, so a pull
  request cannot write its own score.
- What remains: the AI review can be wrong (it blocks only with a concrete
  reason, and its results are kept for audit); and a compile-time payload
  that got past the guard could, inside the sandbox, falsify its own pull
  request's measurements, though nothing else.

## For maintainers

| Setting | Where | Effect |
|---|---|---|
| `AUTO_MERGE_ENABLED` = `true` | repository variable | merge accepted contributions; otherwise the comment says a maintainer will merge |
| `OPENAI_API_KEY` | repository secret | the AI review; without it, contributions wait at the review step |
| `REVIEW_DAILY_CAP_USD` | repository variable (default 10) | the daily review budget |
| label `keep` | on a pull request | never closed by the sweep |

The review spend is recorded on the branch `ci-state`
(`review-spend.tsv`). Pull requests that are not contributions are left to
maintainers; those from outside contributors get the label
`needs-maintainer`. To check a pull request again by hand, run the workflow
*Contribution gate* with its number.
