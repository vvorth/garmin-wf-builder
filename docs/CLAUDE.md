# docs/

Loaded automatically when working under `docs/`. Prose here is part of the
deliverable: the user asked for readable reasoning, not just code.

| Directory / file | What it is | Rule |
|---|---|---|
| `research/NN-*.md` | investigations, with citations | cite SDK paths and API levels; mark every behavioural claim VERIFIED or UNVERIFIED |
| `research/probes/` | minimal Monkey C projects backing research claims | a claim about `monkeyc` is only as good as the probe that built it |
| `adr/NNNN-*.md` | accepted decisions; index in `adr/README.md` | amend with a dated note, never silently rewrite |
| `plans/NN-*.md` | proposals written but not built | status at the top; record user decisions there; **delete once built** (below) |
| `lore/*.md` | durable facts moved out of the root `CLAUDE.md` | add new lore here, not to the root `CLAUDE.md` |
| `README.md` | the documentation hub: the guide's table of contents, then everything else | add a row when a chapter is added or renamed |
| `guide/*.md` | the author-facing guide and format reference, one chapter per feature | keep in step with `schema/`; the schema is normative, the prose explains why |
| `limitations.md` | platform/linter limits; §2 is the authoritative "not implemented" list | update in the same commit as the change |

**House style:** state the current truth. When something is superseded,
rewrite it in place rather than adding a dated correction beside it; history
lives in git. ADRs are the exception: amend them with a dated note, because
they record when and why a decision changed.

**Built plans are deleted.** Code and docs still cite them (`plan 02
§12.4`). To read one as built:

| Plans | Read with |
|---|---|
| 01–03 | `git show a645d64:docs/plans/02-style-layouts.md` (`01-background-color.md` and `03-complication-slot-icons.md` likewise) |
| 04 analog hands | `git show 93ef6d7:docs/plans/04-analog-hands.md` (§13 is what shipped) |
| 05 patterns | `git show f9115ca:docs/plans/05-patterns.md` |
| 06 pattern text, group align | `git show f5155d7:docs/plans/06-pattern-text-and-group-align.md` |
| 07 align everywhere | `git show b534b8a:docs/plans/07-align-everywhere.md` |
| 09 system fonts, 10 `.cft` | `git show 7e8e11d:docs/plans/09-system-font-metrics.md`, `…/10-cft-bitmap-fonts.md` |
| 11 vector fonts, `curve:` | `git show 35217d1:docs/plans/11-vector-text.md` (§5 "Slices" is what shipped; slice 1 is `e744913`, slice 2 `35217d1`, slice 3 the example/screenshots) |
| 12 preview font fidelity | `git show 28638ca:docs/plans/12-preview-font-fidelity.md` (§1 is the measured diagnosis — read it before re-investigating "the preview's typeface is wrong"; slice 1 R1/R3 is `28638ca`, slice 2 R2 the commit after it) |
| 13 showcase `roman` layout | `git show 28638ca:docs/plans/13-showcase-roman-layout.md` (as proposed; built with two deliberate departures recorded in `examples/showcase/face.yaml`'s own comments — `skip: [2, 10]` because the shared registers sit on those spokes, and both apertures on `FONT_XTINY` so each is wider than tall) |
| 15 `outline:`, the stamped ring | `git show e31117b:docs/plans/15-text-outline.md` (§14 "Slices" is what shipped; slice 1 is `0cebdf0` (amended by `65b8f2a`), slice 2 `e31117b`, slice 3 the example/screenshots/doc-sweep, commit `<PLAN15_SLICE3_COMMIT>` — placeholder: substitute the hash of the commit that deletes this file, which this row cannot know at the time it is written) |

**Same-commit rule** (root `CLAUDE.md` §7): a change that makes any of
research, ADRs, lore, the root `CLAUDE.md`, `limitations.md` or
`guide/`/schema stale updates them in the same commit.
