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

## Consequences

- Golden-file tests must be kept per format major, so a 1.x compiler's output
  for a 1.0 document stays stable.
- The published JSON Schema is versioned by URL so editor autocomplete resolves
  the right one.
- The generated-catalogue dependency means the schema is partly *derived*, not
  purely hand-written — a strength for accuracy, but it makes SDK regeneration a
  release-blocking step.
