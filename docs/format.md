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

One caveat, because it will bite you the first time: the schema describes the
**list form** of `elements:`. The equally-valid mapping form
([below](#two-ways-to-write-a-list-of-elements)) is rewritten by the compiler
before the schema ever sees it, so an editor validating against the schema
alone will mark a mapping-form file invalid. `wfb validate` is the authority,
not the editor.

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
static:   [...]        # optional: elements that never change -- see below
elements: [...]        # a list, or a mapping keyed by element id -- see below
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
    size: 18%r                            # or 68, or 12px -- see below
    glyphs: "0123456789:"                 # optional -- see below
    antialias: false
    monospace: false                      # one cell width for every glyph
    align: center                         # where the ink sits in that cell
```

The compiler rasterises the TrueType source into a BMFont sheet at build time,
per device.

### `size:` has two spellings

| Written | Means | Per device |
|---|---|---|
| `size: 18%r` | 18% of **this device's own minor radius** | 23 px on a 260×260 screen, 25 px on a 280×280 one |
| `size: 12px` | exactly twelve pixels | 12 px everywhere |
| `size: 68` | 68 px **on the smallest target**, scaled from there by the ratio of minor radii | 68 px on 260×260, 73 px on 280×280 (unless `scale: false`) |

**Prefer `%r`.** It says the thing a design actually means — "this font is a
fixed fraction of the dial" — directly, per device, in the same unit `at:`,
`radius:` and an `icon`'s `size:` already use. The bare number says it
indirectly, by naming a size on a *reference* device the declaration never
mentions: change the target list so a smaller screen joins it and every
bare-number font in the design silently rebakes.

The bare number is not deprecated and its meaning has not moved — designs are
written against it, and `scale: false` still pins it to a literal pixel count
on every device.

* **Only `px` and `%r` are allowed.** `%` is of a parent box and `pt` is of a
  font, and a sheet is rasterised before any element is placed — there is no box
  yet, and for a font's own size `pt` would be measuring against itself. Both
  are a build error naming `%r`.
* **`scale:` may not be combined with a length.** The unit has already said
  whether the size is per-device; `scale:` is only meaningful for the bare
  number, which needs a reference device to scale away from.
* **A font's declared size is the nominal em size**, handed to the rasteriser as
  written. It is deliberately *not* normalised to a measured ink height the way
  an `icon`'s `size:` is: an icon draws one glyph on its own, where ink height
  is the whole of what a size can mean, while a typeface's characters are drawn
  against a shared baseline and their relative proportions are the point.
  See `wfb/icons.py`'s `bake_size` docstring for the full reasoning.

### `monospace:` stops a clock from jittering

```yaml
fonts:
  clock:
    source: assets/OpenSans-Regular.ttf
    size: 22%r
    monospace: true
    align: center      # or left, or right
```

`monospace: true` bakes **every glyph at the same advance** -- the widest the
baked set needs, and never narrower than the widest ink. Nothing changes at
runtime: the device simply reads those advances out of the `.fnt`.

Why it matters: a centred clock in a proportional face **moves as its digits
change**. Measured on Open Sans at 33 px, `Fri 11:11` is 111 px wide and
`Wed 00:00` is 125 px, so a centred element shifts seven pixels between two
Fridays. Monospaced, both are 217 px and every character sits in the same
column it sat in a second ago.

* It works on a **proportional source as well as a monospaced one**, because
  the cell is measured from the glyphs actually baked rather than read off the
  font's own `post` table. A face whose figures are already tabular (Open Sans
  is one -- every digit is exactly the same width) still gains a fixed column
  for the *colon*, which is otherwise about half a digit wide.
* The row gets **wider**, not narrower: the narrow characters are padded up to
  the cell, never the reverse. `wfb`'s text-overflow and safe-area checks
  measure the baked advances, so they see that width without being told about
  it -- but a design that was already close to the bezel may start warning.
* **`align:` places the ink inside the cell** -- `center` (the default) is what
  a digital readout wants; `left` and `right` line up the edges of a column of
  readings. A glyph with no ink at all, such as a space, keeps a zero offset.
* **`align:` without `monospace: true` is a build error.** A proportional font
  has no cell for the ink to sit in, so honouring it would mean doing nothing
  silently.
* This is a **custom-font** feature. A system font (`FONT_NUMBER_HOT`, ...) is
  the device's own, already rasterised, and cannot be rebaked -- see
  `docs/limitations.md`.

Vertical placement is deliberately not part of this: baseline and line height
are the font's own metrics, and a `text` element already has `vertical_align:`.

### Everything else

* **Omit `glyphs` and the compiler derives the set** from every format spec and
  literal string the design can render. The example face's clock font carries
  eleven glyphs rather than a character set — on a 128 KB budget that is the
  difference between a large font fitting and not.
* **Glyphs are rasterised at 16x and averaged down**, not drawn straight at the
  target size. At single-digit sizes FreeType's hinting fits the outline to the
  pixel grid and breaks the shape's own symmetry — measured across 99
  provably-symmetric glyphs from the icon font, **16.8% of ink pixels landed
  asymmetrically**: a plain square baked to 7x7 ink inside an 8x8 tile, and a
  ring came out lopsided in every row. Rasterising large and box-averaging
  recovers real per-pixel coverage before the 1-bit threshold sees it, which
  brings that to **1.1%**. Advances and line metrics are untouched, so this
  changes how a glyph looks, never where it sits.
* **`antialias` defaults to false**, or to the top-level `antialias:` default
  when there is one -- Bitmap fonts are 1-bit by default because anti-aliasing
  costs runtime RAM. See "`antialias:` — soften an edge" below for the full
  picture, including the icon and primitive-drawing elements that share this
  same key.

A glyph the design can render but the font does not contain is a **build error**,
checked against the baked sheet's own character map.

Alternatively name a system font directly: `font: FONT_MEDIUM`,
`font: FONT_NUMBER_HOT`, and so on.

---

## Elements

Z-order is document order, with an optional `z:` override. Every element takes
`id`, `type`, `at`, `modes`, `z`, `visible`, `lint` and `overrides`.

### Two ways to write a list of elements

Anywhere a list of elements is accepted — the top-level `elements:` and a
`group`'s `children:` — it may be written either as a **sequence**, where each
element carries its own `id:`, or as a **mapping**, where the key *is* the id:

```yaml
# the list form                       # the mapping form
elements:                             elements:
  - id: background                      background:
    type: shape                           type: shape
    shape: rectangle                      shape: rectangle
    color: palette.bg                     color: palette.bg
  - id: clock                           clock:
    type: text                            type: text
    value: time.clock                     value: time.clock
    format: "{:%H:%M}"                    format: "{:%H:%M}"
```

They mean exactly the same thing. `wfb/desugar.py` rewrites the mapping into
the sequence before anything else runs, so the schema, the IR, layout, the
linter, the preview and code generation only ever see one form — and the two
therefore cannot drift into meaning different things. The gate on that claim is
that a design written both ways generates byte-identical Monkey C, resources,
manifest and jungle for every target
(`tests/test_desugar.py::test_the_two_forms_generate_byte_identical_output`);
`examples/complications/face.yaml` is written in the mapping form for the same
reason, as a working proof rather than a snippet.

**Order still matters in the mapping form.** A YAML mapping is ordered as
written, and this compiler reads it in that order, so document order is still
draw order — the *second* element is drawn over the first, exactly as in a
sequence. If that feels like something a mapping should not promise, that is a
fair instinct, and it is one of the reasons for the recommendation below.

Three things are errors in the mapping form, each reported against your own
line:

* writing `id:` inside the body as well — the key already is the id;
* a key that is not a valid identifier (`back-ground:`, `2clock:`);
* the same key twice. This one never reaches the compiler: YAML itself forbids
  duplicate keys and the loader reports it, which is a small bonus of this
  form — a duplicate element id is unwriteable rather than diagnosed.

A `carousel`'s `items:` are **not** affected. They are slots, not elements;
they have no id and are always a sequence.

**Which to use.** The project recommends the **list form**, and everything it
generates — `wfb new`'s templates, the skill, every other example — emits it.
Two concrete reasons:

* the normative artefact is the JSON Schema, and the schema describes only the
  list form. A `$schema`-aware editor (the second thing this page tells you to
  set up) will therefore flag a mapping-form file as invalid even though the
  compiler accepts it. That is a real daily cost, and it is
  [recorded as a limitation](limitations.md);
* a sequence says out loud that order is meaningful, which here it is.

Use the mapping form when the ids are what you navigate the file by — a dense
face with twenty elements, where `hr_value:` as a heading beats hunting for
`- id: hr_value` — and accept the editor caveat, or drop the `$schema` modeline
from that file.

### `visible:` — draw this only sometimes

```yaml
- id: charging_bolt
  type: icon
  icon: battery
  at: {anchor: center, dy: 25%}
  visible: "system.charging"
```

An expression that must type as a **boolean** — a comparison, `and`/`or`/`not`,
or a `?:` whose branches are booleans. There is no truthiness rule, so
`visible: activity.steps` is an error naming the type it got: Monkey C has no
truthy Number either, and guessing what the author meant is how a face ends up
showing something nobody asked for.

**Absent means hidden.** If the condition reads a nullable source and the device
cannot supply it, the element is not drawn. There is deliberately **no
`when_absent:` for visibility**: `when_absent:` chooses a substitute *value*
(placeholder text, a fallback fraction), and existence has no substitute —
"maybe drawn" is not a thing to fall back to. The two are separate axes and
compose independently: an element can be visible while its value is absent, in
which case `visible:` lets it through and `when_absent:` decides what it shows.
Concretely, the generated guard is one test:

```monkeyc
// visible: activity.steps > 500 -- absent means hidden
if (activitySteps == null || !(activitySteps > 500)) {
    return;
}
```

**On a `group`, `visible:` gates the whole subtree.** The condition is conjoined
into every element beneath it at build time, so nested groups compose: a child
of a hidden group is hidden no matter what its own `visible:` says, and a child
with its own condition needs both to hold.

A condition that folds to a constant `false` — `visible: "false"`, or something
that reduces to it on a particular device — is the suppressible `dead-element`
warning: the element is generated and never drawn. A constant `true` is not
warned about; it is a normal thing to write while iterating.

Two things `visible:` deliberately does **not** change, both recorded in
[`docs/limitations.md`](limitations.md):

* the element still occupies its box for the geometry, overlap, safe-area and
  text-overflow checks, because visibility is a runtime fact and the linter
  reasons about build-time geometry;
* it still owns its `on_hold:` hit region. The hit test lives in the delegate,
  which has no access to the frame's readings, and re-reading them at touch time
  would answer about a different moment than the one on screen anyway. A hold on
  a hidden element opens its glance.

### `static:` — draw it once, then blit it

```yaml
static:                     # a top-level block, beside `elements:`
  backdrop:
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.bg
  hour_ticks:
    type: group
    children: [...]         # twelve tick marks, none of them bound to anything

elements:
  clock:
    type: text
    value: time.clock
```

Content that never changes is painted **once**, into an offscreen
`Graphics.BufferedBitmap`, and every later frame draws it with a single
`drawBitmap` instead of re-running every primitive. That buffer comes from the
**graphics pool** — 1 MB on every supported target — not from the 128 KB the
watch face itself gets, so a full screen of pixels there costs nothing against
the design's own budget.

**What this buys is CPU and battery, and this repository has not measured it.**
There is no simulator in this container and no watch, so what is verified is
that it compiles, that the fallback path draws the same content, and what it
costs in bytes. See [`docs/limitations.md`](limitations.md).

There are two spellings and they mean exactly the same thing:

```yaml
static:                    #  equivalent to      elements:
  ticks:                   #                       - id: static
    type: shape            #                         type: group
elements:                  #                         static: true
  clock:                   #                         children:
    type: text             #                           - id: ticks
                           #                               type: shape
                           #                       - id: clock
                           #                         type: text
```

`static: true` works on **any** element: on a `group` it covers the subtree, on
a leaf it is a subtree of one. The top-level block is the same thing written in
one place, and the compiler rewrites it into exactly that group — under the
reserved id `static`, at the front of draw order. Prefer the block when a design
has a lot of fixed furniture; prefer `static: true` when one group is already
the natural home for it.

**Static content must come first in draw order.** The buffer is opaque and
covers the whole screen, so its blit erases whatever is under it. The top-level
block satisfies this automatically; `static: true` on a group you have placed
somewhere else does not, and the compiler says so rather than letting the blit
quietly wipe out an element. Whether a *transparent* buffer would work on these
devices could not be established from the SDK and cannot be tried without a
simulator — the evidence, both ways, is in
[`docs/research/probes/static-buffer/`](research/probes/static-buffer/README.md).

Everything else the compiler rejects, and why:

| rejected | because |
|---|---|
| any data binding in the subtree, `visible:` included | the buffer is filled once and never refilled; the reading would freeze at whatever it was on the first frame |
| a `carousel` | it remembers which item is centred and redraws when the wearer moves it |
| `modes:` containing `low_power` | `onPartialUpdate` is charged by clip *area*, and the buffer is the whole screen. `active` and `always_on` are both fine |
| `static:` inside a static subtree | the outer one already draws it |
| two static elements with different `modes:` | there is one buffer, and a buffer is blitted as a whole |

A constant expression is fine — it is the *binding* that is rejected, not the
syntax. `color: "palette.warm"` and `visible: "true"` both fold at build time and
are welcome in a static group.

**It always renders, buffer or not.** The generated view allocates behind
`if (Graphics has :createBufferedBitmap)` and null-checks the result, and
`onUpdate` calls the very same `renderStatic(dc)` on the screen's own Dc when
there is no buffer. One method, two call sites, so the buffered and unbuffered
pictures cannot drift apart. `renderStatic` clears to black first: a fresh
buffer's contents are undefined, and since the static content is the first thing
drawn either way, clearing costs nothing and is what makes `wfb preview` — which
also starts from black — agree with the watch.

The suppressible `graphics-pool` note reports what the buffer costs, per device:

```
note[graphics-pool]: the static content buffers 67,600 B of the 1,048,576 B
                     graphics pool (6.4%) on fenix8solar47mm
      confidence: estimate -- bytes per pixel for a BufferedBitmap is not
                  published; this uses the display's bitsPerPixel and ignores
                  any per-surface overhead
```

It becomes a warning past half the pool. It is an **estimate** and says so: the
SDK publishes no bytes-per-pixel figure for a `BufferedBitmap`, so this uses the
display's own `bitsPerPixel` from the device files as the nearest honest proxy.

### `antialias:` — soften an edge

```yaml
antialias: true            # face-wide default

fonts:
  clock:
    source: assets/OpenSans-Regular.ttf
    size: 68
    antialias: false        # override: keep the clock crisp

elements:
  - id: dial
    type: group
    antialias: false        # override: default for this subtree
    children: [...]
  - id: step_ring
    type: progress
    style: arc
    antialias: true
  - id: steps_icon
    type: icon
    size: 30px               # inherits the face default (true)
```

A single top-level `antialias:` (default `false`) is the face-wide default,
inherited by every font, icon and primitive-drawing element unless it
overrides it. It reaches two entirely different SDK mechanisms, gated in two
entirely different ways:

* **A bitmap font** (a `fonts:` entry, or the synthetic font an `icon` bakes)
  is a *resource* attribute -- `<font antialias="true">` -- and the resource
  compiler bakes an 8-bit grey ramp instead of a 1-bit mask. No device gating
  is needed: the SDK's own history notes that the toolchain overrides the
  attribute itself on devices too old to render it (Forerunner 45, Forerunner
  920XT, Edge 130), which is not a concern for any of this project's three
  targets in any case.
* **A `shape` or `progress` element's own drawing** is a runtime `Dc` call,
  `setAntiAlias`, gated per device with a `has :setAntiAlias` check --
  `doc/docs/Core_Topics/Graphics.html` gives this idiom verbatim, and the
  generated helper (`applyAntiAlias`, deliberately *not* named `setAntiAlias`
  -- see `docs/research/probes/antialias/README.md` 3) is unconditional: a
  build-time gate is not an option, because `wfb` generates one view shared by
  every target device. The face default is reset once at the top of
  `onUpdate` (covering both the awake and asleep branches), `onPartialUpdate`
  and `renderStatic`; an element whose own `antialias:` differs from the face
  default sets and restores it around its own drawing only, so guard early
  returns above it never leave the wrong state behind for the next element.
  `text`, `icon` and `carousel` never emit any of this -- they draw glyphs,
  and a glyph's anti-aliasing is the font-baking half above.

**Inheritance is a default, not a conjunction.** A `group`'s own `antialias:`
becomes what its subtree inherits, and a descendant's own `antialias:` always
wins outright over its enclosing group's -- there is no meaningful "AND" of two
booleans that both just mean "should this look soft", unlike `visible:`, where
conjoining an ancestor's condition into a descendant's is exactly the point.
Leaving it unset anywhere in the chain falls through to the next enclosing
group, and ultimately to the face-wide default.

**Accepted on `group`, `shape`, `progress`, `icon` and `carousel` only.** Not
on `text`: a `text` element draws through a font named in `fonts:`, and that
font is one bitmap resource shared by every element that references it, so
anti-aliasing cannot vary per element the way it can on a shape's own outline
or an icon's own, per-glyph font. Writing `antialias:` on a `text` element is a
build error pointing at that font's own `antialias:` instead -- naming the
actual font this element uses when it names a custom one, or saying plainly
that a system font has no `antialias:` of its own when it does not.

**Cost is measured, not estimated, on both sides -- but read the caveat under
the tables before comparing any two `.prg` figures of your own.** The two
sides move different numbers, because they are different kinds of thing.

The font side is baked into a *resource*, so it moves the `.prg` and never
`--build-stats`. On `examples/slice/`, all three targets, output paths held to
the same length:

| | `.prg` (fenix8solar47mm) | vs. previous row | `--build-stats` |
|---|---|---|---|
| no `antialias:` anywhere | 96,076 B | — | 833 B data, 1,317 B code |
| the eleven-glyph 68px clock font | 96,732 B | **+656 B** | *unchanged* |
| the 30px `steps` icon as well | 96,988 B | **+256 B** | *unchanged* |

The primitive side is emitted *code*, so it moves both -- and only this side
counts against the 128 KB watch-face budget at all. On `examples/antialias/`,
which turns the face default on and has one element override it back:

| | `--build-stats` | total | `.prg` |
|---|---|---|---|
| no primitive anti-aliasing | 833 B data, 1,317 B code | 2,150 B | 96,876 B |
| the face default on, one override | 842 B data, 1,380 B code | 2,222 B | 97,148 B |

That **+72 B** decomposes as +9 B data and +39 B code for the guarded helper
and its one reset call, plus +24 B code for each element that overrides the
default (the two extra calls bracketing its own drawing).

**Two things these numbers do not tell you, stated rather than implied.**

First, **a `.prg`'s size depends on the path it was built at** -- the same
generated source built to two output directories whose names differ in length
produced files 80 B apart, with byte-identical `source/`. So a `.prg`
comparison is only meaningful between builds whose output paths are the same
length, which is how every figure above was taken; `--build-stats` has no such
problem and is the instrument to prefer wherever it moves at all.

Second, **the runtime RAM the SDK's own Resources page warns font
anti-aliasing costs** ("since bitmap fonts can take a lot of runtime
memory...") **and any CPU or battery cost of the primitive side are measured
by neither `--build-stats` nor the `.prg`, and stay unquantified here** --
there is no simulator or device in this container to read either from
(`docs/limitations.md`). Nor has the visual improvement itself been seen: the
softer edge is what the SDK says these switches do, not something this project
has rendered on a panel.

**A soft edge on a 64-colour panel dithers, and the linter says so.** The
suppressible `antialias-dither` check fires once per device, against the
first element (in draw order) whose `antialias:` resolves to `true` there, on
any device whose panel shows only 64 colours -- all three of this project's
current targets, so it fires on every face that turns the feature on for a
`shape`/`progress` element. See "Lint suppression" below and
`docs/limitations.md`. `examples/antialias/` is a worked design exercising
both halves of the feature together, including this tradeoff accepted
explicitly with `lint: {allow: [antialias-dither], reason: ...}`.

### `shape`

```yaml
- id: background
  type: shape
  shape: rectangle    # rectangle | rounded_rectangle | circle | ellipse
  at: { anchor: center }    #  | arc | polygon | line
  size: { width: 100%, height: 100% }
  color: palette.bg
```

Seven shapes, one per native `Dc` drawing call. Each takes `color:`, and each
takes **only** the keys its own geometry needs -- a key from another row is an
error, not a no-op, so `radius:` typed where `corner_radius:` was meant is
reported rather than drawing square corners in silence:

| `shape:` | keys | draws |
|---|---|---|
| `rectangle` | `size` | `fillRectangle` / `drawRectangle` |
| `rounded_rectangle` | `size`, `corner_radius` | `fillRoundedRectangle` / `drawRoundedRectangle` |
| `circle` | `radius` | `fillCircle` / `drawCircle` |
| `ellipse` | `size` | `fillEllipse` / `drawEllipse` |
| `arc` | `radius`, `start_angle`, `sweep` | `setPenWidth` + `drawArc` |
| `polygon` | `points` | `fillPolygon` |
| `line` | `to` | `drawLine` |

**`filled:` (default `true`) is a real switch, not decoration.** `filled: false`
draws the outline at `thickness:` (default 1 px) instead of filling, on
`rectangle`, `rounded_rectangle`, `circle` and `ellipse`. The outlined shape's
ink straddles the declared box, so the compiler grows the element's extent by
half a pen width for the safe-area and overlap checks -- what you declare is
still the geometry, not the ink.

`thickness:` is checked against `filled:` rather than against the shape: a
`line` and an `arc` always draw with it, and any other shape uses it only when
outlined, so `thickness:` on a shape left filled is an error too.

Two shapes reject `filled:`, and both refusals are the platform's, not this
project's:

* **`arc` rejects `filled:` outright.** There is no `fillArc`, `fillSector` or
  `drawSector` anywhere in Connect IQ. An arc is a pen width and nothing else,
  so there is no inner/outer radius, no cap control, and no gradient sweep. For
  a solid disc use `circle`; for a solid wedge, approximate it with `polygon`.
* **`polygon` rejects `filled: false`.** `Dc` has `fillPolygon` and no
  `drawPolygon`. Draw the edges as `line` elements if you want an outline.

`points:`, `start_angle:` and `sweep:` are likewise errors on a shape that
cannot use them, rather than being read and quietly dropped.

#### `arc`

```yaml
- id: outer_arc
  type: shape
  shape: arc
  at: { anchor: center }
  radius: 92%r
  thickness: 5px
  start_angle: 210deg     # 12 o'clock is 0, clockwise positive
  sweep: 300deg           # negative sweeps counter-clockwise
  color: palette.dim
```

Angles are the format's own convention -- 12 o'clock is 0 and clockwise is
positive -- converted to Garmin's (3 o'clock is 0, counter-clockwise) at build
time. It is **exactly** the conversion `progress` with `style: arc` uses; both
call `wfb.layout.garmin_arc` and both draw through the same
`WfbArc.drawSpan`, so the two arcs cannot drift apart.

Use `shape: arc` for a fixed decorative span and `type: progress` /
`style: arc` for one whose length is bound to a reading.

#### `polygon`

```yaml
- id: chevron
  type: shape
  shape: polygon
  points:                             # 3 to 64 of them
    - { anchor: center, dy: 26% }
    - { anchor: center, dx: -9%, dy: 34% }
    - { anchor: center, dx: 9%, dy: 34% }
  color: palette.accent
```

Each entry in `points:` is a full `at:`-style position -- anchor, `dx`/`dy`, or
polar `angle`/`radius` -- resolved against the parent box exactly the way a
`line`'s `to:` is. The resolved vertices land in the per-device `Layout` module
as one `Array<Graphics.Point2D>` constant, so the device does no arithmetic
(ADR 0004). `fillPolygon` documents a **64-point limit**, which the schema
enforces.

See `examples/shapes/face.yaml` for all seven on one face.

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
  on_hold: heart_rate      # optional -- see "Interactivity" below
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
coordinate frame and, when it carries `on_hold:`, a hit region. Use a `shape`
underneath it for a visible background.

**`on_hold:` on a group covers the group's whole box**, not just one child — the
natural way to make a multi-element cluster (an icon next to its value, as
above) act as a single touch target instead of naming `on_hold:` on each piece
separately. See "Interactivity" below.

**`visible:` on a group gates every element beneath it**, at any depth. The
group's condition is conjoined into each descendant's own at build time (a group
emits no code of its own, so there is nothing else it could mean), which is why
nesting composes: an inner group's condition and the outer one both have to hold
for a leaf to draw. See "`visible:`" above.

### `carousel`

```yaml
- id: data
  type: carousel
  at: { anchor: center, dy: 20% }
  size: { width: 62%, height: 22% }   # the TOUCH target, not the drawn extent
  pitch: 22%r                         # centre-to-centre slot spacing
  slots: 3                            # 1 | 3 | 5; defaults to min(3, items)
  icon_size: 9%r
  color: palette.accent               # the selected item
  inactive_color: palette.dim         # its neighbours
  value_font: FONT_SMALL
  value_color: palette.fg
  value_offset: { anchor: center, dy: 34% }
  animate: 0.3                        # seconds; 0 disables the slide
  persist: true                       # remember the selection across restarts
  items:
    - value: heart_rate.current       # icon inferred from the source
      format: "{:d}"
      when_absent: placeholder
      placeholder: "--"
      launch: heart_rate              # centre-hold opens this glance
    - value: activity.steps
      format: "{:d}"
      when_absent: fallback
      fallback: "0"
      launch: steps
    - icon: battery                   # or name one explicitly
      value: system.battery
      format: "{:.0f}%"               # no launch: centre-hold opens nothing
```

A row of readings the **wearer** picks between, modelled on the stock
Forerunner face. The centred item is drawn in `color:` with its reading below
(or wherever `value_offset:` puts it); its neighbours are drawn in
`inactive_color:`. A hold moves the selection, which slides into place and is
remembered across restarts.

**One gesture, three meanings, told apart by geometry.** A live watch face
receives only touch and hold — see "Interactivity" below — so the element's own
box is cut into equal thirds:

```
        +---------------+---------------+---------------+
hold →  |   previous    |  open glance  |     next      |
        +---------------+---------------+---------------+
```

That is why `size:` is the **touch target rather than the drawn extent**: the
row paints only its icons and the reading, and sizing the box generously costs
nothing but makes the zones easier to hit. `wfb validate` checks both halves of
that — `carousel-zone` warns when a third is under 40px wide (a judgement, not
a Garmin number, and the message says so) and when a zone reaches under a round
screen's bezel, where a finger cannot land at all.

**Icons are inferred where the catalogue has a convention.** Omit `icon:` and
the item uses the conventional glyph for its data source (`activity.steps` →
`steps`, and so on). Name one explicitly with `icon:`, or reach for any
codepoint with `glyph: "U+XXXX"`, exactly as on an `icon` element.

**`when_absent:` is per item, and it does not hide the row.** One absent
reading blanks *that item's* reading and leaves its icon drawn — the row does
not collapse and the zones do not move, which is the only behaviour that makes
sense for something the wearer is navigating. The carousel's own colours may
therefore **not** be nullable: there is no `when_absent:` for the row's
appearance, so guard a conditional colour inside the expression instead.

**`launch:` is optional per item, and also accepts `auto`.** With a name, a
centre-hold opens that complication's glance (`wfb complications` lists the
names). With `launch: auto`, the compiler resolves the target itself from
*that item's own* `value:` binding, via `Source.launch_complication` — see
"`on_hold: auto` / `launch: auto`" under Interactivity below for how that
resolution works and what it does when it cannot decide. Without `launch:` at
all, the hold is consumed and nothing opens, which is the honest outcome for a
reading no glance owns. A carousel where no item declares a launch target
needs no `ComplicationSubscriber` permission and no raised `minApiLevel`.

**A carousel element may not itself take `on_hold:`.** Its whole box is
already three hold zones — left/right cycle the row, centre opens the
selected item's `launch:` — so there is nothing left for an element-level
hold to mean. This used to validate cleanly and be silently dropped by the
emitter; it is now the `carousel-on-hold` build error, pointing at per-item
`launch:` instead.

**The slide only runs while the watch is awake.** `WatchUi.animate` is
documented to *crash the app* if called from a watch face in low power mode, so
the generated code guards on the sleep state and rotates instantly while
asleep. Since a touch is one of the things that keeps the face awake, the
animation window and the interaction coincide in practice — but it is a guard,
not an assumption. `animate: 0` opts out entirely.

---

## Data binding

Sources are addressed by dotted path and carry a type, a nullability, and any
permission binding it implies.

```yaml
value: activity.steps
value: heart_rate.current
value: system.battery
value: time.clock
value: complication.body_battery
```

**`wfb sources` is the authoritative, always-current list** -- run it rather
than trusting a copy pasted into prose, which goes stale the moment the
catalogue grows. For each path it prints the type, whether it is nullable,
any permission it implies, its conventional `on_hold: auto` target (if it has
one), and the SDK page it was taken from:

```
$ wfb sources
activity
  activity.steps                     number   steps today  [nullable, on_hold: auto -> steps]  (Toybox/ActivityMonitor/Info.html)
  ...
complication
  complication.body_battery          number   a Number representing your current body battery  [nullable, needs ComplicationSubscriber, on_hold: auto -> body_battery]  (Toybox/Complications.html)
  ...
heart_rate
  heart_rate.current                 number   current heart rate  [nullable, on_hold: auto -> heart_rate]  (Toybox/Activity/Info.html)
  ...
```

As of this writing the catalogue covers `time.*`, `date.*` (including the
localised month name and weekday), `device.*` (notification/alarm counts,
do-not-disturb, phone-connected, 24-hour setting), `system.*` (battery,
charging), `activity.*` (steps, calories, distance, floors, move bar,
intensity minutes, stress score, respiration rate, time to recovery),
`heart_rate.current`, `pulse_ox.current`, `ambient.*` (altitude, barometric
pressure), `weather.*` (current condition and temperature, feels-like,
today's high/low and precipitation chance, humidity, wind speed,
today's/tomorrow's forecast condition — see `icon_for:` above for turning a
condition into a drawn icon), `user.*` (running/cycling VO2 max, resting
heart rate, from `Toybox.UserProfile`), and `complication.*` (below).

### The `complication.*` namespace, and the one rule for reaching it

**`complication.<type>` is *always* read through `Toybox.Complications`; every
other catalogue path is *always* a direct API read.** No exceptions, no
overlap. All 42 real `COMPLICATION_TYPE_*` values are exposed
(`COMPLICATION_TYPE_INVALID` is not a real value and is excluded), generated
from one table, `wfb/complications.py`'s `TYPES` — transcribed verbatim from
`Toybox/Complications.html`'s own Type table, not hand-copied, so it cannot
silently drift from what the platform actually offers. `wfb complications`
prints all 42, the Monkey C constant each compiles to, and the API level it
was introduced at.

```yaml
- id: body_battery_reading
  type: text
  value: complication.body_battery
  format: "{:d}"
  font: FONT_SMALL
  when_absent: placeholder
  placeholder: "--"
```

A `complication.*` binding compiles to a plain pull, exactly like any other
source — `WfbComplications.valueOf(new Complications.Id(Complications.
COMPLICATION_TYPE_BODY_BATTERY))` — cast to the source's own type
(`Complications.Complication.value` is a union of `String or Number or Float
or Long or Double or Null`, so the cast is required, not decorative). Binding
one adds the `ComplicationSubscriber` permission and raises `minApiLevel` to
4.2.0 automatically. `wfb/emit/monkeyc.py` also emits one
`WfbComplications.subscribe(...)` per bound type in `onLayout`, whose whole
job is `WatchUi.requestUpdate()` on change — this is *not* a cache (see "How
data is read", below), it exists only so a value that changes after the first
draw is not stuck stale forever.

**Prefer a direct-read source over its complication counterpart whenever both
exist.** `heart_rate.current`, `activity.steps`, `weather.condition` and
around twenty others are also reachable via `complication.*`
(`complication.heart_rate`, `complication.steps`, `complication.
current_weather`, ...), but the direct path is strictly cheaper: no
`ComplicationSubscriber` permission, no `minApiLevel` floor of 4.2.0, and no
subscription. The complication route exists **only** for values with no
other way in — most usefully `complication.body_battery`
(`Toybox.SensorHistory` is the only other route to Body Battery, and it is a
permission **watch faces are not allowed to declare at all** —
`Core_Topics/Manifest_and_Permissions.html`'s table has a blank Watch Face
column for it), plus `complication.solar_input`, `complication.sunrise`/
`sunset`, `complication.training_status`, `complication.
weekly_run_distance`/`weekly_bike_distance`, `complication.sleep_score` and
`complication.calendar_events`. These nine used to be bound through a
direct-looking path (`body_battery.current`, `weather.sunrise`, and so on);
binding the old path now raises **`source-renamed`**, naming the
`complication.*` replacement, because the value moved without the platform
actually changing what it means.

A device can decline to support a given complication type outright — most
relevantly here, `complication.sleep_score` needs ConnectIQ 6.0.2, above
`fr955`'s own 5.2.0 ceiling (its `compiler.json`), so it will never update
there. `runtime-lib/WfbComplications.mc`'s `subscribe()` absorbs this the
same way every other nullable source is absorbed: `valueOf` just returns
`null` on a device that does not support the type, rather than the
subscription throwing. A design that binds `complication.sleep_score` will
show nothing at all on `fr955` specifically — worth knowing before relying on
it there. This is a **per-device gap that is not itself checked** — see
`docs/limitations.md` §3, "device gating for a source is not enforced".

*Redundant with a direct source and deliberately not added as its own
entry*: a complication duplicating a field already bound directly
(`COMPLICATION_TYPE_STEPS`, `_CALORIES`, `_HEART_RATE`, `_ALTITUDE`,
`_VO2MAX_RUN`, `_VO2MAX_BIKE`, `_RECOVERY_TIME`, `_STRESS`,
`_CURRENT_WEATHER`, `_CURRENT_TEMPERATURE`, and more) is still present as
`complication.*` — the catalogue is complete, all 42 types — but a design
should reach for the cheaper direct path first; `wfb sources`' `on_hold:
auto -> ...` annotation on the direct source is the same hint applied to
launch resolution.

**One thing genuinely still isn't bindable, through either route**: a
running-only *total* distance (as opposed to weekly).
`COMPLICATION_TYPE_WEEKLY_RUN_DISTANCE` is a *weekly* total, not all-time, and
there is no other platform field for it short of aggregating
`UserProfile.getUserActivityHistory()` by hand, which is real computation
ADR 0005 deliberately keeps out of the expression language.
`activity.distance` (today's ambient distance, every activity type) remains
the nearest thing actually bindable.

See `docs/limitations.md` §2 for what is still missing from the catalogue.

### How data is read

**Every binding is a plain read, every frame, unconditionally. Nothing is
cached inside the generated face.** An earlier version of this compiler
graded sources `frame`/`slow`/`event` and cached the two slower grades — a
TTL for one, a subscribed field for the other — on the theory some Garmin API
calls were too expensive to make every frame. That theory was wrong: the SDK
documents its own calls as already cached on *its* side —
`Toybox/Weather.html` describes `getCurrentConditions()` as "get the **most
recently cached** weather conditions", not "fetch weather conditions" — so a
second cache inside the 128 KB watch-face budget bought nothing but code and
memory. It is gone. `wfb/emit/monkeyc.py`'s `ReadPlan` hoists one read per
distinct reader per element method the way it always did (two elements
sharing `weather.getDailyForecast()` still share one call, not one each), and
that is the entire optimisation — no staleness check, no field, no TTL.

**Consequence: any source, including `weather.*` and `complication.*`, may
now be bound from a `low_power` or `always_on` element.** The compiler used
to reject that outright for anything but a `frame`-tier source; it no longer
does. This does **not** make reading them free in `onPartialUpdate` — exceeding
that handler's power budget still calls `onPowerBudgetExceeded` and disables
partial updates **permanently, for the rest of the app's lifecycle**, and that
has not changed. What changed is *who* is responsible for staying under it:
previously the compiler refused the design outright; now the suppressible
`partial-update-budget` lint is the only thing standing between an author and
an expensive `low_power` read — a `weather.*` or `complication.*` binding
there is exactly the case its own warning names as the one to check first. If
your design draws in `low_power`, read the "Modes" section below and treat
that warning as load-bearing, not optional.

If a value you want is missing, check the underlying Garmin API page:
`Toybox/ActivityMonitor/Info.html`, `Toybox/System/Stats.html`,
`Toybox/System/DeviceSettings.html`, `Toybox/Activity/Info.html`,
`Toybox/Weather/*.html`, `Toybox/UserProfile/Profile.html` and
`Toybox/Complications.html` are where the current catalogue draws from, and
each has more fields than are exposed today -- adding one is a
`wfb/catalog.py` entry (path, type, nullability, permission, the SDK field it
reads), not a schema change. Before adding one, check the field's own
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

**`when_absent:` is about the value, `visible:` is about existence.** A nullable
source read by `visible:` needs no policy and cannot take one: absence there
means hidden, full stop. The two compose independently — an element can be
visible while its value is absent. The one interaction is reported rather than
merged: a `placeholder:` whose nullable sources are *all* also read by
`visible:` can never be drawn, and the compiler says so, exactly as it does for
a nullable `color:`. See "`visible:`" above.

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

**Any source may now be read from a `low_power` element — there is no
compile-time restriction on which.** See "How data is read" above: nothing is
cached in the generated face, so there is no longer a cheap/expensive class of
source for the compiler to gate on. That does **not** mean every source is
equally safe to read there. Exceeding the `onPartialUpdate` power budget calls
`onPowerBudgetExceeded` and disables partial updates **permanently, for the
rest of the app's lifecycle** — the platform limit is exactly as real as it
ever was, only the enforcement moved: it is now the suppressible
`partial-update-budget` warning, not a hard build error, so read it and act on
it rather than assuming a green build means a safe one. A `weather.*` or
`complication.*` read in `low_power` is the case its own message names as the
one to look at first.

---

## Interactivity: `on_hold:`

Any element can open a glance when it is **touched and held**:

```yaml
- id: hr_icon
  type: icon
  icon: heart
  at: {anchor: center, dy: -20%}
  on_hold: heart_rate       # run `wfb complications` for the 42 names
```

**A watch face cannot launch an arbitrary app.** The platform offers exactly
one exit — `Complications.exitTo`, documented as "launches the app associated
with the complication" — so an interactive element names a **complication
type** and the watch opens whichever glance or app owns it. `on_hold:
heart_rate` opens the heart-rate glance whether or not the design displays a
heart rate.

`wfb complications` lists every name, the Monkey C constant it compiles to,
and the API level that type was introduced at. The list is generated from the
SDK's own `COMPLICATION_TYPE_*` table, so it cannot drift from what the
platform actually offers.

**Touch and hold is the only gesture there is — on every device.** This is not
a limitation of the compiler or of one watch. `WatchFaceDelegate.onPress` is
the whole input surface a live watch face receives: there is no swipe on a
watch face, the physical keys belong to the system, and
`WatchFaceDelegate.onTap` — which does exist on the fēnix 8 targets — is
documented **"Only available in WatchFace config mode"**. It is how the
*on-device editor* learns which complication slot you picked; it never fires on
a face you are merely looking at. The compiler therefore emits `onPress` alone.
`docs/research/07-carousel-interaction.md` §1 has the evidence, including the
SDK's own sample.

`wfb validate` warns (`hold-unsupported`) if a target has no `onPress` at all —
resolved against that device's own symbol table rather than its API level,
because an API level does not settle it. All three of this project's targets
have it, `fr955` included.

> `on_tap:` was this key's name until that was researched properly. The old
> spelling is now an error that names its replacement; the value is unchanged.

**The hit region is the element's own drawn box** — what the finger must hit is
what the eye sees, which is checkable in `wfb preview`. Nothing is inflated to
a minimum touch size: Garmin publishes no such number, and inventing one would
silently overlap neighbours on a dense face. For a bigger target, or to make
several elements act as one, put them in a `group` (above) and put `on_hold:`
on the group instead of each child.

Regions are tested in draw order and the first match wins, so two overlapping
regions make the second unreachable. That is a warning (`hold-overlap`), not
something you have to notice on the wrist.

**One hold can still mean more than one thing, by landing somewhere else.**
`ClickEvent.getCoordinates()` is the only degree of freedom the platform
offers, and `carousel` (above) uses it: three zones across one element's box,
so previous, next and "open the glance" all come off the same gesture. ADR 0006
§6 originally expected these to conflict; separating them by geometry is what
dissolved that.

Binding `on_hold:` adds the `ComplicationSubscriber` permission and raises
`minApiLevel` to 4.2.0 automatically — `exitTo`'s own level. Nothing emitted
references `onTap`, so its 5.1.0 never enters into it.

### `on_hold: auto`

Naming a complication type by hand is often redundant with what the element
already displays. `on_hold: auto` resolves the target for you, from the
element's own **value** binding:

```yaml
- id: hr_value
  type: text
  value: heart_rate.current
  format: "{:d}"
  font: FONT_SMALL
  at: {anchor: center, dy: -20%}
  on_hold: auto              # resolves to 'heart_rate' -- same as writing it
```

The compiler looks at the element's value expression(s) only — a `text`'s
`value:`, an `icon`'s `icon_for:`, a `progress`'s `value:` — deliberately
never `color:`, `track_color:` or `max:`, because a conditional colour's own
source reference is not what the element is *about*. It resolves through
`Source.launch_complication`, the same field `wfb sources`' `on_hold: auto ->
...` annotation shows for every source that has one:

* **Exactly one distinct target among the bound source(s)** — `auto` becomes
  that target, same as naming it.
* **None** (including an element with no value binding at all, or one whose
  source has no conventional counterpart) — build error `hold-auto-
  unresolved`, naming the source(s) it looked at and pointing at `wfb
  complications` for a name to write explicitly.
* **More than one distinct target** (an expression combining two sources that
  point at different glances) — build error `hold-auto-ambiguous`, listing
  the candidates.

Both are errors rather than warnings: guessing here would silently open the
wrong glance, which is exactly the class of failure this compiler exists to
prevent. A carousel item's `launch:` accepts `auto` the same way, resolved
from that one item's own `value:` — see `carousel` above.

---

## Lint suppression

```yaml
lint:
  allow: [palette-dither]
  reason: "deliberate orange accent, matches the brand"
```

`reason` is required — a suppression without a stated reason is how linters get
disabled wholesale. Errors that reflect hard platform limits (missing glyphs,
off-screen geometry, `hold-auto-ambiguous`/`hold-auto-unresolved`,
`carousel-on-hold`) are **not** suppressible: silencing one produces a face
that does not work.

Twelve codes are suppressible: `palette-dither`, `safe-area`, `text-overflow`,
`contrast`, `partial-update-budget`, `carousel-zone`, `hold-overlap`,
`hold-unsupported`, `complication-gated`, `dead-element`, `graphics-pool` and
`antialias-dither`.
`wfb/lint.py`'s `SUPPRESSIBLE` is
the normative list -- this prose has drifted from it before, so check there
rather than here if the two ever disagree. **A code that is not one of them is a
build error**, and the message distinguishes the two ways that happens — a code the compiler does not emit at all (with a "did you mean"
suggestion) versus a real code that is deliberately unsuppressible (with the
reason). Both used to be ignored in silence, which left an author unable to tell
a typo from a check that refuses to be silenced.

Four of them are not element-scoped diagnostics, so the allow goes on the
element that causes them: `palette-dither` on an element whose `color:` or
`track_color:` is exactly `palette.<name>`, `partial-update-budget` on any
element drawn in `low_power` mode, `graphics-pool` on the first element
declaring `static: true`, and `antialias-dither` on the first element (in
document order) whose `antialias:` resolves to `true` on a 64-colour device.
See `docs/limitations.md` 3.

---

## Not yet implemented

Present in the ADRs, absent from format 1: `image` and `complication_slot`
elements, the `raw` escape hatch (ADR 0007), per-device `overrides` (parsed but
not yet applied), the `config:` block and on-device configuration (ADR 0006), and
`segments`/`scale` progress styles. See [`docs/limitations.md`](limitations.md).

(`complication_slot`'s "cycle through several readings" half now exists as
`carousel`, above. What is still missing is the other half: a slot whose *type*
the wearer picks in the on-device editor, which needs the `config:` block.)
