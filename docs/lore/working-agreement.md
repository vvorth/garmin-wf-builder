# Working agreement — full text, with the incidents behind each rule

Moved verbatim out of `CLAUDE.md` on 2026-09-13 (§7) so the file every
session loads stays small. `CLAUDE.md` keeps a short summary and the **same
numbering**, so an older citation such as "CLAUDE.md §6" or "CLAUDE.md
constraint 6" for this material resolves here. Keep adding to this file,
not back into `CLAUDE.md`.

---

## 7. Working agreement

- **Stop and ask** when a decision materially changes the project's shape
  (authoring format, architecture, scope cuts). Present options with tradeoffs,
  give a recommendation, then wait.
- **Never invent an API.** If a Monkey C symbol cannot be confirmed in
  `<id>.api.debug.xml` or the SDK docs, say so and mark it an open question.
  This rule has already caught a real error (constraint 6 above).
- **Cite sources** — SDK file paths and API levels — in research and ADRs.
- **Prefer a working thin vertical slice** over broad scaffolding.
- **Flag scope cuts early** rather than silently building something smaller.
- If a user requirement turns out to be impossible or badly supported, say so
  directly, explain why, and propose the closest achievable alternative. This has
  already happened three times (tap on fr955, on-device config scope, filled arcs).
- **A guard nobody has watched fail is not a guard.** Drive every new
  diagnostic red against violating input before believing it — and cut the
  whole path, not one branch, or a second branch quietly answers instead and
  a passing test suite means nothing about the fix.
- **The bar for a real build is warning-free, not merely successful.** A
  `monkeyc` run that exits 0 with a warning still failed this project's own
  standard; `wfb/build.py` turns each `WARNING:` line into a diagnostic
  specifically so this is checkable in an assertion, not eyeballed.
- **The obvious test can fail to exercise the thing it is meant to test.**
  `"00:00"` vs `"11:11"` cannot detect a broken monospace-font implementation,
  because Open Sans's figures are already tabular — every digit the same
  width regardless of monospacing. The pair that actually drives it is
  `Fri 11:11` / `Wed 00:00`. When a test can pass against a knowingly-broken
  implementation, it is testing the wrong contrast.
- **"Over-estimating a box is safe" does not transfer** from a bounded
  quantity (a digit count) to an unbounded, localised device string (a
  complication's own label/unit text) — padding for the former produced a
  spurious geometry error on an ordinary design using the latter.
- **When a feature has a truthiness-based on/off switch, adding a
  differently-shaped member to it is the bug to look for.** (`bool(face.
  config)` gated the entire configuration feature in nine places across
  three modules; adding an axis that was not a `ConfigColor` would have
  silently produced no `<watchface-config>` for a design using only the new
  axis, had it not been routed through one shared `Face.has_config` first.)
- **Parallel work in one shared tree must edit files, never run git commands
  that touch the working tree.** `git stash`/`git reset` are repo-wide and
  ignore file ownership; one has already wiped another agent's in-flight
  edits here. Disjoint file ownership is what makes parallelism safe, and a
  stash discards that guarantee for everyone, not just the agent running it.
- **A subagent working in this tree does the work itself and does not spawn
  further helpers.** Two "research-only" subagents once wrote code
  concurrently into the same file and left it holding two conflicting
  definitions. Spawning discards the same disjoint-ownership guarantee one
  level up.

### Documentation discipline

Prose is part of the deliverable. When a change makes any of these stale, update
it **in the same commit**: `docs/research/*`, `docs/adr/*`, this file,
`docs/history.md` (append new session accounts there, not here), and
(once they exist) `README.md`, `docs/limitations.md`, and the format reference.

`docs/limitations.md` exists and is current. It records: no filled arc; the
four-axis / four-configuration on-device config cap; the fr955 exclusions;
single-colour bitmap fonts; no alpha blending; the 64-colour palette rule; what
is not implemented yet; and — separately — **what the linter does not check**,
including the two checks (memory and the partial-update budget) that are
deliberately not allowed to sound exact.

`docs/format.md` is the author-facing format reference. Keep it and the JSON
Schema in step: the schema is normative, the prose explains why.
