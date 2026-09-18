# docs/

Loaded automatically when working under `docs/`. Prose here is part of the
deliverable: the user asked for readable reasoning, not just code.

| Directory / file | What it is | Rule |
|---|---|---|
| `research/NN-*.md` | investigations, with citations | cite SDK paths and API levels; mark every behavioural claim VERIFIED or UNVERIFIED |
| `research/probes/` | minimal Monkey C projects backing research claims | a claim about `monkeyc` is only as good as the probe that built it |
| `adr/NNNN-*.md` | accepted decisions; index in `adr/README.md` | amend with a dated note, never silently rewrite |
| `plans/NN-*.md` | proposals written but not built | status at the top; record a user decision there, keep the superseded analysis; **delete once built** (below) |
| `lore/*.md` | durable facts moved out of the root `CLAUDE.md` | add new lore here, not to the root `CLAUDE.md` |
| `format.md` | the author-facing format reference | keep in step with `schema/`; the schema is normative, the prose explains why |
| `limitations.md` | platform/linter limits; §2 is the authoritative "not implemented" list | update in the same commit as the change |
| `history.md` | the chronological session narrative | **append only**, at the end, under a dated heading; never re-inline it into `CLAUDE.md` |

**House style:** when an account is superseded, leave it in place and add the
correction beside it. The original reasoning is instructive. This applies to
research, ADRs, plans and history alike.

**Built plans are deleted.** Plans 01–03 were removed on 2026-09-14 once
built; what they decided now lives in `format.md`, the schema, ADR 0006 and
the code. Code and docs still cite them as `plan 02 §12.4`; read one with
`git show a645d64:docs/plans/02-style-layouts.md` (`01-background-color.md`,
`03-complication-slot-icons.md` likewise). Plan 04 (analog hands) was built
and deleted on 2026-09-14; read it as built with `git show
93ef6d7:docs/plans/04-analog-hands.md` (§13 is what shipped). Plan 05
(patterns) was built and deleted on 2026-09-14; read it as built with
`git show f9115ca:docs/plans/05-patterns.md`. Plan 06 (text parts in a
pattern, and `align:` on a group) was built and deleted on 2026-09-15; read
it with `git show f5155d7:docs/plans/06-pattern-text-and-group-align.md`.
Plan 07 (`align:`/`vertical_align:` as one placement rule on every element)
was built and deleted on 2026-09-15; read it with `git show
b534b8a:docs/plans/07-align-everywhere.md`. Plan 09 (real device typefaces
for system-font previews/measurement) and plan 10 (decoding Garmin `.cft`
bitmap fonts on top of that) were both built and deleted on 2026-09-18;
read them as built with `git show 7e8e11d:docs/plans/09-system-font-metrics.md`
and `git show 7e8e11d:docs/plans/10-cft-bitmap-fonts.md` (HEAD at the time
both were deleted contains both files, even though plan 10 was last edited
at `f38f41a` and plan 09 at `c7b2658`). What they decided now lives in
`docs/research/10-system-fonts.md`, `wfb/fonts/` and the code.

**Same-commit rule** (root `CLAUDE.md` §7): a change that makes any of
research, ADRs, lore, the root `CLAUDE.md`, `limitations.md` or
`format.md`/schema stale updates them in the same commit.
