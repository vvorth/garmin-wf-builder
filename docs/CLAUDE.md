# docs/

Loaded automatically when working under `docs/`. Prose here is part of the
deliverable: the user asked for readable reasoning, not just code.

| Directory / file | What it is | Rule |
|---|---|---|
| `research/NN-*.md` | investigations, with citations | cite SDK paths and API levels; mark every behavioural claim VERIFIED or UNVERIFIED |
| `research/probes/` | minimal Monkey C projects backing research claims | a claim about `monkeyc` is only as good as the probe that built it |
| `adr/NNNN-*.md` | accepted decisions; index in `adr/README.md` | amend with a dated note, never silently rewrite |
| `plans/NN-*.md` | proposals written but not built | status at the top; record a user decision there, keep the superseded analysis |
| `lore/*.md` | durable facts moved out of the root `CLAUDE.md` | add new lore here, not to the root `CLAUDE.md` |
| `format.md` | the author-facing format reference | keep in step with `schema/`; the schema is normative, the prose explains why |
| `limitations.md` | platform/linter limits; §2 is the authoritative "not implemented" list | update in the same commit as the change |
| `history.md` | the chronological session narrative | **append only**, at the end, under a dated heading; never re-inline it into `CLAUDE.md` |

**House style:** when an account is superseded, leave it in place and add the
correction beside it. The original reasoning is instructive. This applies to
research, ADRs, plans and history alike.

**Same-commit rule** (root `CLAUDE.md` §7): a change that makes any of
research, ADRs, lore, the root `CLAUDE.md`, `limitations.md` or
`format.md`/schema stale updates them in the same commit.
