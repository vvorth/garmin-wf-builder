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
  entry: Slice          # optional: the Monkey C entry class name, from `name` if omitted
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
* **Glyphs are rasterised at 16x and averaged down**, not drawn straight at the
  target size. At single-digit sizes FreeType's hinting fits the outline to the
  pixel grid and breaks the shape's own symmetry — measured across 99
  provably-symmetric glyphs from the icon font, **16.8% of ink pixels landed
  asymmetrically**: a plain square baked to 7x7 ink inside an 8x8 tile, and a
  ring came out lopsided in every row. Rasterising large and box-averaging
  recovers real per-pixel coverage before the 1-bit threshold sees it, which
  brings that to **1.1%**. Advances and line metrics are untouched, so this
  changes how a glyph looks, never where it sits.
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
  align: center             # left | center | right    (horizontal)
  vertical_align: center    # top | center | baseline  (vertical)
  when_absent: hide
```

**`align`/`vertical_align` say which part of the text's own box lands on `at`'s
resolved point** -- `at`/`anchor`/`dx`/`dy` only ever compute *one point*; these
two say what of the element is centred, started, or ended there, independently
per axis. Both default to `center`, which is why `at: {anchor: top, dy: 7%}`
by itself puts the *centre* of the text at 7% down from the top, not its edge.

To anchor the text's own **bottom** edge to a point instead (so growing text
extends upward from a fixed baseline, for instance) -- the case that is not
obvious from `align` alone -- set `vertical_align: baseline`:

```yaml
at: { anchor: top, dy: 7% }
vertical_align: baseline   # the box's bottom edge sits at dy: 7%, not its centre
```

`top` puts the box's top edge at the point instead. Note `baseline` here means
the bottom of the full line box (ascent + descent), not the typographic
baseline glyphs actually sit on (which excludes a descender like the tail of a
"g" or "y") -- close enough for short labels and digits, but not a true
baseline-align.

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
                             # notification | phone | steps, plus one `weather_<condition>`
                             # per Weather.CONDITION_* bucket and a `weather_<condition>_night`
                             # variant for most of them -- run `wfb sources` for the full,
                             # current list (53 names as of this writing)
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
codepoints fit in the Basic Multilingual Plane (see the comment above
`CATALOG` in `wfb/icon_catalog.py`). `wfb.icons.GARMIN_WEATHER_CONDITION_ICON` maps every
`Toybox.Weather.CONDITION_*` value (0–53) to one of these, and
`wfb.icons.METRIC_ICON` maps common data-source paths (`activity.steps`,
`heart_rate.current`, and so on) to their conventional icon, for a design or
tool that wants a sensible default rather than the compiler enforcing one.

**Beyond the named icons**, the vendored font has on the order of ten thousand
glyphs, including codepoints above the Basic Multilingual Plane (all of MDI's
own icons live there). Reach one with **`glyph:`**, which takes a codepoint in
Unicode's own notation:

```yaml
- id: repo
  type: icon
  glyph: "U+F09B"     # nf-fa-github; find codepoints at nerdfonts.com/cheat-sheet
  size: 12%r
  color: palette.dim
```

`glyph:` is the **recommended** way to use an icon the catalogue does not name.
`icon:` also accepts a bare character pasted straight into the YAML, and that
still works, but prefer `glyph:`: `U+F09B` is greppable, reviewable in a diff
and survives copy-paste, where the character itself renders as a blank box —
or as nothing at all — in most editors. That is the same hazard
`wfb/icon_catalog.py` warns about for this project's own source, and it applies
just as much to a design file.

`icon:`, `glyph:` and `icon_for:` are mutually exclusive — an icon element uses
exactly one. Writing `glyph:` for a codepoint the catalogue *does* name is
accepted with a note pointing at the name, which is the better spelling: a name
keeps meaning if the catalogue moves that icon to a different codepoint, which
has already happened once (the Font Awesome → Material Design Icons switch).

A codepoint the font does not carry is a build error, checked against the
font's own character map — the same way a custom font's glyph coverage is
checked, and for the same reason: the alternative is a blank tile discovered on
the wrist. A codepoint above the Basic
Multilingual Plane builds and renders correctly; the generated `<font>`
resource simply omits its `filter` attribute, because the resource compiler
parses that attribute as UTF-16 code units and a surrogate pair would not
survive it (see `wfb/emit/resources.py`). See `wfb/assets/icons/README.md` for
how to find a codepoint, and its licensing (the font aggregates several
separately-licensed icon sets under Nerd Fonts' MIT patcher; the ones the named
catalogue draws from are attributed there).

#### A dynamic icon: `icon_for`

`icon:` names a fixed glyph, chosen at build time. `icon_for:` instead chooses
the glyph on-device, at runtime, from a bound value — mutually exclusive with
`icon:`:

```yaml
- id: weather_now
  type: icon
  icon_for: weather.condition   # or weather.condition_today / .condition_tomorrow
  size: 20%r
  color: palette.text
```

This currently accepts only a bare `weather.condition*` source (see `wfb
sources`) — not an expression over one (`weather.condition + 1` is rejected;
the lookup needs the raw `Weather.CONDITION_*` value). The generated code
resolves the glyph in two steps, mirroring `wfb.icons` exactly: `WfbWeather.
chooseIcon()` (a hand-written barrel function, day glyphs only for now — there
is no sunrise/sunset source yet to pick the night variant on-device) turns the
condition into a catalogue *name*, and `IconGlyphs.glyph()` — generated fresh
each build directly from the icon catalogue, not hand-written — turns that
name into the actual character. A weather condition is not a special case on
the device side any more than it is in the catalogue: the same `IconGlyphs`
table is where any dynamic icon's name becomes a glyph. Because the actual
glyph is not known until runtime, its font bakes *every* glyph the lookup
could return rather than one — still cheap: baking is still a small per-glyph
bitmap, just several of them sharing one font instead of one glyph having its
own.

When the bound value is absent (no cached weather data yet), the icon simply
does not draw — the same `hide`-by-default behaviour any other nullable
binding without an explicit `when_absent:` has, deliberately: a placeholder
"unknown" glyph on first launch, before Weather has ever synced, would read
as a real (if odd) forecast rather than as "not ready yet".

### `group`

```yaml
- id: hr_group
  type: group
  size: {width: 60%, height: 20%}
  at: {anchor: center, dy: -20%}
  on_tap: heart_rate       # optional -- see "Interactivity" below
  children:
    - id: hr_icon
      type: icon
      icon: heart
      size: 10%r
      at: {anchor: center, dx: -15%}
    - id: hr_value
      type: text
      value: heart_rate.current
      format: "{:d}"
      when_absent: hide
      at: {anchor: center, dx: 15%}
```

A container with `children:` and its own `size:`/`at:`. **Percentages inside a
group resolve against the group's own box, not the screen** — `dx: -15%` above
is 15% of the group's 60%-of-screen width, not 15% of the screen. This is what
makes a cluster of elements (an icon plus its reading, a row of stats)
positionable and resizable as one unit: move or resize the group, and every
child's relative position follows without being restated.

A group draws nothing of its own — no fill, no border — it is purely a
coordinate frame and, when it carries `on_tap:`, a hit region. Use a `shape`
underneath it for a visible background.

**`on_tap:` on a group covers the group's whole box**, not just one child — the
natural way to make a multi-element cluster (an icon next to its value, as
above) act as a single tap target instead of naming `on_tap:` on each piece
separately. See "Interactivity" below.

---

## Data binding

Sources are addressed by dotted path and carry a type, a nullability, a
permission and a refresh tier.

```yaml
value: activity.steps
value: heart_rate.current
value: system.battery
value: time.clock
```

**`wfb sources` is the authoritative, always-current list** -- run it rather
than trusting a copy pasted into prose, which goes stale the moment the
catalogue grows. For each path it prints the type, whether it is nullable,
any non-`frame` refresh tier, any permission it implies, and the SDK page it
was taken from:

```
$ wfb sources
activity
  activity.steps                     number   steps today  [nullable]  (Toybox/ActivityMonitor/Info.html)
  ...
heart_rate
  heart_rate.current                 number   current heart rate  [nullable]  (Toybox/Activity/Info.html)
  ...
```

As of this writing the catalogue covers `time.*`, `date.*` (including the
localised month name and weekday), `device.*` (notification/alarm counts,
do-not-disturb, phone-connected, 24-hour setting, next calendar event),
`system.*` (battery, charging, solar charging input), `activity.*` (steps,
calories, distance, floors, move bar, intensity minutes, stress score,
respiration rate, time to recovery, training status, weekly run/bike
distance, sleep score), `heart_rate.current`, `pulse_ox.current`, `ambient.*`
(altitude, barometric pressure), `weather.*` (current condition and
temperature, feels-like, today's high/low and precipitation chance, humidity,
wind speed, today's/tomorrow's forecast condition, sunrise/sunset — see
`icon_for:` above for turning a condition into a drawn icon), `user.*`
(running/cycling VO2 max, resting heart rate, from `Toybox.UserProfile`) and
`body_battery.current`.

**Complications back several of the sources above** (`COMPLICATION_TYPE_*`,
`Toybox/Complications.html`, API 4.2.0) — `body_battery.current`,
`system.solar_input`, `weather.sunrise`/`sunset`, `activity.training_status`,
`activity.weekly_run_distance`/`weekly_bike_distance`,
`activity.sleep_score` and `device.next_calendar_event` — because none of
them is reachable any other way: Body Battery, for instance, is otherwise
exposed only through `Toybox.SensorHistory`, a permission **watch faces are
not allowed to declare at all** (`Core_Topics/Manifest_and_Permissions.html`'s
permission table has a blank Watch Face column for it). These sit on the
`event` refresh tier, not `frame` or `slow`: nothing is fetched on a schedule
at all, `Complications.registerComplicationChangeCallback` pushes a new value
whenever one arrives, and the generated view just keeps the most recent one
in a field (see "Refresh tiers" below). Binding any of them adds the
`ComplicationSubscriber` permission and raises `minApiLevel` to 4.2.0
automatically, the same way any other binding derives its own requirements.

A device can decline to support a given complication type outright — most
relevantly here, `activity.sleep_score` needs ConnectIQ 6.0.2, above `fr955`'s
own 5.2.0 ceiling (its `compiler.json`), so it will never update there.
`runtime-lib/WfbComplications.mc`'s `subscribe()` absorbs this the same way
every other nullable source is absorbed: the field just never gets filled in,
rather than the subscription throwing. A design that binds
`activity.sleep_score` will show nothing at all on `fr955` specifically —
worth knowing before relying on it there.

*Redundant with a direct source and deliberately not added*: complications
duplicating a field already bound directly (`COMPLICATION_TYPE_STEPS`,
`_CALORIES`, `_HEART_RATE`, `_ALTITUDE`, `_VO2MAX_RUN`, `_VO2MAX_BIKE`,
`_RECOVERY_TIME`, `_STRESS`, `_CURRENT_WEATHER`, `_CURRENT_TEMPERATURE`,
and several more — a direct `ActivityMonitor`/`Activity`/`Weather`/
`UserProfile` read is cheaper and needs no subscription). *Left out as
niche*: the eight race-time and race-pace predictors, `LAST_GOLF_ROUND_SCORE`
and `WHEELCHAIR_PUSHES` — nothing platform-specific blocks adding these later
if a design needs one; they simply were not among the commonly-used fields
this pass targeted.

**One thing genuinely still isn't bindable**: a running-only *total* distance
(as opposed to weekly). `COMPLICATION_TYPE_WEEKLY_RUN_DISTANCE` is a *weekly*
total, not all-time, and there is no other platform field for it short of
aggregating `UserProfile.getUserActivityHistory()` by hand, which is real
computation ADR 0005 deliberately keeps out of the expression language.
`activity.distance` (today's ambient distance, every activity type) remains
the nearest thing actually bindable.

See `docs/limitations.md` §2 for what is still missing from the catalogue.

### Refresh tiers

A `slow`-tier source (`weather.*`) is not re-read every frame the way a
`frame`-tier one is: the generated view caches the last read in a field and a
UTC-seconds timestamp, and only calls the API again once that reading is older
than a fixed TTL (`WfbCache.mc`, `wfb/emit/monkeyc.py`'s `ReadPlan`). Two
elements bound to the same underlying reader — `weather.condition_today` and
`weather.condition_tomorrow` both read one `getDailyForecast()` call, for
instance — share one cache and one read, not one each.

An `event`-tier source (every complication-backed one above) is not read on
any schedule at all: the view subscribes once, in `onLayout`
(`WfbComplications.subscribe`, one call per complication, registered against
one shared `onComplicationChanged` callback), and that callback is what
writes the cached field — `onUpdate` just reads whatever is there, the same
`var x = <cache>;` shape a `frame`-tier read uses, with no staleness check
because there is nothing to re-fetch on demand.

Neither a `slow` nor an `event` tier source may be bound from a
`low_power`-mode element: `onPartialUpdate` runs under a strict power budget
that only frame-tier reads are cheap enough for, and the compiler rejects the
design outright rather than silently reading something wrong.

If a value you want is missing and it is not one of the two above, check the
underlying Garmin API page: `Toybox/ActivityMonitor/Info.html`,
`Toybox/System/Stats.html`, `Toybox/System/DeviceSettings.html`,
`Toybox/Activity/Info.html`, `Toybox/Weather/*.html` and
`Toybox/UserProfile/Profile.html` are where the current catalogue draws from,
and each has more fields than are exposed today -- adding one is a
`wfb/catalog.py` entry (path, type, nullability, tier, permission, the SDK
field it reads), not a schema change. Before adding one, check the field's own
"Supported Devices" list in the SDK doc against the three targets by name --
several fields on these pages are gated per device even though the class
itself is universal (`ambientPressure`, `vo2maxRunning` and others all needed
this check; `altitude` and `restingHeartRate` turned out not to).

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

**`when_absent:` covers every nullable binding on the element, not just
`value:`.** A nullable `color:`, `track_color:` or `max:` needs a policy too — a
conditional colour reading `heart_rate.current` makes the whole element depend on
that sensor. A nullable non-value binding always *hides* the element when it is
absent, whichever policy is named, because a colour has no placeholder. If that
makes a declared `placeholder:`/`fallback:` impossible to reach — every nullable
source behind the value is also read by the colour — the compiler says so rather
than letting the substitute sit there as dead text.

**On a `progress`, `fallback:` supplies the fill fraction (0.0–1.0), not the
value.** This is the one place the policy means something different from `text`,
and it is forced: either `value:` or `max:` can be the absent reading, so the
resulting proportion is the only well-defined thing to substitute. A constant
outside 0.0–1.0 is a build error; a computed one is clamped on device. For "half
full" write `0.5`, not the reading you would have shown.

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

## Interactivity: `on_tap:`

Any element can open a glance when it is touched:

```yaml
- id: hr_icon
  type: icon
  icon: heart
  at: {anchor: center, dy: -20%}
  on_tap: heart_rate        # run `wfb complications` for the 42 names
```

**A watch face cannot launch an arbitrary app.** The platform offers exactly
one exit — `Complications.exitTo`, documented as "launches the app associated
with the complication" — so an interactive element names a **complication
type** and the watch opens whichever glance or app owns it. `on_tap:
heart_rate` opens the heart-rate glance whether or not the design displays a
heart rate.

`wfb complications` lists every name, the Monkey C constant it compiles to,
and the API level that type was introduced at. The list is generated from the
SDK's own `COMPLICATION_TYPE_*` table, so it cannot drift from what the
platform actually offers.

**One declaration, two behaviours.** `WatchFaceDelegate.onTap` is documented
since API level 5.1.0 and is *still absent* on some watches above it — `fr955`
is 5.2.0 and has only `onPress`. The compiler emits both handlers, so the same
`on_tap:` is a tap where tap exists and a touch-and-hold where it does not,
and `wfb validate` says which you are getting on each target, resolved against
that device's own symbol table rather than its API level:

```
note[tap-unsupported]: fr955 has no WatchFaceDelegate.onTap, so its 2 tap
target(s) are reached by touch and hold instead
```

**The hit region is the element's own drawn box** — what the finger must hit is
what the eye sees, which is checkable in `wfb preview`. Nothing is inflated to
a minimum touch size: Garmin publishes no such number, and inventing one would
silently overlap neighbours on a dense face. For a bigger target, or to make
several elements act as one, put them in a `group` (above) and put `on_tap:`
on the group instead of each child.

Regions are tested in draw order and the first match wins, so two overlapping
tap regions make the second unreachable. That is a warning (`tap-overlap`),
not something you have to notice on the wrist.

Binding `on_tap:` adds the `ComplicationSubscriber` permission and raises
`minApiLevel` to 4.2.0 automatically — `exitTo`'s own level, not `onTap`'s
5.1.0, because a watch below 5.1.0 still runs the face perfectly well; it just
does not deliver touches.

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

Exactly five codes are suppressible: `palette-dither`, `safe-area`,
`text-overflow`, `contrast` and `partial-update-budget`. **A code that is not one
of them is a build error**, and the message distinguishes the two ways that
happens — a code the compiler does not emit at all (with a "did you mean"
suggestion) versus a real code that is deliberately unsuppressible (with the
reason). Both used to be ignored in silence, which left an author unable to tell
a typo from a check that refuses to be silenced.

Two of the five are not element-scoped diagnostics, so the allow goes on the
element that causes them: `palette-dither` on an element whose `color:` or
`track_color:` is exactly `palette.<name>`, and `partial-update-budget` on any
element drawn in `low_power` mode. See `docs/limitations.md` §3.

---

## Not yet implemented

Present in the ADRs, absent from format 1: `image` and `complication_slot`
elements, the `raw` escape hatch (ADR 0007), per-device `overrides` (parsed but
not yet applied), the `config:` block and on-device configuration (ADR 0006), and
`segments`/`scale` progress styles. See [`docs/limitations.md`](limitations.md).
