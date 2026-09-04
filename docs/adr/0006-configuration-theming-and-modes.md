# ADR 0006 — Configuration, theming, modes and interactivity

- **Status:** Accepted
- **Date:** 2026-09-04
- **Decides:** how an author declares user-editable properties, where those are
  edited, how palettes work, and how elements behave in low-power mode.

## Context

Phase 0 found the on-device story is much narrower than the brief assumes
(`02-features-feasibility.md` §6). The native watch-face editor is **API 5.1.0,
fēnix 8 and newer**, and exposes exactly four axes:

| Axis | Allows |
|---|---|
| Styles | enumerated author-defined variants, by number |
| Data | per-complication-slot type choice (or `allowAny`) |
| Data Colour | **one** colour, from a list or any |
| Accent Colour | **one** colour, from a list or any |

Maximum **four saved configurations** per face. There is no per-element colour
editing and no arbitrary data rebinding.

**User decision (2026-09-04):** target the **native editor plus phone-side
settings only**. No generated on-device settings menu.

**User decision (2026-09-04):** interaction is **tap where available, hold on
fr955** — the compiler generates both paths from one declaration.

## Decision

### 1. Three declared config surfaces, one declaration

An author declares a property once and states where it may be edited. The
compiler emits the right artefact for each surface and **fails the build if a
surface is unavailable on a targeted device** rather than silently dropping it.

```yaml
config:
  accent:
    type: color
    default: "#FF8000"
    edit: [device_native, phone]     # -> <accentColors>, and settings.xml
  data_color:
    type: color
    default: "#FFFFFF"
    choices: ["#FFFFFF", "#00FFFF", "#FFFF00"]
    edit: [device_native, phone]     # -> <dataColors>
  slot1:
    type: complication
    allow: [steps, heart_rate, current_weather]
    edit: [device_native, phone]     # -> <data><complication>
  show_seconds:
    type: bool
    default: true
    edit: [phone]                    # -> settings.xml only
```

Emitted artefacts:

- `edit: device_native` → the `<watchface-config>` resource, read at runtime with
  `WatchFaceConfig.getSettings(null)`, plus the `onWatchFaceConfigEdited` and
  `setSelectedComplication` wiring.
- `edit: phone` → `resources/settings/settings.xml` + `properties.xml`, pushed
  via Garmin Connect.

**Enforced constraints**, checked at build time so they cannot be discovered on
the wrist:

- At most **one** `color` property may be `device_native` as the data colour, and
  at most one as the accent colour. Declaring a third is a build error naming the
  four-axis limitation.
- `device_native` on a target below API 5.1.0 is a build error, with the
  offending device named.
- Non-complication data properties cannot be `device_native`.

### 2. fr955 has no on-device configuration — stated plainly

This follows directly from the chosen scope. The fēnix 8 Solar pair get the
native editor; **the fr955 gets phone-side settings only**, because it is
excluded from the 5.1.0 editor entirely. A design targeting all three is
therefore configurable on the wrist on two of three devices.

This is a consequence of the decision, not a defect, but it must appear in
`docs/limitations.md` and in the build output, so it is never a surprise. The
generated-on-device-menu option that would have covered fr955 was considered and
declined; if that changes, it slots in as a fourth `edit` surface without
disturbing the declaration format.

### 3. Property caching and invalidation

`onSettingsChanged` fires **only** for Garmin Connect pushes, not for on-watch
edits. Any code path that writes a property must explicitly invalidate the cache
or the change silently does not take effect — a trap the sibling Dashboard
project documents from experience.

The generated runtime therefore owns property caching centrally and invalidates
on: `onSettingsChanged`, `onWatchFaceConfigEdited`, and any internal write
(e.g. a tap cycling a slot). Authors never touch this.

### 4. Theming

Palettes are named and resolved at build time:

```yaml
palette:
  bg: "#000000"
  text: "#FFFFFF"
  hot: "#FF5500"
  accent: config.accent          # a runtime-configurable entry
```

Entries resolving to literals become Monkey C constants. Entries bound to config
are read at runtime. Elements reference `palette.hot`, never a raw hex value.

**Palette legality is linted** (Phase 1.4): on a 64-colour device each channel
must be one of `0x00/0x55/0xAA/0xFF`, or the firmware dithers it and it looks
grainy. The linter warns with the nearest legal colour, and an explicit
`allow_dither: true` silences it for a deliberate choice.

### 5. Modes — active, low power, always-on

Because AMOLED forbids `onPartialUpdate` entirely while MIP depends on it
(`01-platform-capabilities.md` §4), mode is a structural property of the IR, not
styling.

```yaml
- id: seconds
  type: text
  value: time.second
  modes: [active, low_power]     # omitted from always_on
```

Modes: `active` (high power, `onUpdate` each second), `low_power` (MIP,
`onPartialUpdate` each second), `always_on` (AMOLED burn-in-constrained).
Default is `[active]` for anything not explicitly marked.

The compiler derives from this:

- the tight `setClip` rectangle around all `low_power` elements — computed from
  resolved geometry and font metrics, and the reason clip cost (charged by
  region area) can be minimised automatically;
- whether a `BufferedBitmap` background is worth pre-rendering in `onUpdate` —
  and this is cheaper than feared: `graphicsResourcePoolSize` is **1 MB on all
  three targets**, a budget separate from the 128 KB watch-face limit
  (`05-device-files.md` §4);
- the AMOLED pixel/luminance estimate for `always_on` (Phase 1.4);
- an error if a `low_power` element reads a non-`frame`-tier source (ADR 0005).

### 6. Interactivity

Declared per element, compiled to whichever mechanism the target supports:

```yaml
- id: slot1
  type: complication_slot
  cycle: [steps, heart_rate, body_battery]
  on_activate: cycle             # tap where available, else hold
  on_hold: launch                # Complications.exitTo()
```

Per the decision, `on_activate: cycle` generates:

- **`onTap`** on devices in the 5.1.0 tap set (both fēnix 8 Solar targets);
- **`onPress`** on devices with 4.2.0 hold but no tap (**fr955**);
- nothing, with a build warning, on devices with neither.

Hit regions are generated from resolved element geometry — the compiler already
knows every bounding box, so the hit-test table costs the author nothing. The
selected slot persists in `Application.Storage` and survives restarts.

Note `on_hold: launch` and hold-to-cycle **conflict on fr955**, where hold is the
activation gesture. The compiler must reject that combination for a device where
both map to `onPress`, rather than silently preferring one.

## Consequences

- One declaration drives up to three generated artefacts; they cannot drift.
- Several genuine platform limits become build errors instead of wrist
  surprises — the four-axis cap, the API-level gate, the hold-gesture conflict.
- `docs/limitations.md` must state the four-axis cap, the four-configuration
  cap, and the fr955 exclusion.

## Open

- Whether `Styles` (the enumerated-variant axis) is worth exposing in v1. It maps
  naturally onto "the same design with a different palette", but interacts with
  per-device overrides in ways not yet thought through. Deferred.
