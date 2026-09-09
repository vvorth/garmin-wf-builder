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
daylight arc would need. **One thing it still cannot express**, for want of an
element type rather than a data source:

| Dashboard has | Blocked on |
|---|---|
| A configurable history graph — HR, Body Battery, stress, pressure, elevation | no graph element **and** no history sources |

Weather's condition icon (`icon_for: weather.condition`, resolved on-device
through `WfbWeather.mc`, mirroring `wfb.icons.weather_icon_for_condition()`)
and its full reading set -- temperature, feels-like, today's high/low and
precipitation chance, humidity, wind speed -- both shipped; see
`docs/format.md`'s `icon_for` and "Data binding" sections. Body Battery
(`complication.body_battery`) and a daylight arc's sunrise/sunset data
(`complication.sunrise`/`complication.sunset`) also both shipped, all three
through `Toybox.Complications`, read the same way every other source is now
read -- a plain per-frame pull, see `docs/format.md`'s "Data binding" section
-- not a direct API field. Nothing in `examples/dashboard/` binds them yet;
that is an example-content update, not a platform gap. The history graph is
the one thing left, and it additionally needs an element type that plots a
series, which is the strongest argument in the codebase for the `raw` escape
hatch: a sparkline is exactly the sort of thing that should drop to
hand-written Monkey C rather than growing the schema.

| Missing | Where it is specified |
|---|---|
| `image` and `complication_slot` elements | ADR 0004. `complication_slot`'s "cycle through several readings" half shipped as `carousel`; what is missing is a slot whose *type* the wearer picks in the on-device editor, which needs the `config:` block below |
| The `raw` escape hatch to hand-written Monkey C | ADR 0007 |
| Per-device `overrides` (parsed and validated, not yet applied) | ADR 0004 §4 |
| The `config:` block, on-device config, phone settings | ADR 0006 |
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
fonts, arc cap shape, or the transflective panel's real appearance. For those the
simulator is authoritative.

---

## 3. What the linter does not check

The linter is this project's main claim to being better than hand-writing, so its
edges matter more than its coverage.

### Checks that are exact

Data-source spelling; palette legality; geometry against the framebuffer and the
visible area (round and rectangle only); glyph coverage of a subsetted font;
contrast arithmetic. (There is no longer a refresh-tier check to list here --
the tier concept itself was deleted; see §2 above.)

A `carousel` is the one element checked against its **drawn** extent rather
than its box, because its box is deliberately larger — it is the touch target.
Whether that target is *usable* is a separate check (`carousel-zone`), listed
below because half of it rests on a judgement.

**Per-device API availability is checked two ways, by two different
mechanisms, because the data supports only one of them in each case.**

*By symbol table, for `on_hold:`.* `check_hold_targets` resolves
`WatchFaceDelegate.onPress` against each target's own `<id>.api.debug.xml` —
the only honest way to answer it, since an API level settles nothing here: the
sibling symbol `onTap` is documented "since 5.1.0" and genuinely absent on
`fr955` at 5.2.0. (`onTap` is deliberately *not* consulted: it is documented
"Only available in WatchFace config mode" and never fires on a live face, so
checking for it would report a capability the author can never reach — see
`docs/research/07-carousel-interaction.md` §1.)

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
| **`carousel-zone`, narrow-zone half** | Splitting the box into thirds is exact; the **40px minimum** each third is measured against is not a Garmin number — Garmin publishes no minimum touch size — so it is this compiler's judgement and the message says so. The other half of the check, whether a zone reaches under a round screen's bezel, *is* exact resolved geometry. |

### Suppression, and what it can reach

`lint: {allow: [<code>], reason: "..."}` on an element silences a suppressible
check for that element. Two of the five suppressible codes are not element-scoped
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
  allow is honoured on any element drawn in `low_power` mode — the elements that
  the clip is computed from and that pay its cost.

`carousel-zone`, `dead-element` and the two `hold-*` codes are ordinary
element-scoped diagnostics, so `lint:` on the element itself reaches them.

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
