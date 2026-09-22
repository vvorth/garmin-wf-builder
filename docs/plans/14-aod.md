# 14 — `aod:`: always-on display as overrides on the one design

**Status:** accepted, 2026-09-22; not built. D1–D5 (§7) decided by the
user, 2026-09-22: every recommendation taken. It grew out of
`docs/research/11-always-on-display.md` §6, whose open question (does
`modes: [always_on]` change meaning, or does `aod:` sit alongside it?) this
plan answers with a third option: `aod:` **replaces** it (§7, D3).

The goal, in the user's words: AOD as a property that holds overrides for an
element, group, pattern or text, able to change visibility, colour, font,
thickness and, later, a jitter offset, with a face-wide default for
elements that say nothing.

---

## 1. What exists today, and what this replaces

Every fact here is from research 11 §3, re-checked 2026-09-22:

- `modes: [always_on]` is a **second element set you opt into**
  (`wfb/ir/builder.py`, default `("active",)`), drawn in `onUpdate` while
  `_sleeping` (`wfb/emit/monkeyc/view.py`). No example, fixture or user
  design uses it.
- Nothing varies an element's styling by mode.
- Nothing reads the AMOLED API or measures burn-in.
- `Device.is_amoled` gates exactly one check: the `partial-update` error.
- No AMOLED device is installed. `fenix847mm` and `fenix947mm` are vendored.
- Every element type already has an `overrides:` key (per-device overrides,
  reserved in the schema and rejected as not implemented). "A block holding
  a partial copy of the element's own properties" is therefore a shape the
  format already anticipates.
- The generated view is **one shared source across every target**. The
  jungle uses no per-device `excludeAnnotations`. Anything AMOLED-only must
  either be gated at runtime or introduce per-device source selection
  (§7, D1).

---

## 2. The format

### 2.1 Per element, per group

```yaml
aod: hide                          # shorthand: not drawn in AOD
aod: show                          # shorthand: drawn unchanged
aod:                               # override block: drawn, restyled
  color: "#555555"
  font: clock_thin
  thickness: 1
  filled: false
  visible: battery.level < 20
```

An override block **uses the element's own property names**, restricted to
a per-type allowlist (§2.3). The schema reuses each element's own property
`$ref`s, so there is no second vocabulary to learn, and an unknown or
disallowed key is a schema error reported on the author's line
(`wfb/validate.py`).

An empty block (`aod: {}`) means `show`.

### 2.2 Face level

```yaml
aod:                  # top-level, beside elements:
  default: hide       # hide | show — for elements whose ancestry says nothing
  dim: 0.4            # optional, AMOLED: scale every drawn colour's luminance
  jitter: 4           # reserved for slice 5; a friendly "not implemented" error until then
```

### 2.3 What may be overridden (v1 allowlist)

| Kind | Overridable |
|---|---|
| every kind | `visible` (an expression, conjoined with the element's own `visible:`) |
| `text` | `color`, `font`, `format` |
| `shape` | `color`, `thickness`, `filled` |
| `progress` | `color`, `track_color`, `thickness` |
| `icon` | `color` |
| `graph` | `color`, `thickness`, `bar_width` |
| `complication_slot` | `color`, `icon_color`, `font`, `format` |
| `hands` | `color`, `thickness` — applied to **every** part of every hand (§5.1) |
| `pattern` | `color`, `thickness`, `font` — applied to **every** part (§5.1) |
| `group` | anything a descendant allows; pushed down (§3) |

**Out of v1, on purpose:**
- **Geometry (`at`, `size`, `radius`):** moving things is jitter's job
  (slice 5). Per-element geometry would turn this back into "a second
  layout", which is what this plan exists to avoid.
- **Data bindings (`value:`, `series:`, `text:`):** they would change what
  the sleep frame reads, and so its cost.

`filled: false` deserves a note. Text can't be drawn as an outline
(research 11 §1.4), but a shape can. A solid bezel disc becomes a thin ring,
which is the AOD guidance applied to the largest lit areas a face usually
has.

`format:` also deserves one: dropping seconds (`"HH:mm:ss"` → `"HH:mm"`)
is free, since AOD redraws once a minute anyway.

---

## 3. Resolution: element > nearest ancestor > face default

Resolved in the builder, while the element list is still a tree, the same
way `Builder._push_visible` works, because a group emits no draw method:

1. An element's own `aod:` wins **key by key** over its ancestors'.
2. Otherwise the nearest ancestor group's `aod:` applies.
3. Otherwise the face's `aod.default`.

**Visibility follows `visible:`'s precedent, with one deliberate
asymmetry:**
- An explicit `aod: hide` on a group **hides the whole subtree**, and no
  descendant can undo it. This is the same as `visible:` conjoining.
- The face `default:` is *not* explicit. It fills only where nothing in
  the ancestry spoke, so `default: hide` plus one `aod: show` on the time
  gives the canonical "everything off but the time" AOD with one line.

The resolved result is stored on each `Element` as an `AodOverride | None`
(`None` = hidden in AOD), so later stages never re-walk the tree.

`dead-element`-style lint: an element that is hidden in AOD **and** has no
`active`-frame purpose is unaffected. An `aod:` override on an element whose
ancestor already hides it is **a warning** (`aod-unreachable`), since it
can never draw.

---

## 4. Codegen

### 4.1 When the AOD frame runs

`_aod` is true while the view is sleeping **on a burn-in device**. Two ways
to decide "burn-in device" (§7, D1):

- **Runtime:** `System.getDeviceSettings().requiresBurnInProtection`. It is
  present on all four devices checked in research 11 §2, but that must be
  confirmed per device by `has_symbol` (`wfb/availability.py`), never by API
  level.
- **Build time:** emit AOD code only when some target `is_amoled`. With a
  mixed target list, the runtime check above still does the per-device
  selection.

Either way, **a face whose targets are all MIP emits no AOD code at all**,
so the three verification builds stay byte-identical. That is a test (§6).

### 4.2 Per-element emission

Almost every override is a compile-time constant, so the default is an
inline ternary in the existing one-method-per-element shape
(`_emit_element_method`):

```monkeyc
dc.setColor(_aod ? 0x555555 : 0xFFFFFF, Graphics.COLOR_TRANSPARENT);
dc.setPenWidth(_aod ? 1 : 3);
```

The alternative is a second method per overridden element. Per ADR 0008,
the two are **measured with `--build-stats`, not assumed**, on a face with
many overrides. Hidden elements are skipped by the same branch that today
selects the `always_on` set.

### 4.3 Fonts

An AOD-only font is a second resource. It is loaded in `onEnterSleep` and
released (nulled) in `onExitSleep` so it doesn't sit in memory all the time.
Since API 4.0.0, loaded fonts live in the graphics pool (constraint 11), so
this should be cheap, but it is measured, not assumed. A vector
`face:` font is fetched with `getVectorFont` the same way, and keeps its
null check.

### 4.4 `static:` elements

A static element with an AOD override can't reuse the awake buffer. For v1
it **skips the buffer while `_aod`** and draws directly. A second buffer is
an optimisation for later, once measured.

### 4.5 `dim:`

`dim` scales the luminance of every colour the AOD frame draws. On AMOLED,
`alphaBlendingSupport` is true and `Dc.setStroke` takes `0xAARRGGBB`, so
there are two candidate implementations: pre-computed dimmed constants, or
alpha. Pre-computed constants work on any device and are the default. The
alpha route is **UNVERIFIED** until the burn-in lint (slice 4) shows the
meter counts the blended result. An explicit `color:` in an override is
**not** dimmed; it is the author's final word.

### 4.6 Palette and config colours

An override colour can name a colour role, the same as any `color:`, so it
follows `color_scheme:` and `config.colors` at runtime. The 64-colour
palette lint does **not** apply to AOD colours on an AMOLED-only target
(research 11 §3.7: 16 bpp); it does on a MIP one.

---

## 5. Hard cases

### 5.1 Hands and patterns: list-shaped styling

`hands.hour.parts[…]` and `pattern.parts[…]` are lists. Merging into a list
by index is fragile: reordering the parts silently re-targets the override.
v1 offers only the element-level keys in §2.3, applied **uniformly to every
part**. If per-part control proves necessary, the next step is **wholesale
list replacement** (`aod: {parts: [...]}`), never per-index patching.

The second hand is already awake-only, and stays so.

### 5.2 Jitter (slice 5, reserved now)

- Set at **face or group level only**. Per-element jitter would break
  relationships such as the hands' centre against the tick ring. A group
  moves as a unit.
- **A deterministic sequence keyed by minute of day**, capped at 4 px
  (Garmin's guidance, research 11 §1.3). Then
  `wfb preview --aod --minute N` renders any frame, and a heatmap is a sum
  over 1440 minutes, standing in for the simulator's burn-in tool, which
  is unreachable here (research 11 §1.5).
- **Works well with `static:`:** a static buffer blits at `(dx, dy)`, so
  shifting exactly the static elements Garmin says to shift is nearly free.
- Elsewhere, positions are `Layout.mc` constants, so an offset means
  `Layout.FOO_X + _aodDx` through every emitter (research 11 §6 E1). That
  mechanical diff is why this slice comes last.

Until then `jitter:` is accepted by the schema and rejected by the builder
with a friendly "not implemented" error, like per-device overrides.

---

## 6. Slices

Every slice is warning-free on the three verification targets **and** on
`fenix847mm`, with docs, guide and schema in the same commit.

| # | Slice | Done when |
|---|---|---|
| 0 | **Install an AMOLED target** (`tools/setup-env.sh` re-run for `fenix847mm`). Add an AMOLED example, `examples/features/aod/face.yaml` | it builds for `fenix847mm` today, with the `always_on` path unchanged |
| 1 | **Format + resolution:** schema, builder resolution (§3), remove `modes: [always_on]` (D3), `wfb preview --aod` | a resolution test drives each precedence rule red then green; `always_on` in `modes:` is a schema error with a message pointing at `aod:` |
| 2 | **Codegen:** `_aod` gate (§4.1), ternaries (§4.2), AOD fonts (§4.3), static bypass (§4.4) | an all-MIP face's generated source is byte-identical before and after; the AMOLED example builds and its `--build-stats` figure is recorded |
| 3 | **`dim:`** (§4.5) | preview shows the dimmed frame; explicit override colours are left alone |
| 4 | **Burn-in lint** (research 11 §6 D): lit-pixel and luminance fractions from the `--aod` render, per AMOLED target, reported per element | a face lighting >10% fails, one under passes, formula and confidence stated per ADR 0008 |
| 5 | **Jitter** (§5.2) | preview renders minute N with the expected offset; the static buffer blits offset |
| 6 | **`getDisplayMode` ladder** (research 11 §6 F): skip drawing on `DISPLAY_MODE_OFF` | guarded per device; MIP targets untouched |

Slice 4 is where the default in D2 is revisited.

---

## 7. Decisions (user, 2026-09-22: all recommendations accepted)

**D1: how is "burn-in device" decided?** Runtime
`requiresBurnInProtection` (one shared view, a branch per frame) or
build-time `is_amoled` (no code on all-MIP faces; mixed lists still need the
runtime check). **Decided: both** — build-time to emit nothing for
all-MIP faces, runtime to select within a mixed target list.

**D2: face default: `hide` or `show`?**
- `hide` is safe: an unconverted face lights nothing. Needs an
  `aod-empty` lint (AMOLED target, nothing drawn in AOD), since Garmin
  calls an absent AOD a defect (research 11 §1.3).
- `show` is friendly but can light 60% of the screen, and only the slice 4
  lint would catch it.
**Decided:** `hide` until slice 4 exists, then reconsider `show`
paired with `dim:`.

**D3: does `modes: [always_on]` go away?** **Decided: yes, removed
outright, no shim** (house style; nothing uses it). `modes:` then means only
MIP partial updates (`active`/`low_power`), and `aod:` owns the AMOLED sleep
frame. This answers research 11's open question with a third option: neither
"change its meaning" (A) nor "alongside" but "replace".

**D4: name: `aod:` or `always_on:`?** `aod` is short and widely known;
`always_on` matches the mode name that D3 removes. **Decided:
`aod:`.**

**D5: does `aod:` apply on MIP?** MIP's sleeping frame is an ordinary
once-a-minute update with no burn-in rule. **Decided: no, AMOLED
only** (it follows from D1). A MIP face's sleep frame stays exactly the
awake design.

---

## 8. What stays unproven after this plan

These carry over from research 11 §5:
- No AMOLED face has been run, on device or in the simulator.
- Garmin's luminance formula is unpublished.
- The 3-minute static-pixel rule can't be checked from one frame. Jitter
  is the mitigation, and the heatmap is only an approximation.
- Whether `onEnterSleep` and `DISPLAY_MODE_LOW_POWER` ever disagree.
