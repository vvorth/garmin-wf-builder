# ADR 0009 — Schema versioning and forward compatibility

- **Status:** Accepted
- **Date:** 2026-09-04
- **Decides:** how the format evolves without breaking existing faces.

## Context

Two independent version axes exist and are routinely confused:

1. **The format version** — what our schema supports.
2. **The Connect IQ API level and device set** — what the *platform* supports.

WFF handles the second axis well: WFF 1/2/3/4 map to Wear OS 4/5/5.1/6, and the
reference marks every feature with the version that introduced it
(`04-prior-art.md` §1). That is worth copying. But WFF conflates its format
version with the platform version, which we cannot do — a Garmin feature is
gated by API level **and** by an explicit per-device list, and the two do not
move together (`onTap` is 5.1.0 but only 19–23 devices).

## Decision

### 1. Declared format version, semantic

```yaml
format: 1            # major only, in the document
```

- **Major** bumps only for breaking changes. A face declaring `format: 1` must
  keep compiling under a 1.x compiler forever.
- Additive changes do not bump the major. New optional keys with defaults that
  preserve existing behaviour are always additive.
- The compiler refuses a `format` newer than it understands, with a clear message
  naming the version needed — never a partial parse.

### 2. Unknown keys are an error in the compiler, preserved by the GUI

These are deliberately different rules for different tools:

- **Compiler:** an unrecognised key is an **error**. Silently ignoring a
  misspelled key is how a design quietly loses an element, and check 1 in
  ADR 0008 exists precisely to prevent that class of bug.
- **GUI:** must **preserve** unknown keys on round-trip (ADR 0002). An older
  editor must never destroy a newer file's content.

The apparent tension is intentional: the compiler is authoritative about what
compiles; the editor is a text transformer that must not lose data.

### 3. Platform capability is annotated per feature, not per format version

Every schema feature carries the API level and device predicate it requires,
sourced from the generated catalogue rather than hand-written:

```yaml
# schema metadata, not author-facing
on_activate.cycle:
  requires_any:
    - { symbol: WatchFaceDelegate.onTap,   since: "5.1.0" }
    - { symbol: WatchFaceDelegate.onPress, since: "4.2.0" }
```

This keeps ADR 0008 check 2 exact and means adding a Connect IQ feature does not
require a format major bump — it is a catalogue update plus an optional key.

### 4. SDK version is recorded, not pinned

The build records the SDK version used and warns when the device database was
generated from a different one. Faces are not pinned to an SDK; the catalogue is
regenerated per SDK release and drift is a CI check (ADR 0005).

### 5. Deprecation path

A deprecated key warns for one major version and is removed in the next, with
the warning naming the replacement. `wfb migrate` performs mechanical upgrades
and is expected to handle the common cases rather than all of them.

> **Superseded for the format 1 → 2 break (2026-09-29, plan 22):** see the
> amendment below. Format 1 was migrated, not kept for a major.

## Consequences

- Golden-file tests must be kept per format major, so a 1.x compiler's output
  for a 1.0 document stays stable.
- The published JSON Schema is versioned by URL so editor autocomplete resolves
  the right one.
- The generated-catalogue dependency means the schema is partly *derived*, not
  purely hand-written — a strength for accuracy, but it makes SDK regeneration a
  release-blocking step.

## Amendment (2026-09-29): format 2 is migrated, not deprecated

Plan 22 revised the format in one designed break: one colour namespace,
author-shaped names, one spelling per idea and a grouped top level
(`docs/guide/format-2-migration.md` lists every rename). §5's path -- a
deprecated key warning for a major, then removed -- was not used for it.
The user decided (F4) that `wfb migrate` rewrites a format 1 file once,
keeping its comments, key order and quoting, and that the compiler then
reads format 2 only: `format: 1` is an error naming the command, and a
format 1 key in a format 2 file is a schema error naming its replacement.

The reasons: nearly every key moved, so a face written against format 1
would have warned on most of its lines for a whole major; the migrator is
exact rather than best-effort, because format 2 is a front-end change
(`wfb/lower.py` rewrites it into the same internal shape, so a migrated face
generates the same Monkey C, byte for byte, apart from each file's header);
and there is one user, whose every face is in this repository. What the
migrator cannot rewrite faithfully it refuses, with the line and what to do
by hand, and writes nothing.

Consequences for this ADR: the schema is `schema/wfb-face-2.schema.json`
and the only one shipped; golden files were regenerated for format 2
(their header line is the only change); §2's unknown-key rule is unchanged.
Format 2 also reserves vocabulary for designed but unbuilt features, each a
friendly "not implemented" error rather than an unknown key, so building
one later is additive (`docs/limitations.md` §2).

## Amendment (2026-10-01): §4 built

The SDK version is recorded, not pinned. `tools/extract-device-reference.py`
writes the SDK release its pages came from to `.cache/device-reference/
sdk-version.txt` (from the SDK's `bin/version.txt`, or `--sdk-version` where
only the pages are kept, as in the Docker build), and `tools/setup-env.sh`
extracts again when it is missing. `wfb build` compares it with the SDK it
compiles with: a `sdk` warning when they differ, since font metrics and
palette sizes come from the reference, and a note when the reference
records no SDK. The build directory gets `build-info.json` naming both SDKs,
the devices and the `.prg`s; `wfb doctor` reports a mismatch. The
"device database" here is the extracted reference: the device definitions
themselves (`compiler.json`, `simulator.json`) carry no SDK version.
Catalogue regeneration and its CI drift check stay unbuilt (ADR 0005 §1).


## Amendment (2026-10-04): `wfb migrate` removed

The user decided to remove `wfb migrate` and its guide chapter once no
format 1 face was left to move: every example and fixture is format 2. The
compiler still reads format 2 only. `format: 1` is an error telling the
author to declare `format: 2`, after which each format 1 key is a schema
error naming its replacement (`wfb/validate.py`, `FORMAT_1_KEYS`), to
rewrite by hand. The migrator is in git history up to the commit that
removed it. At the same time the builder stopped reading an internal,
format 1-shaped document: it reads format 2's keys as written, and
`wfb/lower.py` only checks what the schema cannot.
