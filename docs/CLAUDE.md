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
| `format.md` | the author-facing format reference | keep in step with `schema/`; the schema is normative, the prose explains why |
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

**Same-commit rule** (root `CLAUDE.md` §7): a change that makes any of
research, ADRs, lore, the root `CLAUDE.md`, `limitations.md` or
`format.md`/schema stale updates them in the same commit.
