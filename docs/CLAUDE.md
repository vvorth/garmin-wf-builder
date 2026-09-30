# docs/

Loaded automatically when working under `docs/`. Prose here is part of the
deliverable: the user asked for readable reasoning, not just code.

## Records and docs are separate

**Records** are how the project got here. They carry history and may cite
each other -- a plan cites the research it builds on, an ADR the research
behind its decision:

| Directory | What it is | Rule |
|---|---|---|
| `research/NN-*.md` | investigations, with citations; index `research/00-summary.md` | cite SDK paths and API levels; mark every behavioural claim VERIFIED or UNVERIFIED |
| `research/probes/` | minimal Monkey C projects backing research claims | a claim about `monkeyc` is only as good as the probe that built it |
| `plans/NN-*.md` | proposals written but not built; index `plans/README.md` | status at the top; record user decisions there; **delete once built**, and add a row to `plans/README.md`'s deleted-plans table |
| `adr/NNNN-*.md` | accepted decisions; index in `adr/README.md` | amend with a dated note, never silently rewrite |

**Docs** are what is true now: what is implemented, and platform knowledge
learned along the way that a future session needs.

| Directory / file | What it is | Rule |
|---|---|---|
| `guide/*.md` | the author-facing guide and format reference, one chapter per feature | keep in step with `schema/`; the schema is normative, the prose explains why |
| `limitations.md` | platform/linter limits; §2 is the authoritative "not implemented" list | update in the same commit as the change |
| `lore/*.md` | durable facts moved out of the root `CLAUDE.md` | add new lore here, not to the root `CLAUDE.md` |
| `README.md`, `development.md`, `container.md` | the documentation hub, setup and layout, the Docker image | add a hub row when a chapter is added or renamed |

**Docs never cite plans or research.** No "plan 14 §4.3", "slice 2",
"research 11 §6", decision ids (D3, R2.1, A5), `docs/plans/` or
`docs/research/` links, or `git show` of a deleted plan. The same holds for
every `CLAUDE.md`, code comments, the schema and diagnostics. When a doc
needs a fact a plan or research established, it states the fact in its own
words, with the primary evidence inline where it matters: the SDK path, the
API level, the device and date it was measured on, or the probe that shows
it. A reader must never have to open a plan or a research file to
understand a doc. Records may point at docs; docs do not point back.

**One exception: a genuinely quirky implementation.** Where code or lore
does something that looks wrong or needlessly roundabout because the
platform forces it (a workaround for a `monkeyc` bug, a measured
firmware behaviour), the comment or lore entry may cite the research or
probe that proves it, so nobody "fixes" it back. It still states the
reason in one or two sentences itself; the citation is the evidence, not
the explanation. Plans are never cited, not even here.

**House style:** state the current truth. When something is superseded,
rewrite it in place rather than adding a dated correction beside it; history
lives in git. ADRs are the exception: amend them with a dated note, because
they record when and why a decision changed.

**Same-commit rule** (root `CLAUDE.md` §7): a change that makes any of
research, ADRs, lore, the root `CLAUDE.md`, `limitations.md` or
`guide/`/schema stale updates them in the same commit.
