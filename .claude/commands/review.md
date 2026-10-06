---
description: Review the current change as a senior data engineer interviewing its author
---

Review the current change. This is read-only: do not edit, create or delete any file.

1. Find the change. If the current branch is not `main`, run `git diff main`. On `main`, run
   `git diff HEAD~1`. Also run `git status --short` so uncommitted work is included, and read
   any file the diff touches when the diff alone lacks context.
2. Review it as a senior data engineer interviewing the author. Reply in exactly this shape:

   **Three questions I would ask**
   Exactly three questions, numbered. Each names the file (and line where it helps) it is
   about, and probes a decision: correctness, idempotency, failure modes, units, data
   quality, cost, or testability.

   **What is missing or sloppy**
   A numbered list, most important first. Each item names the file and says what to change.
   Check against `CLAUDE.md` conventions: types and docstrings with units, tests alongside
   code, dbt descriptions and at least two tests per model, no secrets, no placeholders or
   TODOs, no unbuilt behaviour described as existing.

   **What is good**
   One paragraph.
