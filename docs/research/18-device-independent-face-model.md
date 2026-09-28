# 18 — A device-independent face model

**Question.** Garmin watch faces run on screens of several shapes (mostly
round), three display technologies with very different colour depths, and 17
resolutions. What set of abstractions and properties lets one face description
target all of them? The face is built from drawables (text, primitives,
images, hands, ranges, groups, and a composite *data widget* of one to three
parts bound to a metric), a conditional language that can hide, show, or
change the colour, shape or font of an element, several layouts, and data
slots the wearer changes individually.

**Status:** research. This is a reference model to measure `wfb` against,
not a plan. §3–§12 give the model. §13 maps it onto what `wfb` already
builds. §14 lists the gaps that would each need a plan and a user decision.
Every fleet or platform claim is marked **VERIFIED** (the device database
`data/devices/*.json`, the installed device files, the SDK, or the code at
the cited path) or **UNVERIFIED**.

---

## 1. The fleet, measured

Across the 136 face-capable devices in `data/devices/*.json` (VERIFIED; the
normalised fields come from `$CIQ_SDK/doc/docs/Device_Reference/<id>.html`):

| Axis | Distribution |
|---|---|
| Screen shape | round 115, rectangle 9, semi-octagon 8, semi-round 4 |
| Colours | 64: 67 · 65 536: 49 · 14: 9 · 2: 8 · 8: 3 |
| Shape × colours | round/64: 64 · round/65 536: 44 · semi-octagon/2: 8 · rectangle/65 536: 5 · round/14: 4 · semi-round/14: 4 · round/8: 3 · rectangle/64: 3 · rectangle/14: 1 |
| Resolution | 17 distinct sizes, from 148×205 to 454×454 and 448×486. The most common are 240×240 (38), 390×390 (20), 260×260 (13) and 454×454 (12) |
| Touch | 74 of 136 |
| Watch-face memory | per device, 49 152 B to 131 072 B (constraint 2) |

The fleet's colour depths are **2, 8, 14, 64 and 65 536**, not a 2/4/16/64
ladder (VERIFIED). The 14- and 8-colour panels have no documented palette
rule (`wfb/palette.py` module docstring; research 16 §5).

In the installed device files, `compiler.json` carries `displayType`
(`mip`, `amoled`, `lcd`), `bitsPerPixel`, `pixelFormat` (for example
`ARGB2222` on `fr955`), `resolution`, `deviceFamily`,
`alphaBlendingSupport: false` and the per-app-type memory limits.
`simulator.json`'s `display` carries `shape`, `isTouch` and `location` (the
panel's rectangle inside the skin PNG) (VERIFIED, `vendor/devices/fr955/`).
No device file is a mask as such. The visible area is the skin PNG's alpha
inside `display.location` (research 16 §3, VERIFIED).

## 2. Three principles

1. **Target capabilities, not device names.** Every rule is phrased as a
   question to the device profile (§3), such as "how many colours?", "is the
   screen round?" or "does it have `WatchFaceDelegate.onPress`?". A device
   id is the last-resort escape hatch (ADR 0004 §4 already says this about
   overrides).
2. **Separate build-time conditions from runtime conditions.** Shape,
   colour count, resolution and API availability are known when the face is
   built, so a condition on them is evaluated then and the unused branch is
   never emitted. Only data, power mode, wearer configuration and time reach
   the watch. On a device with a 49 152 B limit, emitting every branch
   decides whether the face fits.
3. **Absence is a normal value.** Every reading may be null (constraint 8),
   every metric may be missing on a device (ADR 0005, 2026-09-15 amendment),
   and every history may be empty. Every binding declares what to draw
   instead.

## 3. Device profile

The profile is read from the device files and never hardcoded:

```
DeviceProfile
├─ Screen    width, height, shape: round | rectangle | semi-octagon | semi-round
│            visible_mask (row spans from the skin alpha), safe_rect, inscribed_circle
│            subscreens: [ {shape: circle, box} ]          (Instinct window)
├─ Display   tech: mip | amoled | lcd, bits_per_pixel, pixel_format
│            palette: an exact list | truecolor, colour_count (derived)
│            alpha_blending: false
├─ Power     partial_update: bool (MIP), aod: {lit-pixel limit, shift} (AMOLED)
├─ Budget    watchface_memory, graphics_pool (constraint 11)
├─ Input     touch, hold (constraint 6c: a live face gets touch and hold only)
├─ Api       symbol table from <id>.api.debug.xml → has(qualified symbol)
├─ Config    native editor (4 axes) | generated settings menu | none
└─ Fonts     system-font metrics, vector-font availability (research 10, 12)
```

The two derived properties most rules depend on are the **colour class**
(§5) and the **visible mask** (§4).

## 4. Geometry

- **Units:** pixels, a fraction of the width, the height or the shorter side,
  and polar coordinates (angle and radius from the centre). Every length
  resolves to whole pixels per device at build time, with an optional 1 px
  floor so thin strokes never vanish.
- **Anchors:** the screen centre and edges, the safe rectangle's edges, and
  a subscreen. A group gives its children a local frame of reference.
- **Fitting that knows the shape:** on a round screen, the usable width at
  height *y* is the chord at *y*, not the screen width. Text overflow, the
  safe-area check and clipping are all tested against the mask's row spans.
  One rule then covers every shape: the skin mask for non-round screens and
  the analytic circle for round ones (`wfb/visible_area.py`, VERIFIED).

## 5. Colour

Elements name **semantic roles** (`fg`, `bg`, `accent`, `data`, `warn`),
never literal colours. Each role resolves per colour class:

```yaml
palette:
  accent: { default: "#FF5500", mono: "#FFFFFF" }
  warn:   { default: "#FF0000", "colors<=14": "#FFFFFF" }
```

| Class | Rule |
|---|---|
| 65 536 | the colour passes through |
| 64 | each channel snaps to `00`/`55`/`AA`/`FF`; anything else dithers (constraint 13) |
| 14, 8 | an explicit variant is required. There is no known snap rule (UNVERIFIED which colours are exact) |
| 2 | an explicit variant, otherwise black or white chosen by luminance (`wfb/palette.py`) |

An image gets one variant per class, reduced to the palette at build time.
AMOLED adds a black background and the always-on sleep-frame rules
(constraint 5, research 11).

## 6. Power modes

The modes are `awake`, `asleep` (MIP: a full redraw once a minute plus an
optional per-second partial update inside a clip-area budget, constraint 4)
and `aod` (AMOLED: a lit-pixel limit and burn-in shifting, research 11 and
15). Which modes a device has is known at build time. Each element therefore
declares, per mode, whether it is shown and which properties it overrides.
The compiler can then route every per-second element into the partial-update
path and check that path's budget statically.

## 7. Metric catalogue

The typed catalogue is the centre of the model:

```
Metric
  id, value_type: number | percent | duration | time | enum | string
  unit, default format, default icon, label
  range:   none | fixed (0..100) | goal (a dynamic maximum)  → can drive a gauge
  history: none | {series, window, resolution}               → can drive a graph
  complication_type?                                         → can fill a native Data slot
  permission?, requires: [qualified API symbols]             → availability per device
```

A runtime reading is `{value?, min?, max?, goal?, history[]?}`. Every field
is nullable.

**Filtering by property** is how slot choices are declared:

```yaml
choices: { history: true }            # metrics that can draw a graph
choices: { range: true, not: [weather.*] }
```

A filter is evaluated per device, so on a watch missing an API the offered
list shrinks without the author doing anything.

**History is narrow on a face.** `wfb/series.py` knows 15 series in four
families: heart rate, `ActivityMonitor.getHistory` (steps, calories,
distance, floors, active minutes), and the hourly and daily forecasts
(VERIFIED). Stress, Body Battery, pulse ox, elevation, pressure and all
solar values have **no** series a face can read: `SensorHistory` is closed
to faces, and solar has no history API (constraint 14b, research 08 §1). A
`history: true` filter therefore keeps roughly a dozen metrics.

**A wearer-chosen complication has no history of its own.** The native Data
axis binds a *complication type* at runtime (constraint 9b). A graph part on
a wearer-chosen slot therefore needs a compile-time map from complication
type to series (for example heart rate → `heart_rate`, steps → `steps`),
and the graph code for every mapped series has to be compiled in, because
the choice is only made on the watch. The map is the model's own idea. No
such table exists in `wfb` today (VERIFIED by search of `wfb/complications.py`
and `wfb/series.py`).

## 8. Conditional language

A small typed expression language that treats null as normal and compiles
to Monkey C, with no evaluator on the watch (ADR 0005 §2).

- **Types:** number, boolean, string, colour, font, enum, time, duration.
- **Operators:** arithmetic, comparison, `and`/`or`/`not`, a ternary, a
  null-coalescing default, `between`, `in`, and a first-match rule list.
- **Scopes, split by when they are evaluated:**

  | Evaluated | Scope |
  |---|---|
  | on the watch | data readings, `time.*`, wearer configuration (style, slot bindings), power mode |
  | at build time | the target profile: shape, colour count, touch, `has("Toybox.…")`, resolution |

  **The name `device.*` is already taken** by runtime status readings
  (`device.is_24_hour`, `device.phone_connected`, … in `wfb/catalog.py`,
  VERIFIED). A build-time profile scope needs a different name, such as
  `target.*`.

Any property may be a constant, an expression, or a rule list:

```yaml
color:
  - when: system.battery < 15  → palette.warn
  - when: mode == aod          → palette.dim
  - else:                        palette.fg
visible: heart_rate.current != null and mode != aod
font: { case: target.colors, 2: small_mono, else: big }
```

The compiler reads the dependencies of each expression. Build-time inputs
are folded away before code generation. Runtime inputs decide how often the
element must redraw and whether it can be cached as `static:`.

## 9. Drawables

Every drawable has the same base properties: `id`, `at`, a box,
`align`/`vertical_align`, `visible`, `color`, per-mode overrides, `z`, and
`on_hold`.

| Kind | Its own properties |
|---|---|
| text | template, format, font, overflow (`shrink` \| `clip` \| `ellipsis`), text on a curve |
| shape | line, rectangle, circle, arc, polygon; stroke or fill; antialiasing |
| image | one variant per colour class, reduced to the palette |
| hand | hour/minute/second, pivot, geometry built from shapes; the second hand hides while asleep |
| range | value/min/max drawn as an arc, bar, segments, needle or ticks |
| pattern | one template repeated along a circle or a line (ticks, numerals) |
| graph | a series drawn as a line, area or bars; window; normalisation |
| group | a local frame; its children move and show/hide together |

## 10. The data widget

A widget is a group bound to one slot, with one to three **parts** drawn
from `icon | value | label | graph | gauge`:

```yaml
widget:
  slot: left
  parts: [icon, value, graph]
  arrange: row                       # presets: stack, row, icon-left, along-arc
  place:                             # or free placement, relative to a sibling
    value: { right_of: icon, gap: 2 }
    graph: { below: value }
  requires: { graph: history, gauge: range }
  fallback: { graph: gauge, gauge: none }
  template: "{value}{unit}"
```

Whether a part is drawn depends on what the bound metric supports (§7). If
the wearer changes the slot's metric, parts appear or disappear and the
widget re-flows. Because the binding is a runtime choice (§8), the re-flow
happens on the watch: the compiler emits one layout per combination of
eligible parts, which is at most 2³ = 8 per widget and usually 2.

## 11. Slots, layouts and styles

- **Slot:** a named configuration point with a default metric, a choices
  filter, and the widget that draws it.
- **Layout:** positions for slots and elements. A slot keeps its identity
  across layouts, so the wearer's binding survives a change of layout.
- **Style:** a (layout, colour scheme) pair offered to the wearer by name.
  This is how layouts and colours share the one Styles axis
  (constraint 9c).
- **Configuration surface:** the model doesn't know which one is in use.
  The same slots, styles and colours map onto the native four-axis editor,
  the generated `getSettingsView` menu, or nothing (defaults only),
  according to the profile (§3).

## 12. Per-device overrides, and build-time checks

Overrides select by capability first and by device id last, and deep-merge
into the element:

```yaml
overrides:
  "shape:rectangle":  { layout: grid }
  "colors:2":         { palette: mono }
  instinct2:          { at: { anchor: subscreen } }
```

The build checks each device:

- text overflowing the chord at its height;
- anything outside the mask;
- colours that would dither;
- memory, measured with `monkeyc --build-stats` rather than estimated
  (ADR 0008);
- the partial-update time budget;
- the AOD lit-pixel limit and burn-in;
- an expression using a metric or symbol the device lacks;
- a slot choice that is ineligible on some device.

## 13. Against `wfb` today

| Model concept | In `wfb` | Where |
|---|---|---|
| Device profile read from files | built | `wfb/devices.py`, `wfb/availability.py` |
| Visible mask, subscreen | built | `wfb/visible_area.py`, `anchor: subscreen` (plan 20) |
| Relative and polar units, anchors | built | ADR 0004 §2, `wfb/units.py`, `wfb/layout.py` |
| Semantic palette, 64-colour and 2-colour snapping | built (the snap is a lint and a preview, not a per-class variant syntax) | `wfb/palette.py` |
| Palette variants per colour class | **missing**; closest is `overrides:` with `colors:` (not built) | §5 |
| Power modes per element | built: `modes:`, `aod:` blocks | ADR 0006 §5 |
| Typed catalogue, null handling | built | `wfb/catalog.py`, ADR 0005 §1, §3 |
| Metric `range`/`history` as filterable properties | **missing**; series are a separate table, not properties of a source | `wfb/series.py` |
| Slot choices by filter | partial: `choices: any` or an explicit list | `docs/guide/configuration.md` |
| Expression language, `visible:`, colour expressions | built: ternary, `min`/`max`/`clamp`/`round`/`floor`/`abs`/`percent` | `wfb/expr.py` |
| Rule lists (`when:` … `else:`) | **missing**; nested ternaries only | §8 |
| Build-time `target.*` scope, folding | **missing**; only `overrides:` (not built) is planned for this | §8, plan 20 D1 |
| Drawables | built for all nine kinds but `image` (also `raw`) | `wfb/kinds/` |
| Data widget with eligible parts | partial: `complication_slot` draws icon + value (+ label); no graph or gauge part, no eligibility, no re-flow | `wfb/kinds/complication_slot.py` |
| Complication type → series map | **missing** | §7 |
| Slots, layouts, styles, both config surfaces | built | ADR 0006 §1, `docs/guide/styles-and-layouts.md` |
| Capability-keyed overrides | specified, **not built** (a build error today) | ADR 0004 §4, plan 20 slice 4 (D1) |
| Build-time checks | built, except the complication-choice eligibility check | `wfb/lint.py`, ADR 0008 |

## 14. What this does not answer

Each gap in §13 changes the format, so each needs a plan and a user decision
(root `CLAUDE.md` §7) before it is built:

1. **Capability-keyed overrides** (plan 20 D1). This is the smallest change
   and covers most of what the build-time scope of §8 would do.
2. **A build-time `target.*` expression scope**, as a finer-grained
   alternative or complement to (1). Open question: whether it is worth a
   second mechanism once overrides exist.
3. **Palette variants per colour class.** Open question: what is exact on the
   8- and 14-colour panels (UNVERIFIED; needs a probe on one of those
   devices' files, or a real watch).
4. **Metric properties (`range`, `history`) and filter-based `choices:`.**
5. **A graph/gauge part on a complication slot**, which depends on the
   complication-type → series map in §7. Open question: how much memory it
   costs to compile in every mapped series' acquisition code
   (UNVERIFIED; measure with `--build-stats`, constraint 2).
6. **`image` elements**, already on the not-implemented list
   (`docs/limitations.md` §2).
