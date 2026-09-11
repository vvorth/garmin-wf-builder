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

`shape: arc` is the same primitive without a binding, and for the same reason
**`filled:` is a build error on it** rather than a silently-ignored key. The
nearest achievable thing to a filled sector is a `shape: polygon` approximating
the wedge; the nearest thing to a solid disc is `shape: circle`.

### There is no `drawPolygon`

`Toybox.Graphics.Dc` has `fillPolygon` and no outline counterpart — checked in
`$CIQ_SDK/doc/Toybox/Graphics/Dc.html` and in each target's own
`<id>.api.debug.xml`. So `filled: false` is a build error on `shape: polygon`,
naming the gap; an outline has to be drawn as `shape: line` edges, which is
exactly what a generated `drawPolygon` would have had to compile to anyway.

`fillPolygon` also documents a hard **64-point limit**, which the schema
enforces as `maxItems` on `points:`.

A `graph` element with `style: area` inherits the same limit: closing the
outline costs two corners, so the usable sample count is 62, checked at
build time (`wfb/ir.py`'s `GRAPH_AREA_MAX_SAMPLES`) against `style: line`
as the named alternative.

### `SensorHistory` is closed to a watch face, and solar has no history API at all

The obvious route to pressure, stress, elevation and Body Battery **as a
time series** is `Toybox.SensorHistory` — a real iterator, with a period and
an order, for exactly this purpose. A watch face may not use it:
`Core_Topics/Manifest_and_Permissions.html`'s permission table has a "Watch
Face" column, and the `SensorHistory` row's cell is empty. It still
compiles — a watchface manifest declaring the permission and calling
`SensorHistory.getPressureHistory({...})` builds warning-free on all three
targets — and a permission a face may not hold fails *silently* at runtime
(see "A missing permission fails silently" below), so the only symptom
would be an empty graph on the wrist. `wfb/series.py`'s catalogue therefore has no entry that reads
`SensorHistory` at all, and never will without a platform change.

**Solar is a stronger negative still: there is no solar history API
anywhere in Connect IQ.** Only two current-value reads exist
(`System.Stats.solarIntensity`, `Complications.
COMPLICATION_TYPE_SOLAR_INPUT`), and neither is a series. The solar chart on
a stock fēnix face is native firmware; the remaining route — sampling
`solarIntensity` into the face's own rolling buffer — is a different design
with its own unmeasurable risks (flash-write frequency, coverage gaps
whenever the face is not the active one) and was deferred by decision, not
attempted. `docs/research/08-graphs-and-configuration.md` §1 and
`docs/research/probes/graph-series/` have the full evidence.

What is open — every `graph` `series:` there is, all needing **no
permission** (`Toybox.ActivityMonitor` and `Toybox.Weather` are both absent
from the same permission table, the same no-permission situation
`Toybox.Activity` is already in for `heart_rate.current`): `heart_rate`;
the daily activity family `steps`/`calories`/`distance`/`floors_climbed`/
`active_minutes` (`ActivityMonitor.getHistory()`, at most 7 days); the
hourly forecast family `forecast_temperature`/
`forecast_precipitation_chance`/`forecast_cloud_cover`/`forecast_uv_index`/
`forecast_wind_speed`/`forecast_humidity`; and the daily forecast family
`daily_high_temperature`/`daily_low_temperature`/
`daily_precipitation_chance`. Run `wfb series` for the current, authoritative
list.

**The CPU cost of acquiring and drawing a graph every minute is
unmeasured**, the same standing every other feature in this repository
without a simulator or a watch has (below, "The simulator does not run in a
headless Linux container"). The generated code rebuilds its cached series
only when the clock minute changes, which is a cheap precaution, not a
measurement.

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

### `monospace:` only reaches a font the compiler bakes

`fonts.<name>.monospace` (`docs/format.md` §Fonts) gives every glyph in a
**custom** font one shared advance, which is what stops a digital clock
shifting as its digits change. A **system** font — `FONT_MEDIUM`,
`FONT_NUMBER_HOT` and the rest — is already rasterised on the device and the
real typeface is not available anywhere on the host, so there is nothing to
rebake and no way to offer the same guarantee. A clock in a system font
jitters exactly as much as that font's own figures do, and `wfb` cannot tell
you by how much: its width for a system font is an estimate against a stand-in
face (`wfb/fonts/fallback.py`), which is the same reason the text-overflow
check is labelled estimated there.

Deliberately not offered, on either kind of font: a *vertical* equivalent of
`align:`. Baseline and line height are the font's own metrics and are what make
a line of text sit together; a `text` element's `vertical_align:` already says
where that line goes.

### A font's `size:` cannot be `%` or `pt`, and is not normalised to ink height

`fonts.<name>.size` takes a bare number or a `px`/`%r` length (`docs/format.md`
§Fonts), and not the other two units the coordinate model has. This is a real
restriction, and it is structural rather than an omission: a bitmap sheet is
rasterised **before** any element is placed, so a `%` has no parent box to be a
fraction of, and a `pt` — which is defined as a multiple of a font's own pixel
height — would be measuring a font's size against itself. Both are a build
error naming `%r`, which is what an author reaching for `%` on a font almost
always wants.

Separately, and deliberately: a font's declared size is the **nominal em size**
handed to the rasteriser, not a measured ink height. Two different typefaces
declared at the same `size:` can therefore render visibly different heights,
because how much of the em-square a face's ink fills is a property of the face.
An `icon`'s `size:` *is* normalised that way (`wfb/icons.py`'s `bake_size`),
because an icon is one glyph placed on its own and ink height is the whole of
what its size can mean; a typeface's characters share a baseline and a line
height, and their relative proportions are the typeface, so normalising against
one chosen reference character would distort every other one. Nothing checks
that two fonts at one declared size look the same height — they will not,
in general.

### The JSON Schema does not describe the mapping form of `elements:`

An element list may be written as a sequence or as a mapping keyed by element id
(`docs/format.md` §"Two ways to write a list of elements"). Both are accepted;
only the sequence is in `schema/wfb-face-1.schema.json`, because the mapping is
rewritten into the sequence by `wfb/desugar.py` **before** validation, which is
exactly what keeps the schema, the IR, the linter, the preview and codegen from
having to know that two spellings exist.

The cost lands on the editor. A YAML language server pointed at the schema —
which this project recommends setting up — validates the file as written, not
as the compiler will read it, so every mapping-form element is reported as
invalid (`elements` should be an array) while `wfb validate` reports nothing.
This is not fixable by adding an `anyOf` to the schema without also giving the
schema a second, parallel description of every element type keyed differently,
which is the duplication the desugaring pass exists to avoid. The workarounds
are to use the list form in files you want an editor to check, or to drop the
`$schema` modeline from a mapping-form file.

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

### A `BufferedBitmap` is opaque here, because transparency could not be established

`static:` (see [`docs/format.md`](format.md)) draws fixed content once into a
`Graphics.BufferedBitmap` and blits it every frame. The attractive version of
that feature lets a static group sit **anywhere** in draw order: clear the buffer
to `COLOR_TRANSPARENT` and its untouched pixels leave what is under them alone.

That could not be established. `Dc.clear()` is documented to honour
`COLOR_TRANSPARENT` since 3.1.0, and the example it gives is the WatchUi overlay
layer, not a buffered bitmap; `createBufferedBitmap`'s default is
`ALPHA_BLENDING_FULL`, which is about drawing *into* the surface; the only place
the SDK explains where a transparent index comes from is about **resource
compiler** bitmaps; `alphaBlendingSupport` is `false` on all three targets and
appears nowhere in the SDK documentation at all. Pointing the other way, the
same device files say `pixelFormat: ARGB2222`, so the display's own pixel does
carry alpha bits. Suggestive on both sides, decisive on neither — and the
simulator does not run here (below), so it cannot be tried.

So the shipped design is the provable one: **the buffer is opaque, and static
content is a contiguous prefix of draw order.** One consequence worth naming:
there is exactly **one** buffer per face, because a second opaque full-screen
blit would erase the first. Several `static:` groups are allowed, and they share
that one buffer.

The author does not have to write them at the front, though. Since there is no
order in which anything can be *under* an opaque full-screen blit, "static
content first" is not a choice the design can express, so the compiler makes it
rather than rejecting a design that wrote it otherwise: static elements are
hoisted to the front of draw order (`wfb.ir.draw_sort_key`), each `static:` root
kept as one unbroken run. What that costs is honesty about which element ends up
on top, and the suppressible `static-overlap` warning pays it — it names the
pairs the hoist actually swapped *and* whose boxes overlap on that device, and
says nothing about swaps that cannot change the picture. It is stated in
bounding boxes rather than ink, and says so: two boxes can intersect while
nothing drawn inside them does.

If someone demonstrates transparency on real hardware, the hoist and its warning
are the only things that have to relax. The full evidence is in
[`docs/research/probes/static-buffer/`](research/probes/static-buffer/README.md).

### The benefit of `static:` is unmeasured, and must not be claimed

`static:` exists to spend less CPU and therefore less battery per frame. **That
has not been measured anywhere in this repository, and cannot be**: there is no
simulator in this container and no watch. What *is* verified is that the
generated shape compiles warning-free under `-l 3` on all three targets, that
the no-buffer fallback path draws the same content through the same method, and
what it costs in bytes: **+9 B data, +147 B code** for the idiom on its own,
**+27 B data, +183 B code** on a real design (`examples/static/`, 2,769 B ->
2,979 B of the 131,072 B limit), plus one full-screen surface in the graphics
pool (67,600 B at 260x260, 78,400 B at 280x280, of 1,048,576 B) that is *not*
charged against the watch-face limit. Anyone reading a speedup into this feature is reading something nobody
here established.

The pool figure is itself an **estimate**: bytes per pixel for a
`BufferedBitmap` is not published, so the `graphics-pool` lint uses the
display's own `bitsPerPixel` from the device files and ignores per-surface
overhead. It says so in its own `confidence:` line.

### 64 colours, and everything else dithers

Each channel must be `0x00`, `0x55`, `0xAA` or `0xFF`. Anything else is dithered
by the firmware and looks grainy at close range.

Anti-aliasing a `shape` or `progress` element (`antialias:`, `docs/format.md`)
manufactures exactly the intermediate values this rule is about: a soft edge
is a blend, by construction, and every value in between is off the 64-colour
grid. `lint.check_antialias_palette` (`antialias-dither`) says so once per
device, against the first element that draws anti-aliased, and is
suppressible — an author who wants the softer look on a MIP panel is
accepting dithering at the edge on purpose. All three of this project's
current targets are 64-colour, so this fires on every face that turns the
feature on for a `shape`/`progress` element. (What `wfb preview` shows for
that same soft edge is a separate gap — see "the simulator does not run in a
headless Linux container" below.)

### On-device configuration: four axes, four configurations, and not on fr955

The native watch-face editor is **API 5.1.0, fēnix 8 and newer**, and exposes
exactly four axes: Styles, complication slots, **one** data colour and **one**
accent colour. At most **four saved configurations** per face. There is no
per-element colour editing and no arbitrary data rebinding.

**Three of the four axes are implemented, as `config:`** (`docs/format.md`
"Configuration" and "Color scheme"; ADR 0006 §1, twice amended): the two
colour axes, and **Styles**, which carries no colour of its own but is the
only axis Garmin gives no meaning to at all — a declared `color_scheme:`
(a named role -> colour set) rides it as `config.colors`. Only the **Data**
axis (per-complication-slot type choice) is not — see §2 below.

**The Forerunner 955 is excluded from it entirely.** A design targeting all three
devices is configurable on the wrist on two of them. This is a consequence of the
chosen scope (native editor plus phone settings, no generated on-device menu),
not a defect — but it must never be a surprise: a target with no native editor
keeps every `config:` entry's declared `default:` forever — colour axes and
color_scheme roles alike — and the suppressible `config-unsupported` warning
says so at build time rather than leaving it to be discovered on the wrist.

**No behaviour of the editor is verified anywhere in this project.** There is
no simulator in this container and no watch (§2 below, "the simulator does not
run"), so everything claimed about `config:` is a compile-time result — the
schema accepts or rejects a design, a real `monkeyc` build succeeds or fails,
`--build-stats`/file size report a byte cost — never a description of what the
editor's UI actually shows or does. `docs/research/probes/watchface-config/`'s
own "What it deliberately does NOT settle" section is explicit about the same
boundary.

**What the Data axis could carry is now researched, not implemented**
(`docs/research/09-data-library-and-config-axes.md`,
`docs/research/probes/config-axes/`). Three results bear on any future work
here, and none of them changes what the compiler does today:

* **The Data axis can never hold author-defined content.** `<complication>`'s
  children are `Complications.COMPLICATION_TYPE_*` values or `allowAny`, per
  `resources.xsd`. Author-defined selectable content rides **Styles**, whose
  `styleId` Garmin gives no meaning to -- and which is a *single* number, so
  several independent author-defined axes multiply into one flat list.
* **There is no way to ask which saved configuration is active.**
  `getSettings(null)` returns the active `Settings`, which carries no id, and
  `Id` exposes only `equals`. So the four axes are per-configuration while
  anything the face persists itself (`Application.Storage`, properties) is
  global across all four of the wearer's saved faces.
* **`getComplicationDrawable` is buildable**, at `+134 B data, +414 B code`,
  from a generated `Drawable` subclass delegating back to the view's own
  per-slot draw method. It remains unimplemented -- but the reason is now
  "no Data axis to animate yet", not "unknown shape". Without it the editor's
  animated highlight has nothing to animate, and the SDK sample's own comment
  requires the view to *hide* a slot while the system pulses it.

### A live watch face receives exactly one gesture: touch and hold

Not one gesture *per device* — one gesture, full stop. `WatchFaceDelegate`
declares no swipe, the physical keys belong to the system on the watch-face
screen, and `WatchUi.configureTouchEvents` is documented "only allowed for
Watch Apps and Audio Content Providers". `WatchFaceDelegate.onTap` does exist
on the fēnix 8 targets, but the SDK documents it **"Only available in WatchFace
config mode"**: it is how the on-device editor learns which complication slot
the user picked, and it never fires on a face that is merely being looked at.

So `onPress` is the whole input surface, `ClickEvent.getCoordinates()` is the
only way to give one hold more than one meaning, and anything modelled on a
stock Garmin face's tap behaviour is modelled on native firmware this API does
not expose. `docs/research/07-carousel-interaction.md` §1 has the evidence.

This project's `on_hold:` was called `on_tap:` until that was established.

### Animation exists, but only while the watch is awake

`WatchUi.animate()` **crashes the app** if called "from watch face while in low
power mode", and a watch face has access to timers and animations only during
the roughly ten seconds of high power mode that follow a gesture or a return
from another app (`doc/Toybox/WatchUi/WatchFace.html`). Since a touch is itself
one of the things that keeps the face awake, an animation driven by user input
is workable — but it must be guarded on the sleep state and degrade to an
instant change, never assumed.

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
clock, the conditional colours, the badge and the arcs, and now the weather
row's icon and every one of its readings, Body Battery, and the data a
daylight arc would need. **The `type: graph` element (`docs/format.md`) has
since shipped**, closing the "no element type plots a series at all" half
of what used to block the history graph. What remains blocked is narrower,
and is a data-source gap rather than a layout one:

| Dashboard has | Blocked on |
|---|---|
| A history graph of heart rate | nothing — `type: graph`, `series: heart_rate` |
| A history graph of Body Battery, stress, pressure or elevation | these are `Toybox.SensorHistory`-backed, and a watch face may not declare that permission at all — see "`SensorHistory` is closed to a watch face..." above. Body Battery and stress each have a *current-value* route (`complication.body_battery`, `activity.stress_score`), but neither is a series |

Weather's condition icon (`icon_for: weather.condition`, resolved on-device
through `WfbWeather.mc`, mirroring `wfb.icons.weather_icon_for_condition()`)
and its full reading set -- temperature, feels-like, today's high/low and
precipitation chance, humidity, wind speed -- both shipped; see
`docs/format.md`'s `icon_for` and "Data binding" sections. Body Battery
(`complication.body_battery`) and a daylight arc's sunrise/sunset data
(`complication.sunrise`/`complication.sunset`) also both shipped, all three
through `Toybox.Complications`, read the same way every other source is now
read -- a plain per-frame pull, see `docs/format.md`'s "Data binding" section
-- not a direct API field. Nothing in `examples/dashboard/` binds any of
these yet, the graph included; that is an example-content update the user
makes on their own playground (see "`examples/dashboard/face.yaml` is the
user's own playground" in CLAUDE.md), not a platform gap.

| Missing | Where it is specified |
|---|---|
| `image` and `complication_slot` elements | ADR 0004. `complication_slot`'s "cycle through several readings" half shipped as `carousel`; what is missing is a slot whose *type* the wearer picks in the on-device editor, which needs the Data axis below |
| The `raw` escape hatch to hand-written Monkey C | ADR 0007 |
| Per-device `overrides` (parsed and validated, not yet applied) | ADR 0004 §4 |
| The Data axis of on-device config, and phone-side settings | ADR 0006 §1, twice amended. The two colour axes and Styles (`config:`, `docs/format.md` "Configuration"/"Color scheme") shipped |
| `segments` and `scale` progress styles | ADR 0004 §1 |
| Automatic unit conversion (`units: auto`/`metric`/`statute`, metres->km/mi, m/s->pace) | ADR 0005 §4 states this as framework-owned; no `units:` schema property or conversion code exists at all. `examples/dashboard/face.yaml`'s `activity.distance / 100000.0` is an author doing by hand exactly what this was meant to spare them |
| `wfb install`, `package`, `migrate`; the GUI | brief, Phase 3 |
| Catalogue generation from the SDK (the table is hand-written for now) | ADR 0005 §1 |
| SDK-version recording and device-database mismatch warning | ADR 0009 §4 |
| ADR 0008's check 2, **unsupported API for a targeted device**, for anything other than `on_hold:` | `on_hold:` resolves `WatchFaceDelegate.onPress` against each device's own symbol table, so the machinery is live — but `catalog.Source.requires` still consults nothing; §3 below has the detail |
| `mypy --strict` in CI, ADR 0001's stated mitigation for Python's lack of compile-time exhaustiveness checking over IR node types | ADR 0001 -- there is no CI configuration anywhere in the repo, and `mypy` is not even in `requirements-dev.txt` |

**The refresh-tier concept (ADR 0005 §5) shipped and was then deleted
outright**, on the user's own explicit instruction: `catalog.Tier`,
`Reader.tier`, `Reader.ttl_seconds`, `Source.tier`, `wfb/ir.py`'s
`_check_tiers` and `runtime-lib/WfbCache.mc` are all gone. Rationale: every
value already comes from a Garmin API that documents itself as caching on its
own side (`Toybox/Weather.html`'s `getCurrentConditions()` is "get the most
**recently cached** weather conditions"), so a second TTL cache inside the
128 KB budget bought nothing. Every source, `weather.*` and `complication.*`
included, is now a plain per-frame read -- see `docs/format.md`'s "How data
is read" section. One real consequence: a `weather.*` or `complication.*`
binding may now be used from a `low_power`/`always_on` element, where it used
to be a hard, unsuppressible build error. It is no longer rejected outright;
it is now the author's own responsibility, backed only by the suppressible
`partial-update-budget` warning -- see §3 below and `docs/format.md`'s
"Modes" section. **Complications are read by pull, not by subscription
callback**: `WfbComplications.valueOf` is called from `onUpdate` exactly like
any other reader, cast to the source's declared type because
`Complication.value` is a union type. A subscription is still registered once
per bound type in `onLayout`, but only to call `WatchUi.requestUpdate()` on
change -- it is not a cache, and dropping it entirely was deliberately not
tried: whether a pulled complication value would *stay* fresh with no
subscription at all is **unverified**, because this container has no working
simulator (§2 below, "The simulator does not run in a headless Linux
container") to test it against. All 42 `COMPLICATION_TYPE_*` values are now
data sources under `complication.*`, not the nine that used to be exposed
under other names -- `complication.body_battery`, `complication.
solar_input`, `complication.sunrise`/`sunset`, `complication.
training_status`, `complication.weekly_run_distance`/`weekly_bike_distance`,
`complication.sleep_score` and `complication.calendar_events` are the nine
renamed ones (old path names now raise a `source-renamed` build error naming
the replacement); see `docs/format.md`'s "The `complication.*` namespace"
section and `WfbComplications.mc`. `complication.sleep_score` is a partial
exception worth tracking separately: it needs ConnectIQ 6.0.2, above
`fr955`'s own 5.2.0 ceiling, so it never updates there (below, "device
gating for a source is not enforced") -- unchanged by the rename, just
restated under its new path.

### Screen shapes

Only `round` and `rectangle` have safe-area geometry. `semi-round` and
`semi-octagon` are **unsupported targets rather than silently wrong ones**: the
geometry check reports "not checked" instead of guessing.

### The simulator does not run in a headless Linux container

`wfb simulate` works where the Connect IQ simulator does. It is a GUI
application, and on Linux it links against `libwebkit2gtk-4.0`, `libsoup-2.4`
and `libjavascriptcoregtk-4.0`, which current distributions no longer ship.

Supplying them is not enough, and the failure is worth stating precisely because
the obvious reading of it is wrong. On an `ubuntu:22.04` base — which still
packages all three natively, so every one of the simulator's 27 otherwise-missing
shared libraries resolves — the simulator **starts**: it opens its window under
Xvfb and sits there. It then **segfaults the moment a `.prg` is pushed to it**
with `monkeydo`, which is the "on app load" failure, and it does so with an
unmodified SDK sample `.prg` — an environment limitation, not a property of
generated faces.

The faulting frame is on a worker thread the simulator spawns during app load,
**entirely inside its own stripped executable**; GTK, WebKit and JavaScriptCore
appear nowhere on the stack. `libGL` is not among the loaded objects at all, so
this is not a software-OpenGL problem — an earlier version of this document said
it was, and the backtrace disproves it. Ruled out by direct test, each varied on
its own: `/dev/shm` at 64 MB and at 2 GB; Docker's default seccomp profile and
`--security-opt seccomp=unconfined`; running as uid 1000 and as root; the device
definitions mounted read-only and copied in writable; and WebKit's
`DISABLE_COMPOSITING_MODE` / `DISABLE_SANDBOX` escape hatches.

`wfb preview` is the answer in that environment: it renders from the same
resolved geometry the generated code uses, so the two cannot disagree about
position. What it does *not* claim to reproduce is glyph rasterisation for system
fonts, arc cap shape, the transflective panel's real appearance, or — a
deliberate scope decision, not an oversight found late — **a `shape`/
`progress` element's own anti-aliasing** (`antialias:`, `docs/format.md`):
that side of the feature is a runtime `Dc.setAntiAlias` call, and
`wfb/preview.py` draws every primitive with plain `PIL.ImageDraw` calls
(`rectangle`, `ellipse`, `arc`, `polygon`, `line`), which are aliased by
construction and were not changed to match. ADR 0004 exists precisely so the
preview and the device cannot disagree about what a design looks like, and a
second renderer's idea of a soft edge is not Garmin's. Turning `antialias:` on
for a `shape`/`progress` element changes what the device draws with no
visible difference in `wfb preview`. **The font and icon half of the same key
is not this gap** — it previews correctly, for free: `_paste_glyph` already
pastes a baked glyph tile as a mask, so a multi-grey-level (anti-aliased)
sheet blends into the background exactly the way `drawText` does on the
device, while a 1-bit sheet cannot, because its mask has only two values
(`tests/test_preview.py::
test_an_antialiased_icon_previews_with_intermediate_grey` confirms this end
to end, through a real design rather than against the baked sheet alone). For
the primitive gap, the simulator is authoritative.

---

## 3. What the linter does not check

The linter is this project's main claim to being better than hand-writing, so its
edges matter more than its coverage.

### Checks that are exact

Data-source spelling; palette legality; anti-aliasing legality on a 64-colour
panel (`antialias-dither` -- the same channel-quantization fact `palette-dither`
checks, reached from the other direction); geometry against the framebuffer and
the visible area (round and rectangle only); glyph coverage of a subsetted
font; contrast arithmetic. (There is no longer a refresh-tier check to list
here -- the tier concept itself was deleted; see §2 above.)

A `carousel` is the one element checked against its **drawn** extent rather
than its box, because its box is deliberately larger — it is the touch target.
Whether that target is *usable* is a separate check (`carousel-zone`), listed
below because half of it rests on a judgement.

**Per-device API availability is checked three ways, by two different
mechanisms, because the data supports only one of them in each case.**

*By symbol table, for `on_hold:` and for `config:`.* `check_hold_targets` resolves
`WatchFaceDelegate.onPress` against each target's own `<id>.api.debug.xml` —
the only honest way to answer it, since an API level settles nothing here: the
sibling symbol `onTap` is documented "since 5.1.0" and genuinely absent on
`fr955` at 5.2.0. (`onTap` is deliberately *not* consulted: it is documented
"Only available in WatchFace config mode" and never fires on a live face, so
checking for it would report a capability the author can never reach — see
`docs/research/07-carousel-interaction.md` §1.) `check_config_support` resolves
`WatchFaceConfig.getSettings` the same way, for the same reason: `fr955`
reports ConnectIQ 5.2.0, above the editor's own documented 5.1.0, and still
has no editor at all.

*By version comparison, for complications.* `check_complication_availability`
compares a type's `since` against the device's `Device.api_level`. This one
cannot use the symbol table: `COMPLICATION_TYPE_*` are constants, and
`api.debug.xml` carries only `<functionEntry>` symbols, so they do not appear
in it at all (checked directly, including for the universally-supported
`COMPLICATION_TYPE_BATTERY`). The comparison is exact — both numbers come from
files on disk, `Toybox/Complications.html` and the device's `compiler.json` —
but note that it answers "is this type old enough for this firmware", which is
a *different* question from "does this symbol exist here", and the `onTap` case
above is the standing reminder that the two can disagree.

What remains unchecked is ordinary data sources: `Device.has_symbol` is correct
and proven (`tests/test_devices.py` runs it against the real device files), and
no non-complication source consults it. See "Device gating for a source is only
partly enforced" below, the same gap from the catalogue's side.

### Checks that are explicitly weaker, and say so in their own output

| Check | What it actually knows |
|---|---|
| **Memory** | *Measured*, not estimated — but the figure is the **static foreground** total from `monkeyc --build-stats`. Resources loaded at runtime (fonts, bitmaps) add to it and are **not** measured. A face near the limit needs checking on device. |
| **Partial-update power budget** | **A heuristic, and now the only guard.** Garmin does not publish the numeric budget; the docs say only "strict limits". The check flags relative cost — clip area and operation count — and is labelled a heuristic until measured empirically against `onPowerBudgetExceeded`. Until the refresh-tier deletion (§2 above) this was backed by a hard, unsuppressible compile error barring `weather.*`/`complication.*` from `low_power`; that error is gone, so this suppressible heuristic is now the *entire* build-time defence against overrunning a budget whose overrun is **permanent**. Treat a warning here on a `low_power` element more seriously than its "heuristic" label alone would suggest. |
| **Text overflow** | Exact for a baked custom font (real glyph advances from the TrueType source). A system font (`FONT_TINY` and so on) is **always an estimate** — Garmin publishes each `FONT_*` symbol's pixel *height* per device and language, but not its per-glyph advances, and the real typefaces (Pridi, Roboto Condensed, Bionic, ...) are not available on the host or in the SDK. The estimate scales a real scalable stand-in face to the device's published height and measures per character (`wfb/fonts/fallback.py`), which is why it needs that per-device height to be correct in the first place — a flat 0.55 em/character coefficient is a last-resort fallback used only if even that stand-in face fails to load. Every system-font measurement is labelled `(estimated)` in the generated code regardless. |
| **Contrast** | The arithmetic is exact WCAG; the 3.0 threshold is a judgement call, which is why it is a warning and is suppressible. |
| **`graphics-pool`** | The pool size is exact (`graphicsResourcePoolSize`, straight from the device file) and so is the pixel count. **Bytes per pixel is not.** The SDK publishes no figure for a `BufferedBitmap`, so this uses the display's own `bitsPerPixel` as a proxy and ignores per-surface overhead; the check labels itself an estimate. It also does not account for the fonts and bitmaps the face loads at runtime, which share the same pool -- so the *fraction* it reports is a floor, not a total. |
| **`carousel-zone`, narrow-zone half** | Splitting the box into thirds is exact; the **40px minimum** each third is measured against is not a Garmin number — Garmin publishes no minimum touch size — so it is this compiler's judgement and the message says so. The other half of the check, whether a zone reaches under a round screen's bezel, *is* exact resolved geometry. |

### Suppression, and what it can reach

`lint: {allow: [<code>], reason: "..."}` on an element silences a suppressible
check for that element. Four of the suppressible codes are not element-scoped
diagnostics at all, so their suppression is scoped to the elements that *cause*
them rather than to an arbitrary one:

* **`palette-dither`** is about a `palette:` entry, and `palette:` is a flat
  mapping with nowhere to hang a `lint:` block. The allow is honoured on any
  element whose `color:` or `track_color:` is exactly `palette.<name>` — the
  match is on the author's own expression text, so an element that merely
  *mentions* the entry inside a larger conditional does not count. When no
  element references the entry that way, the warning says so instead of printing
  instructions that would not work.
* **`partial-update-budget`** is about the whole face's clip rectangle, so the
  allow is honoured on any element drawn in `low_power` mode -- the elements that
  the clip is computed from and that pay its cost.
* **`graphics-pool`** is about the one buffer the whole face shares, so the
  allow is honoured on the first element declaring `static: true` -- there is no
  per-group figure to acknowledge separately.
* **`antialias-dither`** is about the whole device's panel, not one element's
  colour, so the allow is honoured on the first element (in draw order) whose
  `antialias:` resolves to `true` on that device -- the same "one
  representative" shape `graphics-pool` uses, chosen the same way.
* **`config-unsupported`** is about the whole `config:` block, which -- like
  `palette:` -- is a flat mapping with nowhere of its own to hang a `lint:`
  block. Since a device with no editor keeps every declared default at once,
  one `allow:` anywhere among the elements it names suppresses it entirely --
  the allow is honoured on any element whose `color:`/`track_color:` is
  exactly `config.accent_color`, `config.data_color`, or one role of
  `config.colors.<role>`, the same exact-text match `palette-dither` uses and
  for the same reason. `palette-dither` reached through a `color_scheme:`
  role is scoped narrower, per-role like every other `palette-dither` case:
  the allow is honoured only on an element naming that specific
  `config.colors.<role>`.

`carousel-zone`, `dead-element`, `static-overlap` and the two `hold-*` codes are
ordinary element-scoped diagnostics, so `lint:` on the element itself reaches
them -- for `static-overlap`, on the element that ends up on top.

A code in `allow:` that this compiler does not emit, or that is deliberately not
suppressible, is now an **error** naming which of the two it is. Before that, both
were ignored without a word, and the author had no way to tell a typo from a
check that refuses suppression on purpose.

### `visible:` is a runtime fact, and the linter reasons about build-time geometry

A hidden element still **occupies its box** for every geometric check: safe
area, off-screen, text overflow, the `low_power` clip rectangle, the AMOLED
luminance estimate, and (once it exists) overlap. Two elements that are
`visible:` on mutually exclusive conditions, deliberately stacked in the same
place, will still be reported as overlapping when that check lands, and both
still count toward the clip.

This is a real limitation, not an oversight, and the alternative is worse: the
linter would have to decide whether two conditions can be true at the same time,
which is a satisfiability question over arbitrary expressions on readings whose
values are unknown at build time. Sizing the clip and the safe area for "every
element that *could* draw" is the conservative answer, and conservative is the
right direction for a budget whose overrun is permanent (§1). Suppress the
warning on the element with `lint: {allow: [safe-area], reason: "..."}` where the
overlap is intended.

The one thing that *is* folded is a condition with no readings in it at all:
`visible:` that reduces to a constant `false` is the suppressible `dead-element`
warning, reported once against the outermost dead element (a group's condition
is conjoined into its subtree, so warning per descendant would repeat one
mistake N times).

### A hold reaches an element that is not on screen

`on_hold:` on an element whose `visible:` is currently false still opens that
element's glance. The hit test lives in the generated `WatchFaceDelegate`, which
receives only the touch coordinates: it has no `Dc`, no frame, and none of the
hoisted reader locals `onUpdate` builds, so gating it would mean re-reading every
source the condition touches inside `onPress` — a second copy of the element's
read plan, in a second file, free to drift from the first.

It would also not buy correctness. `onPress` runs at touch time, not at draw
time, so a re-evaluated condition answers about a different moment than the pixels
the wearer is looking at; the two can disagree either way. The failure mode as it
stands is bounded and recoverable — a hold on an empty patch of screen opens a
glance, and back returns — so this is documented rather than gated. A `carousel`
is the same: its three hold zones stay live while the row is hidden.

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
* **Device gating for a source is only partly enforced** — ADR 0008's check
  2, the other half of "per-device API availability" above. Two of the three pieces
  are now built, and it is worth being precise about which:

  * **`on_hold:` is checked** -- `check_hold_targets` resolves
    `WatchFaceDelegate.onPress` against each target's own `api.debug.xml`.
  * **A `complication.*` binding, and an `on_hold:`/`launch:` naming a
    complication type, are checked** -- `check_complication_availability`
    (code `complication-gated`) compares that type's `since`
    (`wfb/complications.py`, from the SDK's own table) against the device's
    own `Device.api_level` (from its `compiler.json`), and warns, suppressibly,
    naming the device and both version numbers. `complication.sleep_score` on
    `fr955` -- ConnectIQ 6.0.2 required against a 5.2.0 ceiling -- is the case
    that motivated it and the one it currently catches.
  * **Ordinary data sources are still unchecked.** `catalog.Source.requires`
    (`Parent.name` symbols a binding needs on the target device) exists, is
    set on exactly one source (`device.do_not_disturb`), and is still read by
    nothing.

  Note that the complication check deliberately does **not** go through
  `requires`/`Device.has_symbol`, and could not: `has_symbol` indexes only the
  `<functionEntry>` symbols scraped out of `api.debug.xml`, and
  `COMPLICATION_TYPE_*` are constants that do not appear in that file at all
  (checked directly, including for `COMPLICATION_TYPE_BATTERY`, which every
  target supports). A version comparison is the only thing the available data
  supports. Whoever writes the `requires` check for ordinary sources should
  expect it to be a genuinely separate mechanism rather than an extension of
  this one.

  The runtime behaviour underneath all of this is unchanged and still correct:
  a device that lacks a type returns `null` from `valueOf`, `subscribe()`
  swallows both ways a device can decline, and the design renders as though
  the value were simply absent -- the same "absence is normal" contract every
  nullable source has. The check exists so that is a decision the author makes
  knowingly, rather than something discovered as a blank field on the wrist.
