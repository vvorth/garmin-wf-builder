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
93ef6d7:docs/plans/04-analog-hands.md` (§13 is what shipped).

**Same-commit rule** (root `CLAUDE.md` §7): a change that makes any of
research, ADRs, lore, the root `CLAUDE.md`, `limitations.md` or
`format.md`/schema stale updates them in the same commit.
