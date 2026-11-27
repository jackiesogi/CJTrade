---
description: Commit the current change and open a PR following CLAUDE.md §11
argument-hint: <type e.g. feat|fix|docs|chore|refactor> <short topic>
---
Turn the current change into a branch, commits and a PR, following §11 of
CLAUDE.md. Arguments: $ARGUMENTS (type and topic).

1. If on `master`, create `type/short-desc` from the latest `origin/master`.
   Leave unrelated uncommitted files (such as `exp/`) out of the commits.
2. Run `/verify` and stop if a step fails.
3. Write each commit message to a file: imperative subject of 5–12 words,
   body of at most 3 lines; `awk 'length > 72'` on it must print nothing.
   Commit with `SKIP=integration-cjshell-sinopac git commit -F <file>`; if an import or
   end-of-file hook rewrote files, `git add -A` and commit again.
4. Show the user the commits and the proposed PR title and body, and wait
   for approval before pushing.
5. Push the branch and run `gh pr create` with title `[type]: ...` and the
   body template from §11 (summary paragraph, `### Changes`, `### Notes`,
   `### Before merging`). Do not merge.

Report the PR URL.
