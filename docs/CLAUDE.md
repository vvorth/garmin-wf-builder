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
| `plans/NN-*.md` | proposals written but not built; index `plans/README.md` | status at the top; record user decisions there; **delete once built**, and add a row to `plans/README.md`'s deleted-plans table: how to read it, no per-slice commits (`git log --grep "plan NN"` lists them) |
| `adr/NNNN-*.md` | accepted decisions; index in `adr/README.md` | amend with a dated note, never silently rewrite |

**Docs** are what is true now: what is implemented, and platform knowledge
learned along the way that a future session needs.

| Directory / file | What it is | Rule |
|---|---|---|
| `guide/*.md` | the author-facing guide and format reference, one chapter per feature | keep in step with `schema/`; the schema is normative, the prose explains why |
| `limitations.md` | platform/linter limits; §2 is the authoritative "not implemented" list | update in the same commit as the change |
| `lore/*.md` | durable facts moved out of the root `CLAUDE.md` | add new lore here, not to the root `CLAUDE.md` |
| `README.md`, `development.md`, `container.md` | the documentation hub, setup and layout, the Docker image | add a hub row when a chapter is added or renamed |

**What a doc may cite:**

| Where | Plans | Research (and probes) |
|---|---|---|
| `limitations.md`, `lore/*.md` | never | yes, as the evidence for a stated fact |
| code comments and docstrings (`ts/`, `runtime-lib/`, `tools/`) | never | only where the code does something surprising because the platform forces it (a `monkeyc` workaround, a measured firmware behaviour), so nobody "fixes" it back; never as a bare tag on a feature name |
| `guide/`, the schema, diagnostics (lint/error text), READMEs, example faces, every `CLAUDE.md` | never | never: point to the guide or `limitations.md` instead |

Wherever a research citation is allowed, the doc still states the fact in
its own words -- the citation is the evidence, not the explanation. A
reader must never have to open a plan or a research file to understand a
doc. Plans are never cited anywhere outside the records: no "plan 14 §4.3",
"slice 2", decision ids (D3, R2.1, A5), `docs/plans/` links or `git show`
of a deleted plan. Records may point at docs freely. `ts/test/doc-citations.test.ts`
fails on a plan citation outside the records and on a research citation
where none is allowed; decision ids it cannot tell from ordinary names, so
those are on the writer.

**House style:** state the current truth. When something is superseded,
rewrite it in place rather than adding a dated correction beside it; history
lives in git. ADRs are the exception: amend them with a dated note, because
they record when and why a decision changed.

**Same-commit rule** (root `CLAUDE.md` §7): a change that makes any of
research, ADRs, lore, the root `CLAUDE.md`, `limitations.md` or
`guide/`/schema stale updates them in the same commit.
