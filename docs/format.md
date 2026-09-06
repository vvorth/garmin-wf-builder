# The wfb design format — reference (format 1)

The normative definition is [`schema/wfb-face-1.schema.json`](../schema/wfb-face-1.schema.json).
This page explains the parts the schema cannot: *why* a key exists, and what the
platform does with it.

## Before you write anything

**Start from a template rather than a blank file:**

```sh
wfb new "My Face"                 # the dashboard template
wfb new "My Face" -t minimal      # just a background and the time
wfb new --list                    # what else there is
```

**Turn on editor autocomplete.** The schema is a shipped artefact, so a YAML
language server will complete keys, document them on hover, and flag mistakes as
you type. Either add a modeline to the file:

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/vvorth/garmin-wf-builder/main/schema/wfb-face-1.schema.json
```

…or map it once in your editor. VS Code, with the `redhat.vscode-yaml`
extension — this repository already ships [`.vscode/settings.json`](../.vscode/settings.json)
with it configured:

```json
{ "yaml.schemas": { "./schema/wfb-face-1.schema.json": ["*.face.yaml"] } }
```

`wfb schema --path` prints the schema's location if you need to point something
else at it.

**Keep a preview open while you edit:**

```sh
wfb preview my-face.yaml --watch
```

It re-renders whenever the file — or a font it uses — changes, so the loop is
edit and look rather than edit, run, look.

---

## Document shape

```yaml
format: 1               # major only; the compiler refuses a version it does not know
face:
  id: <uuid>            # the Connect IQ application UUID -- generate once, keep stable
  name: Slice
  version: 1.0.0
targets: [fenix8solar47mm, fenix8solar51mm, fr955]
palette: {...}
fonts:   {...}
elements: [...]
```

**Unknown keys are an error, not a warning.** Silently ignoring a misspelled key
is how a design quietly loses an element. (The GUI, when it exists, has the
opposite rule: it must *preserve* keys it does not understand, so an older editor
cannot destroy a newer file. See ADR 0009.)

---

## Coordinates

A position is either cartesian or polar, relative to an anchor on the parent box:

```yaml
at: { anchor: center, dx: 0, dy: -18% }
at: { anchor: center, angle: 45deg, radius: 38%r }
```

Anchors are the nine box positions: `top_left`, `top`, `top_right`, `left`,
`center`, `right`, `bottom_left`, `bottom`, `bottom_right`.

### Lengths

| Unit | Resolves against |
|---|---|
| `px` | device pixels, verbatim.  A bare number means `px`. |
| `%` | the parent box, along the axis being resolved — width for `dx`, height for `dy` |
| `%r` | the screen's **minor radius** (half the smaller dimension) |
| `pt` | multiples of the element's font pixel height on this device |

`%r` is what keeps a round design circular. `50%r` is the same physical fraction
of the dial on a 260×260 and a 280×280 screen; `50%` of the width is not, once a
screen stops being square.

### Angles

Degrees, **12 o'clock = 0, clockwise positive** — how a watch designer thinks.
Garmin's `drawArc` uses 3 o'clock = 0 and counter-clockwise positive; the
compiler converts, and the generated `Layout` module shows both values in a
comment so the conversion is auditable.

Everything relative is resolved to whole pixels at build time. Nothing relative
reaches the device: the watch performs no layout arithmetic.

---

## Palette

```yaml
palette:
  bg: "#000000"
  text: "#FFFFFF"
  accent: "#FF5500"
```

Elements reference `palette.accent`, never a raw hex value. A literal colour is
accepted but produces a note, because a palette is what makes a colour change
one edit and a lint one rule.

**On a 64-colour panel each channel must be `0x00`, `0x55`, `0xAA` or `0xFF`.**
Anything else is dithered by the firmware and looks grainy. The linter warns and
names the nearest legal colour; `lint: {allow: [palette-dither], reason: "..."}`
on an element silences it for a deliberate choice.

---

## Fonts

```yaml
fonts:
  clock:
    source: assets/OpenSans-Regular.ttf   # relative to the design file
    size: 68                              # em pixels on the smallest target
    glyphs: "0123456789:"                 # optional -- see below
    antialias: false
    scale: true
```

The compiler rasterises the TrueType source into a BMFont sheet at build time,
per device.

* **Omit `glyphs` and the compiler derives the set** from every format spec and
  literal string the design can render. The example face's clock font carries
  eleven glyphs rather than a character set — on a 128 KB budget that is the
  difference between a large font fitting and not.
* **`scale: true` scales the sheet with the screen**, so one declaration is right
  on both the 260×260 and the 280×280 family. A sheet baked for one and shipped
  to the other is a real, common drift.
* **`antialias` defaults to false.** Bitmap fonts are 1-bit by default because
  anti-aliasing costs runtime RAM.

A glyph the design can render but the font does not contain is a **build error**,
checked against the baked sheet's own character map.

Alternatively name a system font directly: `font: FONT_MEDIUM`,
`font: FONT_NUMBER_HOT`, and so on.

---

## Elements

Z-order is document order, with an optional `z:` override. Every element takes
`id`, `type`, `at`, `modes`, `z`, `lint` and `overrides`.

### `shape`

```yaml
- id: background
  type: shape
  shape: rectangle          # rectangle | rounded_rectangle | circle | line
  at: { anchor: center }
  size: { width: 100%, height: 100% }
  color: palette.bg
```

`circle` takes `radius` and `filled`; `rounded_rectangle` takes `corner_radius`;
`line` takes `to` and `thickness`.

### `text`

```yaml
- id: clock
  type: text
  value: time.clock         # a data source or an expression; or use `text:` for a literal
  format: "{:%h:%M}"
  font: font.clock
  at: { anchor: center, dy: -4% }
  color: palette.text
  align: center             # left | center | right
  when_absent: hide
```

### `progress`

One element with a `style` discriminator, because the *binding* and *range*
semantics are identical across styles and only the rendering differs.

```yaml
- id: step_ring
  type: progress
  style: arc                # arc | bar
  value: activity.steps
  max: activity.step_goal
  at: { anchor: center }
  radius: 90%r
  thickness: 10px
  start_angle: 180deg
  sweep: 340deg
  color: palette.accent
  track_color: palette.track
  when_absent: hide
```

> **`style: arc` is a stroked ring, not a filled sector.** There is no `fillArc`,
> `fillSector` or `drawSector` anywhere in the Connect IQ API. `thickness` is a
> pen width; cap style is not selectable; true annuli and gradient sweeps do not
> exist. The schema deliberately does not offer `inner_radius`/`outer_radius`,
> because promising them would be a lie.

### `icon`

```yaml
- id: steps_icon
  type: icon
  icon: steps               # alarm | battery | distance | dnd | flame | floors | heart |
                             # notification | phone | steps | weather_clear | weather_cloudy |
                             # weather_dust | weather_fog | weather_hurricane |
                             # weather_partly_cloudy | weather_rain | weather_snow |
                             # weather_thunderstorm | weather_tornado | weather_windy |
                             # weather_wintry_mix -- see wfb/icons.py for the full list
  size: 30px                # px or %r only -- see below
  color: palette.accent
```

An icon is a single glyph from a vendored icon font
([Nerd Fonts](https://www.nerdfonts.com)' "Symbols Only" build), baked into a
bitmap font sheet at build time — the same pipeline that bakes a `fonts:`
entry, subsetted to exactly the glyphs a design uses. Drawing an icon is
drawing text: one `drawText` call against that baked font. No image ships in
the `.prg`; the resource cost is the same small per-glyph bitmap a custom text
font pays.

**`size:` accepts only `px` and `%r`, not `%` or `pt`.** The icon's font has to
be baked once, before layout runs, so its size cannot depend on a parent box
(`%`) or another element's own font (`pt`) — both are only known once layout
has already happened. `%r` is recommended, for the same reason it is
recommended everywhere else: it means the same thing regardless of screen size.

**The catalogue prefers Material Design Icons** (`nf-md`, the vendored font's
largest and most consistent set) whenever a glyph reads at least as well as an
alternative — the one deliberate exception is `steps`, which keeps a Font
Awesome glyph because MDI's walking/running figures read as "activity" rather
than "step count" at a glance. Weather icons (`weather_*`) come from the font's
dedicated Weather Icons set instead, because it covers more distinct conditions
and day/night pairs than MDI's own `weather_*` glyphs and — unlike them — its
codepoints fit in the Basic Multilingual Plane (see `wfb/icons.py`'s module
docstring). `wfb.icons.GARMIN_WEATHER_CONDITION_ICON` maps every
`Toybox.Weather.CONDITION_*` value (0–53) to one of these, and
`wfb.icons.METRIC_ICON` maps common data-source paths (`activity.steps`,
`heart_rate.current`, and so on) to their conventional icon, for a design or
tool that wants a sensible default rather than the compiler enforcing one.

**Beyond the named icons**, the vendored font has on the order of ten thousand
glyphs, including codepoints above the Basic Multilingual Plane (all of MDI's
own icons live there). `icon:` accepts any single character from it directly —
```yaml
icon: ""    # a literal glyph, e.g. from https://www.nerdfonts.com/cheat-sheet
```
— checked against the font's own character map at build time, the same way a
custom font's glyph coverage is checked. A codepoint above the Basic
Multilingual Plane builds and renders correctly; the generated `<font>`
resource simply omits its `filter` attribute, because the resource compiler
parses that attribute as UTF-16 code units and a surrogate pair would not
survive it (see `wfb/emit/resources.py`). See `wfb/assets/icons/README.md` for
how to find a codepoint, and its licensing (the font aggregates several
separately-licensed icon sets under Nerd Fonts' MIT patcher; the ones the named
catalogue draws from are attributed there).

### `group`

A container with `children:`. Percentages inside it resolve against the group's
box, not the screen.

---

## Data binding

Sources are addressed by dotted path and carry a type, a nullability, a
permission and a refresh tier. `wfb sources` lists the catalogue.

```yaml
value: activity.steps
value: heart_rate.current       # requires the Sensor permission -- derived, not declared
value: system.battery
value: time.clock
```

**The compiler derives `manifest.xml` permissions from the bindings.** A missing
permission does not fail loudly on a Garmin device: the API returns null and the
element simply never appears, with no diagnostic. Deriving the permission set
makes that failure structurally impossible.

### Absence is the normal case

Every `ActivityMonitor.Info` field is typed `... or Null`, and sensors are
missing entirely on some devices. So **`when_absent:` is required** for a
nullable binding rather than defaulting silently:

| Policy | Effect |
|---|---|
| `hide` | the element is not drawn |
| `placeholder` | fixed text is drawn instead (needs `placeholder:`) |
| `fallback` | another expression supplies the value (needs `fallback:`, which must not itself be nullable) |

### Expressions

Compiled to Monkey C. Nothing interprets them on the watch.

```yaml
color: "heart_rate.current > 150 ? palette.hot : palette.text"
value: "percent(activity.steps, activity.step_goal)"
```

Literals; references to sources and palette entries; `+ - * / %`; comparisons;
`and` / `or` / `not`; `cond ? a : b`; and exactly seven functions — `min`, `max`,
`clamp`, `round`, `floor`, `abs`, `percent`.

No loops, no user-defined functions, no assignment, no state. Anything beyond
this is a signal to use the escape hatch (ADR 0007), not to grow the language —
growing it is how these formats become unmaintainable.

Constant subexpressions fold at build time; only genuinely dynamic terms survive
into the generated code. Palette references stay *named* in the output, because
inlining the hex would throw away the point of having a palette.

---

## Formats

Python-style specs, familiar and unambiguous.

| Spec | Renders |
|---|---|
| `{}` | the value's own `toString()` |
| `{:d}`, `{:02d}` | an integer, optionally zero-padded |
| `{:.1f}` | a float |
| `{:d} steps` | literal text around the field |

Date values (`date.today`) use their own codes — separate from the time codes
below, because `%M` means minute and `%m` means month, and silently rendering one
where the other belongs is exactly the confusion the split prevents:

| Code | Renders |
|---|---|
| `%a` | abbreviated weekday, e.g. `Thu` |
| `%b` | abbreviated month, e.g. `Sep` |
| `%e` / `%d` | day of the month, unpadded / zero-padded |
| `%m` | month number, zero-padded |
| `%Y` / `%y` | four- / two-digit year |

`format: "{:%a %e %b}"` renders `Thu 3 Sep`. The weekday and month come back from
the firmware already localised, so a custom font bound to a date is subsetted
with the whole alphabet rather than with the glyphs of one particular day.

Time values use strftime codes, plus one addition:

| Code | Meaning |
|---|---|
| `%H` | hour, 24-hour, zero-padded |
| `%I` / `%l` | hour, 12-hour, padded / unpadded |
| **`%h`** | **the hour the user asked to see** — follows `DeviceSettings.is24Hour` |
| `%M`, `%S` | minute, second |
| `%p` | AM / PM |

`%h` exists because hand-written faces get the 12/24-hour setting wrong
constantly. A builder should get it right once.

The compiler also derives the **widest plausible rendering** of every binding
from its format and the source's documented range — that is what makes "does this
label overflow its slot?" a static check, and what decides a font's glyph set.

---

## Modes

```yaml
modes: [active, low_power]     # default: [active]
```

Mode is structural, not styling, because AMOLED forbids `onPartialUpdate`
entirely while MIP depends on it.

| Mode | Meaning |
|---|---|
| `active` | drawn in `onUpdate`, once a second while awake |
| `low_power` | also drawn in `onPartialUpdate`, once a second while asleep (MIP only) |
| `always_on` | the AMOLED burn-in-constrained layout |

The compiler computes the **tightest `setClip` rectangle** around all `low_power`
elements, because clip cost is charged by region *area* — every pixel inside the
clip counts as modified whenever any does.

**A `low_power` element may only read `frame`-tier sources.** This is an error,
and it is not suppressible: exceeding the partial-update budget calls
`onPowerBudgetExceeded` and disables partial updates for the rest of the app's
lifecycle.

---

## Lint suppression

```yaml
lint:
  allow: [palette-dither]
  reason: "deliberate orange accent, matches the brand"
```

`reason` is required — a suppression without a stated reason is how linters get
disabled wholesale. Errors that reflect hard platform limits (refresh tiers,
missing glyphs, off-screen geometry) are **not** suppressible: silencing one
produces a face that does not work.

---

## Not yet implemented

Present in the ADRs, absent from format 1: `image` and `complication_slot`
elements, the `raw` escape hatch (ADR 0007), per-device `overrides` (parsed but
not yet applied), the `config:` block and on-device configuration (ADR 0006), and
`segments`/`scale` progress styles. See [`docs/limitations.md`](limitations.md).
