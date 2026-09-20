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
build time (`wfb/ir/model.py`'s `GRAPH_AREA_MAX_SAMPLES`) against `style: line`
as the named alternative.

### There is no rotated-primitive draw call, so analog hands rotate in Monkey C

`Toybox.Graphics.Dc` draws axis-aligned rectangles, circles, ellipses, arcs,
lines and polygons — nothing takes a rotation angle (checked in
`Dc.html` and every target's own `api.debug.xml`, `docs/research/probes/
analog-hands/`). An analog hand's shape and axis are still resolved to
whole pixels at build time (ADR 0004), but the hand's *angle* is the time,
so the device rotates the resolved vertices itself every frame — one
`sin`/`cos` pair per hand, via `runtime-lib/WfbHands.mc`. This is the one
piece of layout arithmetic this compiler lets the watch do (ADR 0004),
along with patterns below, and its CPU/battery cost is unmeasured (no simulator,
no watch in this container).

**No second hand while asleep.** Showing one would need `onPartialUpdate`
with a clip that moves with the hand every second, repainted from a
full-frame buffer redrawn every minute — a different buffer architecture
from `static:`'s paint-once one, and not built (`seconds: always` is a
friendly "not implemented yet" error; see §2 and plan 04 §11). `seconds:
awake` (the default) hides the second hand while asleep instead; `seconds:
never` drops it entirely.

**No sweep**: the face redraws at most once a second, same as everything
else here. **Four primitives only** (`polygon`/`rectangle`/`line`/`circle`)
— no rounded-rectangle, ellipse or arc hand parts, no bitmap hands, and no
outlined polygon (the same "no `drawPolygon`" limit above). **Coordinates
resolve to whole pixels in the hand's own frame**, so a hand thinner than
about 2 px may lose its taper. **Edges of a rotated polygon alias on a
64-colour MIP panel** — `antialias:` is the lever, with the usual
`antialias-dither` tradeoff (`examples/features/analog/`'s `classic` layout pulls
it), and what it looks like is unobserved: `wfb preview` draws hands
aliased either way. **Hand
colours cannot read data**, only palette, literal and `config.*` — a hand
has no `when_absent:`. **12-hour dial only**: the hour hand turns twice a
day; there is no 24-hour (GMT) hand. **Hands cannot be held** (`on_hold:`
is not a key on `type: hands`), although a `group` around them can be.

**Patterns turn in Monkey C too** (`type: pattern`, plan 05).
A radial pattern's copies are the build-time-resolved template rotated on
the watch, one `sin`/`cos` pair per copy, and a linear pattern's are
translated by a whole-pixel step. Both go through the same
`runtime-lib/WfbGeom.mc` helpers hands use. Baking the copies instead was
measured and costs roughly 30x more of the 128 KB budget
(`docs/research/probes/pattern-cost/`). The time is paid once for a
pattern in `static:`, and once a frame for one outside it. That per-frame
cost is unmeasured. How the firmware rasterises the Float coordinates of a
turned copy without anti-aliasing is unobserved, the same open question
hands have.

- **Parts:** the hands' four primitives, an `arc` centred on the pattern's
  centre, and `text`.
- **Text parts:** a bitmap font cannot turn, so by default only the anchor
  turns or steps. `WfbGeom.rotatedX`/`rotatedY` round the transformed point
  half up and the glyphs are drawn upright. They are two 5-argument helpers
  because Connect IQ 3.x devices (`fenix6`, `fenix6xpro`, `fr245`) reject a
  method with more than 9 parameters (`docs/lore/monkeyc.md`;
  `tests/test_parameter_limits.py` guards it). The value may read only
  `copy`, so every copy's string is known at build time. The per-copy
  `formatting.emit` call on the device is unmeasured, and costs nothing
  inside `static:`. **A `shape: text` part can now turn too** (plan 11
  slice 2, `docs/plans/11-vector-text.md` §5), the same way a `text`
  **element** already could (below, "A face cannot ship its own TTF, and
  vector fonts are Garmin's only"): give the part a device-resident `face:`
  font and its own `curve:`. The one thing genuinely different from a
  standalone element is the angle's frame — a pattern part's `curve.angle`
  is authored once, in the **template's own local frame** (for copy 0), and
  a radial pattern composes it with each copy's own rotation at codegen/
  preview time, the same way a pattern `arc` part's `start_angle:` already
  composes with `start:`/`step:` — so twelve hour numerals, each tangent to
  its own radius, are one authored angle (`curve: {style: angled, angle:
  0deg}`), not twelve. A linear pattern never rotates, so its copies simply
  keep the part's own angle unchanged. `docs/format.md`'s ["Text
  parts"](format.md#text-parts) has the full rules and the worked example.
- **Colours** may read `copy` (the index of the copy being drawn) and any
  source that is never absent, such as `date.weekday`. `examples/features/patterns/`'s
  row of dots lights today's this way. They may read a source that **can**
  be absent only when the pattern has `when_absent: hide`: absence then
  hides the whole pattern, checked once per frame before the loop.
- **Part `visible:`** is a boolean expression evaluated per copy, with `copy`
  bound as in a colour, and hides just that part for that copy
  (`examples/features/patterns/`'s `test_visibility`).

The device cost of the per-copy colour, the per-frame absence check and the
per-copy `visible:` is unmeasured.

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

### The memory limit is per device (48 KB – 1 MB), and 28 devices cannot run a watch face at all

A watch face gets **131 072 bytes** on the three verification devices — one
sixth of the 786 432 bytes the same hardware gives a watch app — but that
figure is **not** the platform's. Across the 136 documented devices that can
run a face, 62 are at 131 072 B, 38 at 98 304 B, 19 at 65 536 B, 10 at
524 288 B, and the floor is **49 152 B**: a 21× spread. A design that is
comfortable on a fēnix 8 may not fit on the 21 devices at or below 64 KB, so
check `--build-stats` on each device actually named in `targets:`. Of the 164
documented devices, **28 cannot run a watch face at all**.

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

### A face cannot ship its own TTF, and vector fonts are Garmin's only

An author's typeface is **always** rasterised to a bitmap sheet at build time.
Connect IQ has no way to carry an outline font inside a `.prg`: a `<font>`
resource accepts only a BMFont `.fnt`, and no API anywhere loads font bytes.

`Graphics.getVectorFont` (API 4.2.1) draws scalable text at any pixel size,
but only from faces **already on the watch** — about 14 Latin faces, of which
only `RobotoCondensedBold`/`Regular` is widely present, on **44 of the 136**
watch-face-capable devices. That reach is a limitation in its own right, not
just a stepping stone to something wider: the catalogue cannot be extended,
so the typefaces this project's own examples use (Chivo Mono, Dynalight,
Questrial) can never be vector fonts, and a design that leans on one has
opted out of most of the fleet by construction, whatever `if_unavailable:`
it chooses.

`Dc.drawAngledText`/`Dc.drawRadialText` accept scalable fonts only and
explicitly refuse resource fonts, so **text drawn with an author's baked
font still cannot be rotated or curved, and never will be** — that part of
the practical consequence is permanent. What *is* built (plan 11,
`docs/format.md`'s `curve:` section): a `fonts:` entry can name a
device-resident face instead of baking one (`face:` instead of `source:`),
and a `text` **element**, or a pattern's own `shape: text` part (slice 2),
can bend it along a line (`style: angled`) or around a circle (`style:
radial`). Two honest limits on that, not to be glossed over:

* **`if_unavailable: error` is a build-time guarantee only.**
  `Graphics.getVectorFont` returns `null` rather than throwing, and the
  platform offers no way to fail at runtime, so the generated code *always*
  null-checks before drawing and a null font simply draws nothing —
  identically in `error` and `hide` mode. `error` guarantees a usable face
  was published at build time on every target; it does not, and cannot,
  guarantee the element is never missing from the wrist.
* **The radial glyph-facing model is unverified.** `wfb preview` draws
  `curve: {style: radial, direction: clockwise}` facing glyphs outward and
  `counter_clockwise` facing inward, inferred from standard text-on-a-path
  convention and from Garmin's own `TrueTypeFontsRadialText.mc` sample
  demonstrating both direction constants at one fixed angle — a
  well-reasoned model, not a confirmed one: the SDK prose does not document
  glyph facing, and the simulator does not run in this environment (below,
  "The simulator crashes when an app is pushed"), so nothing here has been
  checked against a real device or simulator.

It is *not* a memory limitation either way — a baked sheet loads into the
separate graphics pool, not the watch-face budget (measured in
`docs/research/probes/vector-fonts/`). Full analysis:
`docs/research/12-vector-fonts.md`. §2's "Text parts" bullet above has the
pattern-part-specific rules (the local-angle-composed-with-the-copy design).

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
`FONT_NUMBER_HOT` and the rest — is already rasterised on the device, so there
is nothing to rebake and no way to offer the same guarantee. A clock in a
system font jitters exactly as much as that font's own figures do. `wfb`
measures that width with the device's own font file when Garmin's fonts are
installed (exact for a `.cft` bitmap font), and otherwise against a free
stand-in or Pillow's default face, so how much it jitters is only as good as
the text-overflow check (§3, "Text overflow").

Deliberately not offered, on either kind of font: a *vertical* equivalent of
`align:`. Baseline and line height are the font's own metrics and are what make
a line of text sit together; a `text` element's `vertical_align:` already says
where that line goes.

### A font's `size:` cannot be `%` or `pt`, and is not normalised to ink height

`fonts.<name>.size` takes a `px`/`%r` length (`docs/format.md` §Fonts), and not
the other two units the coordinate model has. This is a real
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

`icon:` accepts any single character from the Nerd Fonts icon font directly, not
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
**+27 B data, +183 B code** on a real design (the since-removed `examples/static/`, 2,769 B ->
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

Anti-aliasing a `shape`, `progress`, `graph` or `hands` element (`antialias:`,
`docs/format.md`)
manufactures exactly the intermediate values this rule is about: a soft edge
is a blend, by construction, and every value in between is off the 64-colour
grid. `lint.check_antialias_palette` (`antialias-dither`) says so once per
device, against the first element that draws anti-aliased, and is
suppressible — an author who wants the softer look on a MIP panel is
accepting dithering at the edge on purpose. All three of this project's
current targets are 64-colour, so this fires on every face that turns the
feature on for any of those elements. (What `wfb preview` shows for
that same soft edge is a separate gap — see "the simulator does not run in a
headless Linux container" below.)

### On-device configuration: four axes, four configurations, and not on fr955

The native watch-face editor is **API 5.1.0, fēnix 8 and newer**, and exposes
exactly four axes: Styles, complication slots, **one** data colour and **one**
accent colour. At most **four saved configurations** per face. There is no
per-element colour editing and no arbitrary data rebinding.

**All four axes are implemented, as `config:`** (`docs/format.md`
"Configuration"; ADR 0006 §1): the two colour axes,
**Styles**, which carries no colour of its own but is the only axis Garmin
gives no meaning to at all — a declared `color_scheme:` (a named role ->
colour set) rides it as `config.colors` — and **Data**: `config: data:`
declares named complication slots, and `type: complication_slot` draws one,
choosing its icon on-device from the wearer's picked *type* alone. A slot
also accepts `on_hold: auto` (only), opening whichever glance the wearer's
*current* pick belongs to, and the editor's own **animated highlight** on a
slot (`AppBase.onStart`'s edit-mode flag, `WatchFaceDelegate.onTap` +
`setSelectedComplication`, `getComplicationDrawable` returning a generated
`SlotDrawable`) is built and emitted automatically for any design with at
least one `complication_slot` element — see §2 below for what "built" does
and does not mean here.

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

**The Data axis shipped as `config: data:` + `type: complication_slot`**
(`docs/format.md` "Configuration → The Data axis";
`docs/research/09-data-library-and-config-axes.md`,
`docs/research/probes/config-axes/`). What the research settled, and what is
still true of the shipped feature:

* **The Data axis can never hold author-defined content.** `<complication>`'s
  children are `Complications.COMPLICATION_TYPE_*` values or `allowAny`, per
  `resources.xsd`. Author-defined selectable content rides **Styles** instead
  (`color_scheme:`/`config.colors` is exactly this, spent on a colour scheme
  rather than arbitrary content), whose `styleId` Garmin gives no meaning to
  -- and which is a *single* number, so several independent author-defined
  axes multiply into one flat list.
* **There is no way to ask which saved configuration is active.**
  `getSettings(null)` returns the active `Settings`, which carries no id, and
  `Id` exposes only `equals`. So the four axes are per-configuration while
  anything the face persists itself (`Application.Storage`, properties) is
  global across all four of the wearer's saved faces.
* **`getComplicationDrawable` -- the editor's animated highlight -- is now
  built**: a generated `<Face>SlotDrawable` per face delegates straight back
  to the view's own per-slot draw method, so there is exactly one
  implementation of what a slot looks like, and the view hides the slot the
  editor is currently animating (a private `_pulsing` field, checked at the
  top of every `complication_slot`'s draw method) — the SDK sample's own
  comment on this exact hazard ("This prevents the complication from being
  drawn on the watch face while it is pulsing") is what makes this mandatory,
  not optional. Measured on `examples/features/slots/face.yaml` at a fixed path,
  `fenix8solar47mm`: the editor machinery alone (no `on_hold:`) costs +161 B
  data / +693 B code over the same design without it; `on_hold: auto` on one
  slot adds a further +9 B data / +90 B code on top of that. **No behaviour
  of any of it is verified** — whether the highlight actually animates,
  whether it lines up with what is drawn, and whether `onTap`'s hit regions
  read correctly on a real touchscreen are all UNVERIFIED (no simulator in
  this container, no watch — §2 below). What is verified: it compiles
  warning-free on every target, including `fr955`, which has no editor at
  all and never calls any of it.
* **A slot's icon is chosen on-device from the wearer's picked *type* alone**
  (`Complications.Id.getType()`), not from the current *value* -- so a type
  whose icon depends on its value (the weather-condition complications:
  `current_weather`, `forecast_weather_*day`) draws one fixed, type-keyed
  icon (`wfb.icon_catalog.CATALOG["weather"]`) rather than the value-keyed
  condition icon `icon_for: weather.condition` resolves on-device -- that
  remains future work. Every other native type has a catalogue icon
  (`wfb.icons.COMPLICATION_ICON` covers all 42), an
  author can override any choice's icon per-design (`choices:`'s
  mapping-form `icon:`/`glyph:`/`icon: none`, plan 03 §6.1/§6.2), and
  `icon_position:`/`icon_gap:`/`icon_color:` place, space and colour it (plan
  03 §6.1/§6.3) -- `docs/format.md`'s "The Data axis" has the full account.
* **`choices: any` + `icon_size:` is accepted.** A Connect IQ-app
  complication picked there draws no icon.
* **monkeyc 9.2.0 crashes on two different string literals with the same
  Java hash code** (`docs/lore/toolchain.md`). The compiler rewrites a
  colliding `IconGlyphs` glyph to `Number.toChar` at runtime, and reports
  any other collision as a `string-label` build error. The known remaining
  case is two static `icon` elements whose glyphs collide (for example
  `distance` and `temperature`); change one of them. **Unverified on a
  device:** that a `toChar`-built supplementary-plane glyph draws
  correctly.
* **A slot's geometry lints are sized from its value alone, never `label:`/
  `unit:`.** Both are localised device strings with no documented upper
  bound; padding for them was tried and produced a spurious `off-screen`
  **build error** on an ordinary slot (confirmed directly), which is worse
  than the gap it would have closed. `docs/format.md`'s "What this compiler
  cannot tell you" records this the same way this file does.

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
clock, the conditional colours, the badge and the arcs, the weather row's
icon and every one of its readings, Body Battery, and the data a daylight arc
would need. `type: graph` plots a series, so what remains blocked is a
data-source gap rather than a layout one:

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
| `image` elements | ADR 0004 |
| The `raw` escape hatch to hand-written Monkey C | ADR 0007 |
| Per-device `overrides` (writing one is an error, not a silent no-op) | ADR 0004 §4 |
| Phone-side settings (`settings.xml`/`properties.xml`) | ADR 0006 §1 -- the one piece of it still unbuilt, and the only route that would give `fr955` any configuration at all. Frozen, incomplete, on `wip/phone-settings` |
| `layouts:` **form B** (an element-level membership key/list, as opposed to the container form A ships) | plan 02 (deleted once built; `git show a645d64:plan 02`) §4.3 -- explicitly declined by the user (§12 decision 1); there is no plan to build it |
| A `complication_slot` inside a `layouts:` body | plan 02 §12.5 -- a build error by design, not a gap: the Data axis is face-wide, so a slot stays in the shared top-level `elements:` only |
| Per-layout fonts, or a per-layout `onPartialUpdate` clip | plan 02 §6.8, §5.6. Every layout's fonts load in `onLayout` regardless of which is active (measured, not assumed to be a problem); `resolved.clip_for("low_power")` unions low-power elements across *every* layout, conservatively -- see that method's own docstring in `wfb/layout.py` |
| Moving a per-frame data-source read inside its own layout's guard (only the draw calls are guarded; every read still runs every frame) | plan 02 §6.4 -- a later optimisation, only worth doing if measured |
| The fr955 `excludeAnnotations` strip for an unreachable layout's compiled-in code | plan 02 §6.8 -- needs a probe, only worth doing if fr955 runs short of memory |
| `segments` and `scale` progress styles | ADR 0004 §1 |
| Automatic unit conversion (`units: auto`/`metric`/`statute`, metres->km/mi, m/s->pace) | ADR 0005 §4 states this as framework-owned; no `units:` schema property or conversion code exists at all. `examples/dashboard/face.yaml`'s `activity.distance / 100000.0` is an author doing by hand exactly what this was meant to spare them |
| `wfb install`, `package`, `migrate`; the GUI | brief, Phase 3 |
| Catalogue generation from the SDK (the table is hand-written for now) | ADR 0005 §1 |
| SDK-version recording and device-database mismatch warning | ADR 0009 §4 |
| ADR 0008's check 2, **unsupported API for a targeted device**, for anything other than `on_hold:` | `on_hold:` resolves `WatchFaceDelegate.onPress` against each device's own symbol table, so the machinery is live — but `catalog.Source.requires` still consults nothing; §3 below has the detail |
| `mypy --strict` in CI, ADR 0001's stated mitigation for Python's lack of compile-time exhaustiveness checking over IR node types | ADR 0001 -- there is no CI configuration anywhere in the repo, and `mypy` is not even in `requirements-dev.txt` |
| `seconds: always` (a second hand while asleep) | plan 04 §11 -- needs a full-frame buffer repainted every minute plus a per-second `onPartialUpdate` clip around the hand's own bounding box, a different buffer architecture from `static:`'s paint-once one; refused with a friendly error, not a schema enum message |
| `arc` hand parts | plan 04 §11 -- would need the start angle to rotate with the hand too |
| Data-driven hand colours | plan 04 §11 -- a hand has no `when_absent:` to fall back through if the bound reading were absent |
| A gauge needle (an author-expression angle, not the clock) | plan 04 §11 -- the rotation machinery is the same as an analog hand's; the format question (one authored angle vs. three fixed clock formulas) is not |
| 24-hour (GMT) hands; a minute hand that creeps with the seconds | plan 04 §11 |
| `wfb new -t analog` template | plan 04 §11 |
| A pattern `text` part whose `value:` reads data (a data source, `palette.*` or `config.*`) | plan 06 §6 D3 -- every copy's string must be known at build time for the font's glyph subset and the pattern's extent, and a reading would need `when_absent:`. Text parts reading only `copy` are built |
| `pattern: grid` (rows × columns) | plan 05 §9 D5 -- two nested linear steps; nothing has asked for it yet |
| Per-copy variation other than `skip:`/`skip_every:`, colour and visibility | plan 05 §9 D5 -- a longer or differently-shaped copy is a second pattern element today |
| `on_hold:` and `low_power` on a `pattern` | plan 05 §5.1, §5.4 -- hold a `group` around it; a fixed pattern gains nothing from `onPartialUpdate` |
| `rounded_rectangle`/`ellipse` parts in a linear pattern, and an `arc` part off the pattern's centre | plan 05 §9 D3/D5 -- a linear pattern could draw both untransformed, and was kept to one part vocabulary instead |
| A true typographic-baseline value for `vertical_align:` (glyph ascent, so a descender like the tail of a "g"/"y" hangs below it) | plan 07 §6 choice 1 -- `bottom` is the line box's bottom (ascent + descent); a real typographic baseline would need a new value |
| Element-level alignment of a *linear* `pattern`'s drawn-ink box (as opposed to its `at:`, which is a pivot every copy steps from, and already refuses `align:`/`vertical_align:` outright) | plan 07 §6 choice 2's alternative -- useful for aligning a whole row, but left unbuilt because it would make a pattern's `at:` mean two different things (the step origin, and the row's own box) |

**None of `layouts:`/`config: style:`'s on-device editor *behaviour* is
verified anywhere in this project** (plan 02 §9,
the same standing "no simulator in this container, no watch" caveat every
`config:` feature in this table carries): whether the editor lists a
`<style>` entry's label and previews it live as the wearer scrolls, whether
the static buffer repaints promptly on a style edit, and whether a
layout-scoped `on_hold:` hit region reads correctly on a real touchscreen
are all open questions. What *is* verified is what this project always
verifies for a feature like this: a warning-free real `monkeyc` build on
all three targets, the measured `--build-stats` figure, and `wfb preview
--style`/`--all-styles` rendering from the same resolved geometry the
generated code draws from.

**Every source is a plain per-frame read; there are no refresh tiers or TTL
caches.** Every value comes from a Garmin API that caches on its own side
(`Toybox/Weather.html`'s `getCurrentConditions()` is "get the most
**recently cached** weather conditions"), so a cache inside the 128 KB budget
would buy nothing (`docs/format.md`'s "How data is read"). So a `weather.*` or
`complication.*` binding may be used from a `low_power`/`always_on` element;
that is the author's responsibility, backed only by the suppressible
`partial-update-budget` warning (§3 below, `docs/format.md`'s "Modes").

**Complications are read by pull, not by subscription callback**:
`WfbComplications.valueOf` is called from `onUpdate` exactly like any other
reader, cast to the source's declared type because `Complication.value` is a
union type. A subscription is still registered once per bound type in
`onLayout`, but only to call `WatchUi.requestUpdate()` on change -- it is not
a cache. Whether a pulled value would *stay* fresh with no subscription at all
is **unverified** (no working simulator, "The simulator crashes when an app is
pushed" below). All 42 `COMPLICATION_TYPE_*` values are data sources under
`complication.*`; nine older path names (`body_battery.current` and others)
raise a `source-renamed` build error naming the replacement (`docs/format.md`'s
"The `complication.*` namespace", `WfbComplications.mc`).
`complication.sleep_score` needs ConnectIQ 6.0.2, above `fr955`'s 5.2.0
ceiling, so it never updates there (below, "device gating for a source is not
enforced").

### Screen shapes

Only `round` and `rectangle` have safe-area geometry. `semi-round` and
`semi-octagon` are **unsupported targets rather than silently wrong ones**: the
geometry check reports "not checked" instead of guessing.

### The simulator crashes when an app is pushed

`wfb simulate` works where the Connect IQ simulator does, and so far that is
nowhere: the simulator's app-load path is broken in this SDK build, in every
environment tried, container or real desktop. It is a GUI application, and on
Linux it links against `libwebkit2gtk-4.0`, `libsoup-2.4` and
`libjavascriptcoregtk-4.0`, which current distributions no longer ship.

Supplying them is not enough. On an `ubuntu:22.04` base — which still
packages all three natively, so every one of the simulator's 27 otherwise-missing
shared libraries resolves — the simulator **starts**: it opens its window under
Xvfb and sits there. It then **segfaults the moment a `.prg` is pushed to it**
with `monkeydo`, which is the "on app load" failure, and it does so with an
unmodified SDK sample `.prg` — an environment limitation, not a property of
generated faces.

The faulting frame is on a worker thread the simulator spawns during app load,
**entirely inside its own stripped executable**; GTK, WebKit and JavaScriptCore
appear nowhere on the stack. `libGL` is not among the loaded objects at all, so
this is not a software-OpenGL problem. Ruled out by direct test, each varied on
its own: `/dev/shm` at 64 MB and at 2 GB; Docker's default seccomp profile and
`--security-opt seccomp=unconfined`; running as uid 1000 and as root; the device
definitions mounted read-only and copied in writable; and WebKit's
`DISABLE_COMPOSITING_MODE` / `DISABLE_SANDBOX` escape hatches.

**It is not a container or distro artifact.** On a real Ubuntu 22.04 desktop
(Xwayland, no Docker, no Xvfb) the window genuinely renders, and `monkeydo`
still segfaults it at the byte-identical crash, across two devices and two
example faces, with `GDK_BACKEND=x11` and WebKit's JIT env vars set. Under an
Ubuntu 20.04 container (glibc 2.31, before `libpthread` was folded into
`libc`) it crashes identically too. Full account in
`docs/research/probes/simulator/README.md`.

`wfb preview` is the answer: it renders from the same resolved geometry the
generated code uses, so the two cannot disagree about position. What it does
*not* claim to reproduce is glyph rasterisation for system fonts (except
`.cft` bitmap fonts, drawn from the device's own glyphs), arc cap shape, the
transflective panel's real appearance, or — a deliberate scope decision —
**a `shape`/`progress`/`graph`/`hands` element's own anti-aliasing**
(`antialias:`, `docs/format.md`):
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
font; contrast arithmetic; a relative length resolving below 1 px with
`min_1px:` off (`sub-pixel-length` -- resolved device geometry, not an
estimate, same as the safe-area/overlap checks).

**Per-device API availability is checked by symbol table, by version
comparison, and by module/field lookup, because the data supports only one
of them in each case.**

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

*By module and field, for every catalogue path.* `wfb/availability.py`
resolves *any* catalogue path (`value:`/`color:`/etc, not just
`complication.*`) against a target device's own `api.debug.xml` for a missing
`Toybox` **module** (`Device.has_module`) or a missing **field**
(`Device.has_field`, bare-name matched -- exact when the name is absent,
approximate when present, since the symbol table records no owning class;
see that method's own docstring). The generalised lint, `check_api_gated`
(code `api-gated`), reports these
per element per device, folded together with the existing complication-type-
since check so each gap is reported once, at its most fundamental cause (a
missing module subsumes a too-new type; `hold-unsupported` subsumes a
missing module too, when the device also lacks `onPress` -- "the hold never
fires" is true either way). **`config-unsupported` is the one exception,
deliberately not deduped:** a `config.data.*` slot's own declared default is
itself read through `Toybox.Complications`, so on a device that lacks that
module as well as the editor (fenix6, fenix6xpro, fr245 today),
`config-unsupported`'s "keeps its declared default" claim would be false for
that slot -- the default cannot resolve either, so the slot shows its absent
state instead. Both warnings fire there, each naming a genuinely different
fact, and `check_config_support`'s own wording is adjusted per-slot to say
so rather than repeating the (here false) "keeps its default" line.
`manifest.xml`'s `minApiLevel` stays at the
generator's own base floor (`3.2.0`) regardless -- it is one number shared by
every target device in a build, so a per-feature bump would lock out any
device that never touches the feature (`docs/research/probes/api-gating/`). A device missing something a design
binds gets a runtime `has`-guard in the shared generated view instead
(`wfb.availability.compute_guards`, `wfb/emit/monkeyc/`), and the binding
simply reads as absent there.

**What this still does not cover: a missing *function* symbol.** The
generated code only ever guards a module or a field at runtime -- there is no
guard for an individual function (`Reader.requires`/`Source.requires`'s own
namespace). If `wfb.availability.source_unavailable` ever reports a function
gap, `check_api_gated` raises it as a build **error**
(`api-gated-unguardable`), not a warning, because the call would otherwise
run unguarded and crash on that device. No device this project vendors
triggers it today -- every reader's function symbol is present on every
installed device -- so it is only exercised with a stubbed device in tests.

**The bare-field-name approximation is a real, if currently unrealised,
risk.** `Device.has_field` cannot tell two different classes' same-named
fields apart (its docstring's own caveat); every field this project's
catalogue currently binds happens to be unique enough among installed
devices that this has not produced a false positive, but a future catalogue
entry is not guaranteed the same luck.

**Runtime behaviour on a real sub-4.2.0 device is unverified in this
container.** The simulator cannot run here (§3), so "a device without
`Toybox.Complications` silently treats `Toybox has :Complications` as
`false` and does not crash merely importing the module or referencing its
type in an annotation" is the SDK docs' documented idiom, not an observed
fact on real hardware -- confirm in the host simulator (or on a real
`fenix6`/`fr245`) before relying on it for a face that must work there.

### Checks that are explicitly weaker, and say so in their own output

| Check | What it actually knows |
|---|---|
| **Memory** | *Measured*, not estimated — but the figure is the **static foreground** total from `monkeyc --build-stats`. Resources loaded at runtime (fonts, bitmaps) add to it and are **not** measured. A face near the limit needs checking on device. |
| **Partial-update power budget** | **A heuristic, and now the only guard.** Garmin does not publish the numeric budget; the docs say only "strict limits". The check flags relative cost — clip area and operation count — and is labelled a heuristic until measured empirically against `onPowerBudgetExceeded`. Until the refresh-tier deletion (§2 above) this was backed by a hard, unsuppressible compile error barring `weather.*`/`complication.*` from `low_power`; that error is gone, so this suppressible heuristic is now the *entire* build-time defence against overrunning a budget whose overrun is **permanent**. Treat a warning here on a `low_power` element more seriously than its "heuristic" label alone would suggest. |
| **Text overflow** | Exact for a baked custom font (real glyph advances from the TrueType source). A system font (`FONT_TINY` and so on) is measured with the device's own font file when `vendor/fonts/` holds Garmin's fonts: a `.ttf` scaled to the device's published metrics (`wfb/fonts/fallback.py`), or on the fenix 6/7 family, fr245 and fr255 a decoded `.cft` bitmap font, exact to the pixel (`wfb/fonts/cft.py`). Without them it is **an estimate** against a pinned free stand-in (`exact`/`family`/`substitute` match, `docs/research/10-system-fonts.md`), then Pillow's default face, then a flat 0.55 em/character. Every system-font width is labelled `(estimated)` in the generated code regardless. UNVERIFIED for `.cft` devices (`docs/research/10-system-fonts.md` §10.6–10.7): whether `getFontHeight` reports the file's `height` or `height − 1`, whether the simulator quantises the antialias blend to the 64-colour palette, and which glyph an unmapped character draws (glyph 0 is assumed). |
| **Contrast** | The arithmetic is exact WCAG; the 3.0 threshold is a judgement call, which is why it is a warning and is suppressible. |
| **`graphics-pool`** | The pool size is exact (`graphicsResourcePoolSize`, straight from the device file) and so is the pixel count. **Bytes per pixel is not.** The SDK publishes no figure for a `BufferedBitmap`, so this uses the display's own `bitsPerPixel` as a proxy and ignores per-surface overhead; the check labels itself an estimate. It also does not account for the fonts and bitmaps the face loads at runtime, which share the same pool -- so the *fraction* it reports is a floor, not a total. |

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
  block. It is one combined warning per device regardless of what each axis
  actually does there -- keep a compiled-in default (colours, and a slot on
  a device that still has `Toybox.Complications`) or show as absent (a slot
  on a device that also lacks it, see "Per-device API availability" above) --
  so one `allow:` anywhere among the elements it names suppresses it entirely --
  the allow is honoured on any element whose `color:`/`track_color:` is
  exactly `config.accent_color`, `config.data_color`, or one role of
  `config.colors.<role>`, the same exact-text match `palette-dither` uses and
  for the same reason. `palette-dither` reached through a `color_scheme:`
  role is scoped narrower, per-role like every other `palette-dither` case:
  the allow is honoured only on an element naming that specific
  `config.colors.<role>`.

`dead-element`, `static-overlap`, the two `hold-*` codes and
`sub-pixel-length` are ordinary element-scoped diagnostics, so `lint:` on
the element itself reaches them -- for `static-overlap`, on the element
that ends up on top; for `sub-pixel-length`, on the element even when the
finding is actually about one of its hand/pattern **parts**, since a part
has no `lint:` block of its own to hang an `allow:` on.

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
glance, and back returns — so this is documented rather than gated.

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
  2. Modules, fields and complication types are checked and runtime-guarded
  ("Per-device API availability" above). Two gaps remain:

  * a missing reader *function* symbol (as opposed to a module or a field)
    has no runtime guard, so it is a build error rather than a warning;
  * `catalog.Source.requires` (`Parent.name` symbols a binding needs) is set
    on exactly one source (`device.do_not_disturb`) and read by nothing.

  The complication check does **not** go through `Device.has_symbol`, and
  could not: `COMPLICATION_TYPE_*` are constants, absent from
  `api.debug.xml`'s `<functionEntry>` symbols (checked directly, including
  for `COMPLICATION_TYPE_BATTERY`), so a version comparison is the only thing
  the data supports.

  Underneath, a device that lacks a type returns `null` from `valueOf`,
  `subscribe()` swallows both ways a device can decline, and the design
  renders as though the value were simply absent -- the same "absence is
  normal" contract every nullable source has. The check exists so that is a
  decision the author makes knowingly.
