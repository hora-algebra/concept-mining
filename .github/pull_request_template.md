<!--concept-mining-target:v1 {"candidate":"","target":"","agent":""}-->

<!--
A refactoring adds exactly one file, lean/patches/<target>/NNNN-<candidate>.patch, and nothing else.
In the line above, fill in the candidate id, the target as CFSG/<target>, and the model that wrote
the patch (or "human"). tools/contribute.py fills all of this in for you.
Not a refactoring? Delete this text and describe your change.
-->

## Concept

<!-- Its name in the patch, and one or two sentences on what it means mathematically. -->

## What happens next

CI builds the patch on a clean copy of the library and checks that every protected theorem and its axioms are unchanged and that the library got smaller. An AI review then asks whether the change introduces a natural group-theory concept, avoids duplicating Mathlib, and keeps the code readable. When both pass, the pull request is merged automatically. If the comment says "Not accepted", let your agent fix the patch on this branch ([how](https://github.com/hora-algebra/concept-mining/blob/main/docs/contribute.md#if-the-comment-says-not-accepted)). A draft only reserves its candidate and is not checked.
