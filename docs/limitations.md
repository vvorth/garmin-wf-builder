# Limitations

Two different kinds of limit, kept apart on purpose:

1. **What the platform will not do.** These are not going to be fixed. Knowing
   them early is worth more than discovering them on a wrist.
2. **What this tool does not do yet.** Scope, not physics.

A third section records **what the linter does not check**, because a linter's
credibility rests on being clear about its own edges.

---

## 1. Platform limits

### There is no filled-arc primitive

No `fillArc`, `fillSector` or `drawSector` exists anywhere in the Connect IQ API.
A ring is `setPenWidth` plus `drawArc`, and nothing else.

Consequences, all of them permanent:

* thickness is a **pen width**, not an inner and outer radius;
* **cap style is not selectable** — you get whatever the firmware draws;
* **no gradient sweeps**, and no true annulus;
* `progress` with `style: arc` therefore does not offer `inner_radius` or
  `outer_radius`. Offering them would be a lie.

### 128 KB, and 28 devices that cannot run a watch face at all

A watch face gets **131 072 bytes** on all three targets — one sixth of the
786 432 bytes the same hardware gives a watch app. Of 164 documented devices,
**28 cannot run a watch face at all**.

The build reports measured usage per device. It is measured by
`monkeyc --build-stats`, not estimated — see §3 for what that figure does and
does not include.

### `onPartialUpdate` overrun is permanent

Exceeding the partial-update power budget calls `onPowerBudgetExceeded` and
**disables partial updates for the remainder of the app's lifecycle**. Nothing
re-enables them; the face falls back to once-a-minute updates until it is
restarted.

`setClip` is charged by **region area**: every pixel inside the clip counts as
modified whenever any of them does. A wide clip is expensive even when almost
nothing inside it changed.

### AMOLED forbids `onPartialUpdate` entirely

MIP and AMOLED are structurally different low-power paths, not a styling
difference. All three targets here are MIP; **74 of 164 devices are
AMOLED-class** and need the `always_on` path instead.

### Single-colour bitmap fonts

A custom font's PNG is a single-channel grayscale image, so a glyph has exactly
one colour, applied at draw time. Two-colour lettering requires two fonts drawn
on top of each other. Icons inherit this too: an icon element is a glyph from a
baked bitmap font (`wfb/icons.py`), so a two-tone icon is not possible without
splitting it into two overlaid glyphs, the same as two-colour text.

### The resource compiler's font `filter` cannot represent a codepoint above U+FFFF

`icon:` accepts any single character from the vendored Nerd Font directly, not
only the named catalogue entries, including codepoints above the Basic
Multilingual Plane — all of Material Design Icons' ~7,000 glyphs live up
there, and the catalogue now uses several of them (`heart`, `flame`, `alarm`,
`dnd`, `notification`, `battery`, `floors`, `distance`, `phone`).

The one real, reproduced problem: the generated `<font filter="...">`
resource attribute is parsed by the (Java) resource compiler as UTF-16 code
units, so a codepoint needing a surrogate pair splits into two halves that
match no real glyph, failing the build with "does not have characters in the
given filter". `wfb/emit/resources.py` works around this by omitting `filter`
entirely for any font that needs such a glyph — the `.fnt` file it points at
is already subsetted to exactly the right glyphs by this project's own font
baking, so `filter` was redundant protection for that font in the first place.
Confirmed against a real build (`BUILD SUCCESSFUL`) and in `wfb preview`,
not just compiled: a supplementary-plane glyph renders correctly.

### No alpha blending

`alphaBlendingSupport` is **false** on all three targets. There is no
transparency and no compositing; `COLOR_TRANSPARENT` as a background means "do
not paint the background", not "blend".

### 64 colours, and everything else dithers

Each channel must be `0x00`, `0x55`, `0xAA` or `0xFF`. Anything else is dithered
by the firmware and looks grainy at close range.

### On-device configuration: four axes, four configurations, and not on fr955

The native watch-face editor is **API 5.1.0, fēnix 8 and newer**, and exposes
exactly four axes: Styles, complication slots, **one** data colour and **one**
accent colour. At most **four saved configurations** per face. There is no
per-element colour editing and no arbitrary data rebinding.

**The Forerunner 955 is excluded from it entirely.** A design targeting all three
devices is configurable on the wrist on two of them. This is a consequence of the
chosen scope (native editor plus phone settings, no generated on-device menu),
not a defect — but it must never be a surprise.

### API level does not determine availability

`fr955` runs API **5.2.0**, above `onTap`'s documented "since" of **5.1.0**, and
still does not have `WatchFaceDelegate.onTap`. Availability is resolved against
each device's own `<id>.api.debug.xml`, never against `minApiLevel`. (`fr955`
*does* have `InputDelegate.onTap`, which is a different symbol — a bare grep is
not enough.)

### A missing permission fails silently

The API returns null and the element never appears, with no diagnostic anywhere.
This tool derives the permission set from the bindings so the failure cannot
happen; it is listed here because it is the single most surprising thing about
the platform.

### `onSettingsChanged` does not fire for on-watch edits

It fires only for Garmin Connect pushes. Any cached property must be invalidated
explicitly or an on-watch change silently does not take effect.

---

## 2. Not implemented yet

Phase 2 shipped a vertical slice. Present in the ADRs, absent from the code:

### Measured against a real face

`examples/dashboard/` is a deliberate attempt to reproduce the reference face in
`garmin-watchface-protomolecule` — the "can the schema express Dashboard?"
question ADR 0004 poses. It gets the row structure, the separators, the two-tone
clock, the conditional colours, the badge and the arcs. **Four things it cannot
express**, all for want of data sources rather than element types:

| Dashboard has | Blocked on |
|---|---|
| A weather row's *condition icon* | nothing -- `weather.condition`/`icon_for:` now express this |
| A weather row's temperature, precipitation chance, high/low | no source for these fields yet (the `slow` tier and `Weather.CurrentConditions`/`DailyForecast` reader both exist -- adding a field is a `wfb/catalog.py` entry, not new plumbing) |
| Body Battery, on the status row and the left arc | no `SensorHistory` sources |
| A configurable history graph — HR, Body Battery, stress, pressure, elevation | no graph element **and** no history sources |
| A daylight arc that drains between sunrise and sunset | no sunrise/sunset sources |

Weather's condition icon shipped (`icon_for: weather.condition`, resolved
on-device through `WfbWeather.mc`, mirroring `wfb.icons.
weather_icon_for_condition()`) -- see `docs/format.md`'s `icon_for` section.
The other weather fields, Body Battery and the daylight arc are all catalogue
work; the history graph additionally needs an element type that plots a
series, which is the strongest argument in the codebase for the `raw` escape
hatch: a sparkline is exactly the sort of thing that should drop to
hand-written Monkey C rather than growing the schema.

| Missing | Where it is specified |
|---|---|
| `image` and `complication_slot` elements | ADR 0004 |
| The `raw` escape hatch to hand-written Monkey C | ADR 0007 |
| Per-device `overrides` (parsed and validated, not yet applied) | ADR 0004 §4 |
| The `config:` block, on-device config, phone settings | ADR 0006 |
| Tap / hold interactivity | ADR 0006 §6 |
| `segments` and `scale` progress styles | ADR 0004 §1 |
| Complications, and the `event` refresh tier | ADR 0005 |
| `wfb install`, `package`, `migrate`; the GUI | brief, Phase 3 |
| Catalogue generation from the SDK (the table is hand-written for now) | ADR 0005 §1 |

The `slow` refresh tier and its TTL cache (ADR 0005 §5) **shipped** --
`weather.*` is its first real source; see `docs/format.md`'s "Data binding"
section and `WfbCache.mc`.

### Screen shapes

Only `round` and `rectangle` have safe-area geometry. `semi-round` and
`semi-octagon` are **unsupported targets rather than silently wrong ones**: the
geometry check reports "not checked" instead of guessing.

### The simulator does not run in a headless Linux container

`wfb simulate` works where the Connect IQ simulator does. It is a GUI
application, and on Linux it links against `libwebkit2gtk-4.0` and `libsoup-2.4`,
which current distributions no longer ship. Even with those libraries supplied,
the simulator **segfaults on app load under Xvfb with software OpenGL** — and it
does so with an unmodified SDK sample `.prg`, so this is an environment
limitation and not a property of generated faces.

`wfb preview` is the answer in that environment: it renders from the same
resolved geometry the generated code uses, so the two cannot disagree about
position. What it does *not* claim to reproduce is glyph rasterisation for system
fonts, arc cap shape, or the transflective panel's real appearance. For those the
simulator is authoritative.

---

## 3. What the linter does not check

The linter is this project's main claim to being better than hand-writing, so its
edges matter more than its coverage.

### Checks that are exact

Data-source spelling; per-device API availability; palette legality; geometry
against the framebuffer and the visible area (round and rectangle only); glyph
coverage of a subsetted font; refresh tiers; contrast arithmetic.

### Checks that are explicitly weaker, and say so in their own output

| Check | What it actually knows |
|---|---|
| **Memory** | *Measured*, not estimated — but the figure is the **static foreground** total from `monkeyc --build-stats`. Resources loaded at runtime (fonts, bitmaps) add to it and are **not** measured. A face near the limit needs checking on device. |
| **Partial-update power budget** | **A heuristic.** Garmin does not publish the numeric budget; the docs say only "strict limits". The check flags relative cost — clip area and operation count — and is labelled a heuristic until measured empirically against `onPowerBudgetExceeded`. |
| **Text overflow** | Exact for a baked custom font (real glyph advances from the TrueType source). A system font (`FONT_TINY` and so on) is **always an estimate** — Garmin publishes each `FONT_*` symbol's pixel *height* per device and language, but not its per-glyph advances, and the real typefaces (Pridi, Roboto Condensed, Bionic, ...) are not available on the host or in the SDK. The estimate scales a real scalable stand-in face to the device's published height and measures per character (`wfb/fonts/fallback.py`), which is why it needs that per-device height to be correct in the first place — a flat 0.55 em/character coefficient is a last-resort fallback used only if even that stand-in face fails to load. Every system-font measurement is labelled `(estimated)` in the generated code regardless. |
| **Contrast** | The arithmetic is exact WCAG; the 3.0 threshold is a judgement call, which is why it is a warning and is suppressible. |

### Not checked at all

* **Element overlap.** Two elements may be placed on top of each other with no
  complaint. Building `examples/dashboard/` ran into this repeatedly: a
  separator drawn through a row of text validates cleanly, and only the preview
  shows it. A dense design is where this gap is felt.
* **The rendered width of a computed value.** The overflow check knows the digit
  range of a bound *source* and now accounts for a constant scale factor
  (`activity.steps / 1000`), but not for arithmetic in general. A value derived
  by anything more involved is sized from its source's full range, which
  over-estimates.
* **Visual quality.** Nothing judges whether a design is legible or attractive.
* **AMOLED pixel and luminance ratios** (ADR 0008 check 8). Not implemented; the
  simulator's heat map is authoritative anyway.
* **`raw` element runtime allocation.** The escape hatch does not exist yet; when
  it does, its memory contribution will be compiled and therefore measured, but
  its *runtime* allocation will not be modelled.
* **Safe area on `semi-round` and `semi-octagon`.** Reported as "not checked".
* **Whether a device's firmware actually behaves as its files describe.** The
  device files are the best available ground truth, not a guarantee.
