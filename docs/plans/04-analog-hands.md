# Plan 04: Analog hands

- **Date:** 2026-09-14
- **Status:** built 2026-09-14, all three phases, by a subagent and then
  reviewed; §13 records what shipped, the measurements and the deviations.
  Where §13 disagrees with an earlier section, §13 wins.
- **Status:** (superseded) approved for building, 2026-09-14. The user asked for the
  research, the design, the requirements and the limitations, and for the
  build to go to a subagent and then be integrated. §12 lists the choices
  made without a round-trip, for the user to review afterwards.
- **Ask (the user's words, condensed):** define analog hands (hour,
  minute, second) by listing several primitives per hand, drawn at the
  12 o'clock position. Research using them on a face that updates their
  placement from the time, including showing the second hand only while
  the watch is active and hiding it when idle. Assume several sets of
  hands may be used with the styles feature. Research how to define them
  by name, with each hand's axis centre clear. Research and plan placing
  hands at an author-chosen position, so that the axis may be off centre.
- **Builds on:** ADR 0004 (element model, build-time resolution), ADR
  0006 §5 (modes), plan 02 (`layouts:` + `config: style:`, now in
  `docs/format.md` "Styles and layouts"), research 04 §1 (WFF's
  `AnalogClock`), and the probe `docs/research/probes/analog-hands/`,
  written for this plan.

---

## 1. What the platform gives (research)

| Question | Answer | Evidence |
|---|---|---|
| Is there a rotated-primitive draw call? | **No.** `Dc` draws axis-aligned rectangles, circles, ellipses, arcs, lines and polygons. Nothing takes a rotation. | `$CIQ_SDK/doc/Toybox/Graphics/Dc.html`; `bin/api.debug.xml` |
| So how does a hand turn? | **Rotate its vertices in Monkey C, then `fillPolygon`/`drawLine`/`fillCircle`.** This is what the SDK's own analog sample does. | `$CIQ_SDK/samples/Analog/source/AnalogView.mc`, `generateHandCoordinates` |
| Trigonometry on the watch | `Math.sin`, `Math.cos` (API 1.0.0). They are declared to return `Float or Double`. | `bin/api.debug.xml`; present in all three targets' `<id>.api.debug.xml` |
| Native alternative | `Graphics.AffineTransform` (`rotate`, `transformPoints`, `@since 4.2.0`) is on all three targets. It is not used; the reasons are in the probe README. | same |
| How often the face redraws | `onUpdate` runs **once a second while awake** and **once a minute asleep**. `onPartialUpdate` runs once a second while asleep, charged by clip *area* (constraint 4). | `WatchFace.onUpdate`/`onPartialUpdate` docs; ADR 0006 §5 |
| Knowing awake from asleep | `WatchFace.onEnterSleep` ("prepare for once-per-minute updates") and `onExitSleep`. On all three targets. | `bin/api.debug.xml` |
| Seconds while asleep | Only through `onPartialUpdate` with a clip that moves with the hand, repainting the previous clip from a **full-frame** buffer that already holds the hour and minute hands. That is the sample's `_offscreenBuffer`, redrawn every `onUpdate`. | `AnalogView.mc` `onPartialUpdate`, `getBoundingBox`, `drawBackground` |

**What the generated face does today, and why seconds need something new.**
Without `always_on`, `onUpdate` draws the same `active` element set both
awake and asleep (`wfb/emit/monkeyc.py`, `_emit_on_update`). An element
with `modes: [active]` is therefore **still drawn in the once-a-minute
sleeping update**. A second hand drawn there would sit frozen on whatever
second that update landed on. `modes:` cannot say "awake only" for one
element, so the second hand needs its own switch (§5.6). The `_sleeping`
flag that switch needs exists already, but is emitted only for
`always_on` designs.

**Prior art (research 04 §1).** WFF's `AnalogClock` has `HourHand`,
`MinuteHand` and `SecondHand`, each an *image* with `pivotX`/`pivotY`
given as fractions of the hand image's own box. This plan keeps the
three-hand structure. It makes the pivot *the origin* rather than a
fraction, because parts here are vectors with no image box to be a
fraction of (§5.1).

## 2. The probe

`docs/research/probes/analog-hands/` built the intended generated code on
all three targets, warning-free under `-l 3` strict. It covers a rotated
polygon with a tail, a thick line, a circle on the axis and one off it, an
off-centre axis, and the second hand gated on `_sleeping` with no
`always_on`. Findings the build must follow:

1. Rotated coordinates stay **Floats**; `fillPolygon`, `drawLine` and
   `fillCircle` accept them. The watch never rounds.
2. `sin`/`cos` must travel as **`Decimal`**. `Float` fails under strict
   typing, and the error is quoted in the README.
3. Cost is about a kilobyte: the whole probe app is 2,125 B on
   `--build-stats`.

## 3. Requirements

| # | Requirement | Where it is met |
|---|---|---|
| R1 | A hand is authored as a **list of primitives** drawn **pointing at 12 o'clock**. | §4, §5.2 |
| R2 | Hour, minute and second hands. Any subset may be present, so a small-seconds subdial is a set with only `second:`. | §5.1 |
| R3 | Hands are **named**: a set is declared once, by name, and placed by name. | §4 |
| R4 | The **axis is unambiguous**. Every coordinate in a hand is measured from the axis, and the axis is the origin. There is no second convention. | §5.1 |
| R5 | Hands follow the time **automatically**, with no author expression. | §5.5 |
| R6 | The second hand can be **shown only while awake and hidden asleep**, and that is the default. | §5.6 |
| R7 | **Several sets** coexist and switch with **Styles**. | §5.9 |
| R8 | The axis can be placed **anywhere the author says**, including **off centre**. | §5.8 |
| R9 | Everything the format already guarantees still holds: build-time resolution of every length, warning-free builds on all three targets, lints that know the geometry, a preview that matches the device, and no silent no-ops. | §5.3, §6, §7 |

## 4. The YAML

```yaml
hands:                                   # top-level, beside fonts:/palette:
  classic:                               # a named hand set
    hour:
      color: config.colors.fg            # default for this hand's parts
      parts:                             # drawn in this order
        - shape: polygon                 # pointing at 12; origin = the axis
          points:
            - {dx: -3%r, dy: 6%r}        # 6%r *behind* the axis: a tail
            - {dx: -2%r, dy: -38%r}
            - {dy: -44%r}                # the tip, straight up
            - {dx: 2%r, dy: -38%r}
            - {dx: 3%r, dy: 6%r}
    minute:
      color: config.colors.fg
      parts:
        - {shape: rectangle, at: {dy: -30%r}, size: {width: 3%r, height: 70%r}}
        - {shape: circle, radius: 4%r}   # a hub; `at:` defaults to the axis
    second:
      color: config.accent_color
      parts:
        - {shape: line, at: {dy: 15%r}, to: {dy: -82%r}, thickness: 2px}
        - {shape: circle, at: {dy: 15%r}, radius: 3%r}    # counterweight
        - {shape: circle, radius: 2%r, color: palette.black}

  small_seconds:
    second:
      color: palette.white
      parts:
        - {shape: line, at: {dy: 3%r}, to: {dy: -20%r}, thickness: 1px}

elements:
  - id: main_hands
    type: hands
    hands: classic                       # names a `hands:` entry
    at: {anchor: center}                 # THE AXIS, on the screen
    seconds: awake                       # the default: hidden while asleep

  - id: subdial_seconds
    type: hands
    hands: small_seconds
    at: {anchor: center, dy: 45%r}       # an off-centre axis (R8)
```

`type: hands` + `hands: <name>` follows the precedent of `type: icon` +
`icon: <name>` and `type: shape` + `shape: <kind>`. A bare name is how
`layout:`/`colors:` already name their declarations.

## 5. Semantics

### 5.1 A hand set, a hand, the axis

- **`hands:`** is an ordered mapping of name → set. A set has any of
  `hour:`, `minute:`, `second:`, and at least one. A set declares no
  position: it is a shape, like a `fonts:` entry, not something drawn.
- **A hand** is `{color?, parts}`. `parts:` holds 1 to 16 primitives, in
  draw order. The hand's `color:` is the default for its parts, and a
  part's own `color:` overrides it. A part left with no colour is an
  error.
- **The hand frame (R4).** Each part's coordinates are measured **from
  the axis**. The hand is drawn **as it looks at 12:00**, in the format's
  usual screen convention: `dx` is positive to the right and `dy` is
  positive *down*, so a tip is at negative `dy`, exactly as `at: {dy:
  -18%}` means "up" everywhere else. `anchor:` is rejected in a part
  (there is no box to anchor to; the axis *is* the anchor). A part
  position may be polar, `{angle, radius}`, measured clockwise from
  12 o'clock, so `{angle: 0deg, radius: 40%r}` is the tip.
- **Draw order is fixed:** hour, then minute, then second. Within a hand,
  parts draw in list order. The whole element draws at its own place in
  `z:`/document order. A pin that sits *above every hand* is an ordinary
  `shape: circle` element placed after the hands element. A hub *between*
  hands is a circle part at the origin of the hand below it.

### 5.2 Parts: four primitives, the rotatable ones

| `shape:` | keys | on the watch | why it is allowed |
|---|---|---|---|
| `polygon` | `points` (3–64) | rotate each vertex, `fillPolygon` | vertices rotate exactly |
| `rectangle` | `at` (its centre, default the axis), `size` | **becomes a 4-point polygon at build time**, then as above | a rotated rectangle is a polygon |
| `line` | `at` (start, default the axis), `to`, `thickness` (default 1px) | rotate both ends, `setPenWidth`, `drawLine` | end points rotate exactly |
| `circle` | `at` (centre, default the axis), `radius`, `filled` (default true), `thickness` (only when `filled: false`) | rotate the centre, `fillCircle`/`drawCircle` | a circle is its own rotation |

**Rejected, each with its reason in the message:** `rounded_rectangle` and
`ellipse` (no `Dc` call draws either rotated; approximate with a
polygon), `arc` (possible later: shift the start angle and rotate the
centre, §11), and `text`/`icon` (a bitmap font cannot rotate).
`filled: false` on `polygon`/`rectangle` is rejected, because there is no
`drawPolygon` (limitations §1). A key a part's shape does not read is an
error, following `SHAPE_GEOMETRY_KEYS`.

### 5.3 Units and rounding

- **`px` and `%r` only.** `%r` is the screen's minor radius, so a hand
  scales between 260 px and 280 px screens the same way the dial does.
  `%` is rejected, because a hand frame has no parent box. `pt` is
  rejected, because a hand has no font. A bare number means `px`, as
  everywhere else.
- **Resolved to whole pixels at build time**, per device, into `Layout`
  constants (ADR 0004 §2). **Rounding must be mirror-symmetric:**
  `dx: -1.5px` and `dx: 1.5px` resolve to `-2` and `2`, so a symmetric
  hand stays symmetric on the panel. Round half away from zero; a test
  pins it.
- **The one runtime computation.** The watch rotates the resolved
  coordinates by the time's angle and adds the axis. That is one
  `sin`/`cos` pair per hand per frame, plus a multiply-add per vertex.
  This is the first arithmetic on layout geometry that the device does,
  and **ADR 0004 is amended** to say so. The shape and the axis are
  still build-time constants.

### 5.4 Colours

A hand or part `color:` takes what a `shape`'s does, **except that it may
not read a data source**. Palette entries, literals, and `config.*`
(`accent_color`, `data_color`, `colors.<role>`) are allowed. So are
conditionals over those. Anything that `wfb sources` lists is rejected
with a note: a hand has no `when_absent:`, and a hand is about the time.
Data-driven hand colours are §11. The 64-colour lint (`palette-dither`)
and `config-unsupported` must see every part colour, as they see a
shape's `color:`.

### 5.5 Motion (R5)

| hand | angle, clockwise from 12 | moves |
|---|---|---|
| hour | `((hour % 12) × 60 + min) × 0.5°` | every minute, so at 10:30 it sits halfway between 10 and 11 |
| minute | `min × 6°` | every minute |
| second | `sec × 6°` | every second while awake |

The hour hand advancing by the minute is not optional. A hand parked on
the numeral until the hour strikes looks broken at 10:59. There is no
sweep, because the face redraws at most once a second. There is no
author angle expression, because hands read the clock themselves (§11).
The angles live in `WfbHands.mc` (`hourAngle`/`minuteAngle`/`secondAngle`,
as in the probe), and the preview implements the same formulas.

### 5.6 The second hand, awake and asleep (R6)

`seconds:` on the `type: hands` element takes these values:

| value | meaning |
|---|---|
| `awake` (default) | drawn while awake; **not drawn while asleep** |
| `never` | the set's second hand is not drawn at all |
| `always` | **not implemented**: a friendly error naming §11 and the partial-update budget |

- It is an **error** on an element whose set has no `second:`, because
  it would do nothing.
- Codegen: a view that draws any `awake` second hand gets the
  `_sleeping` field, set by `onEnterSleep`/`onExitSleep`. The same field
  and the same hooks are shared with `always_on`, which already emits
  them. The second hand's parts are wrapped in `if (!_sleeping) { … }`
  **inside** the element's draw method. The hour and minute hands are
  unaffected. `onEnterSleep` already calls `requestUpdate()`, so the
  hand disappears on the first sleeping frame rather than a minute
  later.
- A design with no `awake` second hand and no `always_on` must generate
  **byte-identical** output to today's: no field, no hook change.
- **The start value is `false`** (awake). Whether a face that loads
  while the watch is asleep gets `onEnterSleep` first is unverified
  (§9).

### 5.7 Modes

`modes:` on a hands element accepts `active` and `always_on`. **`low_power`
is an error.** Hour and minute hands never need it, because they change
once a minute and the sleeping `onUpdate` redraws them. A second hand
would need it, and that is `seconds: always` (§11). This is not the
existing whole-disc clip mechanism: a clip around a disc the hand sweeps
is about 2/3 of the screen, which is exactly what constraint 4 warns
against. Under `always_on` the sleeping branch has `_sleeping == true`,
so an `awake` second hand is hidden there too.

### 5.8 Placing the axis, off centre included (R8)

The element's **`at:` is the axis**. It is resolved exactly like any `at:`:
an anchor on the parent box, `dx`/`dy` or polar, and relative to a
group's box when the element is inside one. There is no `size:`. The
element's extent is the **disc it sweeps**: the axis plus the *reach*,
the farthest ink of any part of any drawn hand from the axis (a vertex
distance, a line end plus half its pen, a circle's centre distance plus
its radius plus half its pen when outlined).

- `circular_extent()` returns `(axis, reach)` for it, so the
  visible-area check reasons about the real disc and not its bounding
  square. That is what already keeps a full-screen ring from warning.
- `Placed.box` is the square around the disc. It is used by
  `static-overlap`, and it would be the clip if `low_power` were ever
  allowed.
- **An off-centre axis needs nothing special.** The only author-facing
  difference is that the swept disc may reach the bezel sooner, and the
  existing visible-area check catches that per device.

### 5.9 Several sets, and Styles (R7)

**No new style mechanism.** A set is chosen per style by putting a
`type: hands` element in each `layouts:` entry:

```yaml
layouts:
  classic: {elements: {hands: {type: hands, hands: classic}}}
  sport:
    static:   {subdial_ring: {type: shape, shape: circle, filled: false, at: {dy: 45%r}, radius: 22%r, ...}}
    elements:
      hands:      {type: hands, hands: sport}
      small_secs: {type: hands, hands: small_seconds, at: {dy: 45%r}}
config:
  style:
    default: classic_dark
    choices:
      classic_dark:  {label: "Classic · Dark",  layout: classic, colors: dark}
      classic_light: {label: "Classic · Light", layout: classic, colors: light}
      sport:         {label: "Sport",           layout: sport,   colors: dark}
```

The shared dial sits in top-level `static:`/`elements:`, and each layout
holds only the hands that differ. Because layout content always draws
above shared content (plan 02 §12.3), hands land on top of the dial with
no `z:`. The same set may be placed by several elements, in several
layouts. Its constants are emitted per element, so reuse costs a copy of
the constants and no code.

A dedicated `hands:` field on a style entry, orthogonal to `layout:`, was
considered and not chosen (§10).

### 5.10 Interaction with the rest of the format

| key | on `type: hands` |
|---|---|
| `visible:` | allowed; one guard for the whole element, as for any element |
| `static:` / in a static subtree | **error**: it reads the clock (the static rule "any data binding") |
| `on_hold:` | **not a key** (not in the schema): a moving hand has no fixed box, so hold a group instead. `format.md` says why |
| `antialias:` | allowed; inherited like a shape's, and `antialias-dither` counts it |
| `z:`, `lint:`, `modes:`, `overrides:` | as on every element (with the `modes:` rule in §5.7) |
| inside `layouts:` | allowed, in `elements:`; **not** in a layout's `static:` (it is not static) |

### 5.11 Diagnostics, all driven red

| code / kind | when | severity |
|---|---|---|
| unknown hand set | `hands: nope`; the message lists the declared names | error |
| **one error, not N** | a set rejected for its own fault stays bound; elements naming it add no second error | test |
| empty set | none of `hour`/`minute`/`second` | error |
| bad part shape | `rounded_rectangle`, `ellipse`, `arc` or anything else, with a per-shape reason | error |
| key not used by this part shape | e.g. `radius:` on a polygon part | error |
| `anchor:` in a part position | always | error |
| `%` or `pt` in a part length | always | error |
| no colour | neither the part nor its hand has `color:` | error |
| data-bound colour | a hand colour reads a catalogue source | error |
| `seconds:` without a second hand | the set has no `second:` | error |
| `seconds: always` | not implemented (§11) | error |
| `modes:` has `low_power` | §5.7 | error |
| in a static subtree | §5.10 | error |
| `filled: false` on polygon/rectangle part; `thickness` on a filled circle part | the shape rules | error |
| visible-area | the swept disc crosses the bezel on a device | the existing check and severity for shapes |

**The old `analog_clock` hint** in `wfb/validate.py`'s `ELEMENT_NOT_YET`
("build them from `shape: line`") becomes an `ELEMENT_ALIASES` entry
pointing at `type: hands`, along with `hand` and `analog`.

## 6. Implementation by stage

Follow the existing pattern for each stage. File pointers are as of `09ce870`.

- **Schema** (`schema/wfb-face-1.schema.json`): a top-level `hands`, and
  `$defs/handSet`, `hand`, `handPart`, `handPosition` (an `at:`-style
  position with no `anchor`), `handLength` (a pattern allowing `px`/`%r`
  and bare numbers only), and `handsElement` (`id`, `type: hands`,
  `hands`, `at`, `seconds` enum `[awake, never]`, `modes`, `z`,
  `visible`, `antialias`, `lint`, `overrides`). Add it to `$defs/element`'s
  `oneOf`. The friendly `always` error goes through `wfb/validate.py`
  (see its `ELEMENT_NOT_YET` precedent), not through a schema enum
  message. Update the schema-walking test that asserts common keys on
  every element type, if there is one.
- **IR** (`wfb/ir.py`): `HandPart`, `Hand`, and `HandSet` dataclasses;
  `Face.hands: dict[str, HandSet]`; `Builder._build_hands` (before
  elements, and rejected names stay bound); a `HandsElement(Element)`
  with `hands: str`, `seconds: str | None`, and `_own_expressions()`
  returning every effective part colour, so that permissions, barrel,
  read plan and config-user lints pick them up for free. Reject data
  sources in colours. Add the §5.11 checks. Make the static check reject
  it explicitly, with its own reason. Add `MODES` handling for the
  `low_power` refusal.
- **Layout** (`wfb/layout.py`): a `PlacedHands` with `axis`, per-hand
  resolved parts in hand order, and `reach`. Rectangle parts become
  polygons here, in the order top-left, top-right, bottom-right,
  bottom-left. Use symmetric rounding. `circular_extent` learns it.
  `_resolve_list` dispatches it.
- **Lint** (`wfb/lint.py`): every check that reads a shape's `.color`
  also reads the part colours (grep `.color`). `antialias-dither`
  includes hands. The visible-area check works through
  `circular_extent`. Nothing new becomes suppressible.
- **Codegen** (`wfb/emit/monkeyc.py`):
  - `Layout` constants `<P>_CX/_CY`, then per part
    `<P>_<HAND>_<i>_POINTS` (`Array<Graphics.Point2D>`, via `McLiteral`),
    `_X/_Y/_RADIUS[/_THICKNESS]` or `_X1/_Y1/_X2/_Y2/_THICKNESS`. Each
    part gets a comment line naming its shape. `needs_graphics` counts
    hands polygons.
  - One `draw<Id>(dc, clock)` per hands element, shaped like the probe's
    `drawMainHands`: the visible guard, the anti-alias bracket, then per
    hand one `angle`/`sin`/`cos` and one `setColor` per part colour
    change, with the `if (!_sleeping)` wrapper for an `awake` second hand.
    `setPenWidth` is reset to 1 after a line or outlined circle.
  - `ReadPlan._analyse` adds `time.clock` for a hands element, next to
    the time-format branch.
  - `Toybox.Math` is imported when any hands element exists.
  - `_sleeping` is emitted when `always_on` or any `awake` second hand
    exists. The field doc and the `onEnterSleep`/`onExitSleep` bodies
    name both reasons.
  - `_method_doc`/`_describe` describe the element (the set name, the
    hands drawn, the seconds policy).
- **Barrel** (`runtime-lib/WfbHands.mc`): start from the probe's file,
  and add `drawCircleRotated` for an outlined circle part. Register it
  in `wfb/emit/project.py`'s `BARREL_FILES` and `_barrel_for`, copied
  only when a hands element exists. `runtime-lib/README.md` and its
  `CLAUDE.md` list it.
- **Preview** (`wfb/preview.py`, `wfb/cli.py`): `_Renderer._hands`
  rotates with the same formulas, using the sample time (10:09:42 from
  `SAMPLE`). Add `--time HH:MM[:SS]`, which overrides
  `time.hour/minute/second`, and `--asleep`, which renders the sleeping
  `onUpdate` frame: the `always_on` set when the design has one,
  otherwise `active`, and in both cases without `awake` second hands.
  Both go through `PreviewOptions`.
- **Example** (`examples/analog/face.yaml`): see §7 phase 2 for what it
  must exercise. Update `examples/CLAUDE.md` too.

## 7. Phases, each ending green

The fast suite must end every phase at **exactly the 5 known failures**
(`tests/CLAUDE.md`). Generated projects for designs **without** hands
(`tests/fixtures/slice`, `examples/slots`, `examples/styles`,
`examples/config`, `examples/static` if present) must stay
**byte-identical** to the pre-work output. Capture a `--no-compile`
baseline first and diff after each phase. Existing goldens must not move.

**Phase 1: front end.** Schema, validate aliases, IR, layout, lint, and
every §5.11 diagnostic with a test that drives it red and checks its line.
Add resolution tests: 44%r → 57 px on 260 and 62 px on 280, a mirrored
pair resolving to mirrored pixels, rectangle → polygon order, reach, an
off-centre axis inside a group, and `circular_extent`. Until phase 2, a
design with hands may stop at codegen with a clear "not implemented yet"
message, but never silently.

**Phase 2: back end.** `Layout` constants, the view method, `_sleeping`,
the barrel, imports and the read plan. Codegen tests: the method shape;
`_sleeping` present only when needed (`seconds: never` plus no
`always_on` gives none); no `Toybox.Math` without hands; and the
byte-identity checks above. **`examples/analog/face.yaml`** must use:
a shared static dial, **two sets in two layouts** switched by three
`config: style:` entries, an **off-centre** small-seconds hands element,
at least one `seconds: awake` and one element with no second hand drawn,
all four part shapes, a `config.*` colour on a hand, and a pin above the
hands. It must build **warning-free with real `monkeyc` on all three
targets**. Record `--build-stats` for it. Add a golden for the generated
view and one `Layout` of the example if the golden machinery allows it
without disturbing the slice goldens; otherwise, a codegen test that
asserts the key lines.

**Phase 3: preview and docs.** The preview renderer, `--time` and
`--asleep`, and pixel tests that exercise the contrast: at `--time
3:00:00` the minute hand's tip pixel is straight up and the hour hand's
is to the right, and at `9:00:00` the hour hand's is to the left. An
`--asleep` render has no second-hand pixel where the awake render has
one. Then the docs sweep. Integration (the coordinator) handles the
history entry, deleting this plan, and the commit.

**Docs to update in phase 3 (same-commit rule):**
- `docs/format.md`: a new "Analog hands" section under Elements. Also
  fix "Every element takes…" and any "seven element types" count.
- `docs/limitations.md`: §1 ("no rotated primitive; hands rotate by
  runtime trigonometry"; "no second hand while asleep") and §2 (what
  §11 leaves out).
- ADR 0004: a dated amendment for the runtime rotation and the eighth
  element type.
- ADR 0006 §5: a dated note on `seconds: awake` and the shared
  `_sleeping`.
- `docs/lore/roadmap.md` and root `CLAUDE.md` §1/§6: the element count,
  "Recently built", and removing "Analog hands (`type: hand`) still do
  not exist".
- `docs/research/04-prior-art.md`: a one-line note on what shipped
  against WFF's `AnalogClock`.

## 8. Limitations (what `docs/limitations.md` will say)

1. **No second hand while asleep.** It is hidden. Showing it would take
   `onPartialUpdate` with a moving clip, plus a full-frame buffer
   repainted every minute. That is a different buffer architecture from
   `static:`'s paint-once buffer (§11).
2. **No sweep.** At most one redraw a second.
3. **Primitives only, four kinds.** No rounded rectangle, ellipse or arc
   parts, no bitmap hands, no outlined polygons.
4. **Rotation is Monkey C arithmetic every frame.** Its CPU and battery
   cost is unmeasured (no simulator, no watch). The memory cost is
   measured and is about a kilobyte.
5. **Edges of rotated polygons alias on a 64-colour MIP panel.**
   `antialias:` is the lever, with the usual `antialias-dither` tradeoff.
   What it looks like is unobserved.
6. **Coordinates resolve to whole pixels in the hand frame.** A hand
   thinner than about 2 px may lose its taper.
7. **Hand colours cannot read data**, only palette, literal and
   `config.*`.
8. **12-hour dial only.** The hour hand turns twice a day. There is no
   24-hour (GMT) hand.
9. **Hands cannot be held**, although a group around them can.

## 9. What cannot be verified here

There is no simulator and no watch (`docs/lore/codegen.md` finding 11), so
the following need the user's host simulator or a watch:

- that the hands point where the preview says at a few known times
  (10:09:42, 3:00, 9:00);
- that the second hand vanishes on the first sleeping frame and returns
  on wake. The simulator has a low-power toggle;
- whether a face loaded while asleep receives `onEnterSleep` (the `false`
  start value, §5.6);
- the look of rotated polygon edges, with and without `antialias:`, and
  of a thick rotated `drawLine`'s ends;
- per-frame CPU cost.

## 10. Considered and not chosen

- **Inline hands on the element, with no named sets.** Simpler, but R3
  asks for names, and several layouts reusing one set would duplicate it.
- **`type: hand`, one element per hand.** It gives per-hand `z:` and
  `visible:`, but splits one design across three elements that must
  share one axis. The axis would be restated three times, and R4 is
  better served by stating it once.
- **An explicit `axis:`/`pivot:` offset on each hand**, so coordinates
  pasted from a drawing tool with the pivot elsewhere could be used
  as-is. That is two conventions for one thing. The origin is the axis,
  full stop.
- **A `hands:` field on a `config: style:` entry** (a third axis beside
  `layout:`/`colors:`). It avoids a layout per hand set, but it is a new
  style mechanism, and `layouts:` already does this with no new concept
  (§5.9). It can be revisited if the layout-per-set pattern becomes
  painful.
- **Precomputed rotation tables or rotated bitmaps**: see the probe
  README.
- **`AffineTransform.transformPoints`**: see the probe README; a
  later measured optimisation.

## 11. Out of scope, recorded as follow-ups

- **`seconds: always`**: a seconds hand while asleep, the SDK sample's
  technique (a full-frame buffer holding everything but the second hand,
  repainted each `onUpdate`, plus a per-second clip around the hand's
  bounding box). Needs its own plan, a probe, and the partial-update
  budget lint taught about moving clips.
- **`arc` parts** (rotate the centre and offset the start angle).
- **Data-driven hand colours** (would need a `when_absent:` story).
- **A gauge needle**: a hands-like element whose angle is an authored
  expression (battery, heart rate). The rotation machinery is the same;
  the format question is not.
- **24-hour hands; a minute hand that creeps with the seconds.**
- **A `wfb new -t analog` template.**

## 12. Decisions taken without a round-trip (for review)

The user delegated the build, so these were decided on the
recommendation rather than asked:

1. **Named sets plus a placing element** (`hands:` + `type: hands`),
   rather than per-hand elements or inline definitions.
2. **The origin is the axis**, in the format's own screen convention
   (negative `dy` is toward 12).
3. **`seconds: awake` is the default**; `never` exists and `always` is
   reserved.
4. **Styles through `layouts:`**, with no new style-entry field.
5. **Four part shapes**, and `px`/`%r` only.
6. **Off-centre axes are built, not just planned.** They cost nothing
   beyond resolving `at:` like any element, so refusing them would be the
   extra work.

## 13. What shipped (2026-09-14)

Built in one pass by a Sonnet subagent against this plan. The coordinator
then reviewed it, fixed what is listed under "Review fixes", and
re-ran every gate.

**Measured.** Every figure is from a real `monkeyc` build with
`--build-stats`, and each build was warning-free.

| Design | fenix8solar47mm | fenix8solar51mm | fr955 |
|---|---|---|---|
| `examples/analog/face.yaml` | 4,561 B (3.5%) | 4,562 B (3.5%) | 4,561 B (3.5%) |

These are the figures after review. The subagent's own build measured
4,578–4,579 B; the 17 B difference is the `setColor` de-duplication
below. Most of the example's cost is the dial and the Styles machinery.
A hands-only design measured about 2 KB, as the probe predicted.

**Gates.** The fast suite ends at exactly the 5 known failures. The 8
designs that generated before this work (`complications`, `config`,
`graph`, `shapes`, `slice`, `slots`, `styles`, `sun`) produce
byte-identical `--no-compile` projects. No existing golden moved.
`test_example_compiles[analog]` passes in the slow suite.

**Deviations the subagent reported:**

- There is no golden for the example. `tests/test_hands_codegen.py`
  asserts the key lines instead; this is the fallback §7 allowed.
- `seconds: never` also drops that hand's `Layout` constants, not only
  its drawing. Its colours reach no lint either (a review fix, below).
- The rejected part shapes (`rounded_rectangle`, `ellipse`, `arc`, `text`,
  `icon`) are in the schema's `handPart.shape` enum, so that the IR can give
  each one its own reason. If such a part also has keys only its own shape
  would take (`start_angle:` on an `arc` part), the schema's unknown-key
  error fires first. The error is still real, but it is the less helpful
  one.
- The example's subdial and pin are in `classic`, not in `sport` (§5.9
  sketched them in `sport`).

**Review fixes (the coordinator, same session):**

1. Author-facing messages and schema descriptions pointed at this plan
   file, which is deleted once built. They now point at
   `docs/limitations.md` and `docs/format.md`. Plan-requirement labels
   (R4, R5, R8) in `docs/format.md` and the example header were
   removed, following the precedent set when plans 01–03 were deleted.
2. `%`/`pt` in a hand length reported only "expected number, got string",
   and `anchor:` only "unknown key". A pre-schema check,
   `wfb/validate.py` `_check_hand_frame`, now gives one error for each,
   with the reason (§5.3).
3. `seconds: never` on a set with only a second hand drew nothing and
   passed clean. It is now an error (no silent no-ops), and a never-drawn
   second hand's colours no longer count as used.
4. `setColor` was emitted before every part. It is now emitted only when
   the colour changes within a hand (§6).
5. The dither-suppression path through hand colours had no test. Four
   tests now cover it, including the contrast case (a colour read only by
   a hand, which is exactly what the pre-fix `_users_of` got wrong).
6. `test_hands_codegen.py` skipped when the example was missing. It now
   fails, as the slice fixture's tests do.

Each new review test was driven red by reverting its fix, and then
restored.

**Still unverified** (§9, unchanged): everything behavioural on a watch
or a simulator.
