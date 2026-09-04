# ADR 0002 — Authoring interface: YAML canonical, GUI as a lossless editor

- **Status:** Accepted
- **Date:** 2026-09-04
- **Decides:** what an author edits, and what the single source of truth is.

## Context

The brief states a strong prior for a hybrid — text canonical, GUI bidirectional
— and asks it be argued for or against. Two Phase 0 findings bear directly:

- **Facer/WatchMaker/Pujie are GUI-first, and their file formats are
  consequently undocumented, unstable and non-diffable** (`04-prior-art.md` §2).
  The format becomes an implementation detail of the editor.
- **WFF is text-first (XML) with multiple editors on top** — Watch Face Studio,
  a Figma plugin, and hand editing — and that plurality is possible precisely
  because the format is specified independently of any tool.

An additional constraint the brief implies but does not state: the author here
is a developer who wants faces to be "AI-editable" and version-controllable.
That is only true if the format is the source of truth.

## Decision

**Hybrid, with the text format canonical — confirmed, not merely accepted.**

1. **YAML** is the authoring format, with a **published JSON Schema** as the
   normative definition.
2. The GUI (Phase 3.8) is a **bidirectional editor over that file**. It must
   round-trip losslessly: preserve key order, comments, anchors, and **any key it
   does not understand**.
3. Nothing may be expressible only through the GUI. Every GUI action maps to a
   documented change in the file.

### Why YAML over JSON, TOML, or a bespoke DSL

- **YAML** — comments (essential for a design file a human maintains), low
  syntactic noise, native nesting for a layer tree, and mature schema tooling.
  Round-tripping with comments preserved is a solved problem (`ruamel.yaml`).
  Its footguns (the Norway problem, tag surprises) are contained by validating
  against a strict schema on load and by quoting in everything we generate.
- **JSON** — no comments, noisy for hand-authoring. Good as an interchange and
  as the schema language; bad as the thing a human edits.
- **TOML** — excellent for flat config, awkward for a deeply nested layer tree
  with heterogeneous element types. Arrays of tables get unreadable fast at the
  nesting depth a watch face needs.
- **Bespoke DSL** — best possible ergonomics, but it costs a parser, a formatter,
  an error-reporting story, and editor support, and it forfeits the free
  autocomplete that a JSON Schema gives in VS Code today. Not worth it before the
  element model has stabilised. Revisit only if YAML proves genuinely limiting.

## Rationale for the hybrid

The GUI-first alternative fails on this project's own goals: a design that only
an editor can produce is not diffable, not reviewable, not scriptable, and not
AI-editable. The text-only alternative is viable but gives up the thing a visual
medium genuinely needs — direct manipulation and live preview against a device
frame.

The hybrid's real cost is the **round-trip guarantee**, which is the part
projects usually get wrong. Making it explicit and testable up front is what
makes the hybrid safe:

- Preserving unknown keys means an older GUI cannot silently destroy a newer
  file's features. This is a hard requirement, not a nicety.
- Round-tripping is verified by property-based tests: parse → serialise must be
  byte-identical for any valid document, and parse → GUI-edit → serialise must
  differ only in the edited region.

## Consequences

- The JSON Schema is a **shipped artefact**, published so the YAML language
  server gives autocomplete and inline validation out of the box (an explicit
  deliverable in the brief).
- The GUI cannot be built until the schema is stable, which reinforces the
  Phase 2/3 ordering — the editor is deliberately last.
- Errors must be reported with **file, line and column** from the YAML source,
  not against an internal IR, or the text-canonical promise is hollow in
  practice. This requires carrying source spans through parsing into the IR.
- Generated Monkey C is **build output, never edited by hand**. It is written to
  a build directory and is not the source of truth. (The escape hatch for
  hand-written Monkey C is a separate, explicit mechanism — see ADR 0007.)

## Open

- Whether the GUI is a local web app (browser canvas, Python server) or native.
  Deferred to Phase 3.8; the canonical-format decision makes it reversible, which
  is the point of taking this decision first.
