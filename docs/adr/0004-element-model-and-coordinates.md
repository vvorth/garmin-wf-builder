# ADR 0004 — Element model and coordinate system

- **Status:** Accepted
- **Date:** 2026-09-04
- **Decides:** the layer/element vocabulary, and how a single design adapts
  across screen shapes and sizes.

## Context

The design must survive 148 px to 480 px, four screen shapes (round 115,
rectangle 37, semi-octagon 8, semi-round 4), without the author re-laying-out per
device — while still allowing per-device overrides
(`00-summary.md`, `01-platform-capabilities.md` §6).

Even the three chosen targets defeat fixed pixels: `fenix8solar47mm` and `fr955`
are 260×260 but `fenix8solar51mm` is **280×280**.

Prior art is informative in both directions. WFF's element taxonomy is good and
worth borrowing; **its coordinate model is its weakest part** — a fixed
`width`/`height` canvas that the system scales, with no anchoring
(`04-prior-art.md` §1). Wear OS's device spread is narrow enough to absorb that.
Garmin's is not.

## Decision

### 1. Element vocabulary

A tree of typed elements, borrowing WFF's shape but mapped onto Garmin's actual
`Dc` primitives (`01-platform-capabilities.md` §5):

| Element | Renders via |
|---|---|
| `group` | container; applies inherited anchor/visibility/mode, no drawing of its own |
| `text` | `drawText`, or `drawAngledText`/`drawRadialText` where a vector font is available |
| `shape` | `fillRectangle`, `fillRoundedRectangle`, `fillCircle`, `fillEllipse`, `fillPolygon`, `drawLine` |
| `image` | `drawBitmap` / `drawScaledBitmap` |
| `icon` | a single glyph from a vendored icon font, drawn via `drawText` (preferred over `image` — see `02-features-feasibility.md` §1; superseded the drawn-primitives approach this ADR originally described — see CLAUDE.md's icon-catalogue session notes) |
| `progress` | one of four styles, `arc` among them; see below — there is no separate standalone `arc` element, despite an earlier draft of this table listing one |
| `complication_slot` | a bound complication with a hit region |
| `raw` | escape hatch, see ADR 0007 |
| `hands` | analog hands (**added 2026-09-14, plan 04, §6 below**): a named set of `fillPolygon`/`drawLine`/`fillCircle`/`drawCircle` primitives, resolved per device like any other element but rotated by the time on the device itself — the one exception to "the device does no layout arithmetic" |

**As built, `shape:` exposes one entry per native `Dc` drawing call**:
`rectangle`, `rounded_rectangle`, `circle`, `ellipse`, `arc`, `polygon` and
`line`. `ellipse` and `polygon` were added later than the rest, along with a
plain unbound `arc` and — a behaviour change to designs written before it —
`filled: false` actually being honoured on `rectangle`/`rounded_rectangle`,
which the emitter had silently ignored. Two refusals are the platform's:
`filled:` is rejected outright on `arc` (there is no filled-arc primitive) and
`filled: false` is rejected on `polygon` (there is no `drawPolygon`). A
polygon's resolved vertices live in the per-device `Layout` module as one
`Array<Graphics.Point2D>` constant, which keeps §3's "the device does no layout
arithmetic" rule intact for the first coordinate in this project that is not a
scalar; `docs/research/probes/polygon-const/` is the build that settled the
shape of that constant.

`progress` is a single element with a `style` discriminator rather than four
element types, because the *binding* and *range* semantics are identical across
them and only the rendering differs:

- `style: arc` — `setPenWidth` + `drawArc`. **Constrained**: no filled sector
  exists, so thickness is a pen width, cap style is not selectable, and true
  annuli/gradients are not offered. The schema deliberately does not expose
  `innerRadius`/`outerRadius`, because promising them would be a lie.
- `style: bar` — `fillRectangle` / `fillRoundedRectangle`.
- `style: segments` — a repeated shape filling one by one.
- `style: scale` — ticks + coloured range band + pointer.

Z-order is document order, with an optional explicit `z` override. Groups nest.

**Visibility (`visible:`), as built.** The table above says a `group` "applies
inherited anchor/visibility/mode"; visibility is now a real key on every
element, not just an intention. `visible:` is a boolean expression (ADR 0005's
language, type-checked — a non-boolean is an error, since Monkey C has no
truthiness either) and **absent means hidden**: a nullable source read by the
condition contributes a null check to the same guard, and takes no
`when_absent:` policy, because there is no substitute for existence.

The *inheritance* half is implemented in the IR rather than in codegen, and the
reason is this ADR's own structure: a `group` renders nothing, so the emitter
produces no method for one, and §2's per-device resolve flattens the tree to a
list of placed elements. There is no group left downstream to gate a subtree
from. So `wfb.ir` conjoins a group's condition into every descendant's own at
build time (`Builder._push_visible`), producing one real `Expression` per leaf.
Nested groups compose because the inner group has already pushed before the
outer one runs, and everything downstream — reader hoisting, null guards, the
host preview's evaluator, the linter's constant folding — works on it with no
group-awareness at all.

Two consequences are deliberate and recorded in `docs/limitations.md`: a hidden
element still occupies its box for every build-time geometric check (visibility
is a runtime fact, and deciding whether two conditions can both hold is a
satisfiability question), and it still owns its `on_hold:` hit region (the
generated delegate has none of the frame's readings, and re-reading them at
touch time would answer about a different moment than the pixels on screen).

### 2. Coordinate system — anchors plus relative units, with polar as a first-class option

Absolute pixels are rejected as the primary model; they are available only as a
per-device override.

A position is expressed as one of:

```yaml
# cartesian, relative to an anchor on the parent (or screen)
at: { anchor: center, dx: 0, dy: -18% }

# polar -- essential for round faces, which are 115/164 devices
at: { anchor: center, angle: 45deg, radius: 38% }
```

Rules:

- **Percentages resolve against the parent box**: `%` of width for horizontal,
  `%` of height for vertical. `%r` resolves against the screen's *minor radius*,
  which is what keeps a round design circular on a non-square screen.
- **Anchors** are the nine box positions (`center`, `top_left`, `top`, …) on the
  parent group or the screen.
- **Angles** are degrees, 12 o'clock = 0, clockwise positive — chosen to match
  how a watch designer thinks, and normalised to Garmin's `drawArc` convention by
  the generator rather than by the author.
- Lengths accept `px`, `%`, `%r`, and `pt` (font-relative, resolving against the
  *actual* per-device font pixel height — see below).

This mirrors the approach the sibling Dashboard project arrived at empirically:
its `Layout` module holds fractions of screen height/width and forbids bare
fractions in drawing code. That project is direct evidence the model works for a
dense real-world face.

### 3. Safe area and shape adaptation

The device database records `screen_shape`. The compiler derives a **safe
inscribed area** per shape (a circle for `round`, the rectangle for
`rectangle`, shape-specific for `semi-round`/`semi-octagon`) and lints elements
that fall outside it (Phase 1.4). Authors position against anchors; the compiler
knows the shape.

### 3b. `deviceFamily` is the resource-qualifier directory name

`compiler.json` reports `deviceFamily` directly — `round-260x260` for
`fenix8solar47mm` and `fr955`, `round-280x280` for `fenix8solar51mm`
(`05-device-files.md` §5). That string **is** the per-device resource directory
the generator must emit (`resources-round-260x260/`), so the generator reads it
rather than deriving it from width/height. It also confirms that a bitmap font
baked for 260×260 is wrong on the 51 mm — the drift already present in the
sibling Dashboard project.

Also from the device files: **`alphaBlendingSupport` is `false` on all three
targets.** Any element property implying transparency or alpha compositing must
be gated on that flag rather than assumed.

### 3c. A font's `size:` is a length too

> **Amendment (2026-09-09).** This ADR made every *coordinate* relative and
> per-device, and §3b above says plainly that "a bitmap font baked for 260×260
> is wrong on the 51 mm" — and yet `fonts.<name>.size` was, until now, the one
> declaration in the format that could not be written in the unit that says so.
> It was a bare number meaning "pixels on the smallest target", scaled from
> there by `scale: true` against a reference device the declaration never
> names. An `icon`'s `size:` had been a proper `Length` (`9%r`) since the icon
> catalogue was rebuilt; a text font had not.

`fonts.<name>.size` now accepts either spelling:

* a **`Length`** — restricted to `px` and `%r`, resolved per device from that
  device's own minor radius. `18%r` is 23 px on a 260×260 screen and 25 px on a
  280×280 one; `12px` is twelve pixels everywhere. This is the recommended
  form, and it is the same unit and the same resolver (`wfb.units.pixel_size`)
  that every coordinate and every icon size already goes through.
* a **bare number**, unchanged in meaning, still scaled by `scale:`. Designs
  are written against it and moving it would be a silent breaking change.

`%` and `pt` are rejected: a sheet is rasterised before any element is placed,
so there is no parent box for `%` and, for a font's own size, `pt` would be
self-referential. `scale:` combined with a length is an error — the unit has
already decided.

What is deliberately **not** shared with the icon path is
`wfb.icons.bake_size`'s ink-height normalisation. That exists because the
vendored icon font aggregates ~10 third-party sets that pad glyphs differently
inside the em-square, so one file's own glyphs disagree about what a nominal
size means; an author's typeface has one such convention throughout, and
normalising a face against one reference character would scale the whole face
by that character's ink ratio and break the baseline and line-height
relationships two text elements in a row depend on. See that function's
docstring.

### 4. Per-device overrides

A design is one document; overrides are a scoped patch, never a fork:

```yaml
elements:
  - id: clock
    at: { anchor: center, dy: -12% }
    overrides:
      fenix8solar51mm: { at: { anchor: center, dy: -10% } }
      "shape:rectangle": { at: { anchor: top, dy: 8% } }
```

Override keys may be a device id, or a **capability selector** (`shape:`,
`colors:`, `touch:`, `api:`). Capability selectors are strongly preferred and
device ids are the escape hatch — the same principle as the format overall.
Overrides deep-merge; unknown device ids are a build error, not a silent no-op.

### 5. Text metrics are resolved at build time

The SDK's device reference publishes, per device *and per language*, each
`FONT_*` symbol's face and **pixel size** (`02-features-feasibility.md` §7),
extracted into `docs/research/data/devices/*.json`. So the compiler can compute
real text extents without a device.

This makes `pt` units meaningful, makes "does this label overflow its slot on
this device in this language?" a static check, and is the main reason the preview
renderer can be trusted. It is a capability hand authors do not have.

### 6. Analog hands — the one runtime rotation, and the eighth element type

> **Amendment (2026-09-14, plan 04).** §1's table and the "Consequences"
> section below both say the device performs no layout arithmetic at all.
> Analog hands (`type: hands`) are the first and only exception, because a
> hand's *angle* is the time — there is no build-time value for it to
> resolve to. Everything else about a hand still follows this ADR to the
> letter: its shape (up to 16 primitives per hand, in a frame whose origin
> is the axis) and its axis (an ordinary `at:`) are resolved to whole pixels
> per device exactly like any other element, into `Layout` constants. The
> watch's only addition is one `sin`/`cos` pair per hand per frame,
> rotating those already-resolved vertices by `((hour % 12) * 60 + min) *
> 0.5°`/`min * 6°`/`sec * 6°` — confirmed to type-check warning-free under
> strict typing by `docs/research/probes/analog-hands/`, and costing about a
> kilobyte on `--build-stats`.
>
> `Toybox.Graphics.Dc` has no rotated-primitive draw call at all (checked
> against every target's own `api.debug.xml`), so this was the only choice
> once analog hands were in scope; `Graphics.AffineTransform` could replace
> the hand-written rotation loop with one native call, and is recorded as a
> candidate, unmeasured optimisation in the probe's own README rather than
> built now.
>
> `hands:` (a named-set block, exactly like `fonts:`) and `type: hands` (the
> eighth element type, alongside §1's table) are documented in full in
> `docs/format.md` under "Analog hands". `wfb/layout.py`'s `PlacedHands`
> carries the resolved, per-hand geometry the same way every other `Placed`
> subclass carries a shape's; its own private `_round_away` rounds a
> hand-frame coordinate **half away from zero**, not the plain `round()`
> (half to even) every other element's geometry in that module uses — the
> two happen to agree except on exact `.5` boundaries, and a mirrored
> `-1.5px`/`1.5px` pair depends on which rule is applied, so a hand gets its
> own, deliberately, rather than silently inheriting the other one's
> tie-break (`wfb.preview` keeps an identical duplicate, `_round_away`, for
> the same reason `WfbArc.mc`'s own `roundAway` already has one twin, not
> a shared import across layers that must not depend on each other).
>
> **Correction (2026-09-17).** The "must not depend on each other" reasoning
> above is superseded. The helper is now a single public
> `wfb.layout.round_half_away`, imported by `wfb.preview` rather than
> duplicated — the import direction `preview -> layout` was always allowed;
> only the reverse, `layout -> preview`, is forbidden. The original
> reasoning is left in place above because it explains why the duplicate
> existed for as long as it did, not because it still holds.

### 7. Patterns — the second runtime transform, and the ninth element type

> **Amendment (2026-09-14, plan 05).** `type: pattern` repeats one template
> of up to 16 primitives, either turned about a centre (`pattern: radial`)
> or stepped along a line (`pattern: linear`). It is the second exception to
> "the device performs no layout arithmetic", and it is an exception for a
> different reason than hands. A pattern's copies *do* have build-time
> values. Baking them costs too much memory:
> `docs/research/probes/pattern-cost/` measured a 60-tick minute ring at
> +4,960 B as 60 `shape` elements and +1,369 B as one baked coordinate
> array, against **+170 B** for a loop that rotates the template on the
> watch, whatever the count. At 3.8% of the 131,072 B budget for a single
> ring, baking was not a real option.
>
> Everything else still follows this ADR. The template (in the hand frame:
> origin = the element's `at:`, `px`/`%r` only) and the origin resolve to
> whole pixels per device into `Layout` constants. A linear step resolves
> to whole pixels once. Angles, the copy count and the skipped indices are
> device-independent literals. The watch adds only the transform: one
> `sin`/`cos` pair per radial copy, or an integer multiply-add per linear
> copy. It goes through the helpers analog hands already use, moved for
> that reason into a shared `runtime-lib/WfbGeom.mc`. For a pattern in
> `static:` the loop runs once, when the buffer is filled.
>
> The preview and the extent computation apply the same transform to the
> same resolved template (`PlacedPattern.transform`), so this section's
> anti-drift argument (Consequences, second bullet) still holds. The format
> is documented in `docs/format.md` under "`pattern`".

### 8. Placement — `align`/`vertical_align` as one rule for every kind

> **Amendment (2026-09-15, plan 07).** Every element resolves a **placement
> box**, computed from its own declared geometry and never its ink, and
> `align`/`vertical_align` say which edge of that box — or its centre — sits
> on the point `at:` resolves to, independently per axis, both defaulting to
> `center` (`docs/format.md`, "Placement: `at:` and `align:`"). Plan 06
> (2026-09-15, `git show
> f5155d7:docs/plans/06-pattern-text-and-group-align.md`) had already put the
> two keys on `group` alone, alongside `text`'s own long-standing pair; plan
> 07 makes them one property of every kind of element instead of restating
> the same left/center/right rule once per kind (five hand-written copies by
> the time it was found: `group`, `text`, a pattern text part, and one each
> in the host preview's two text-drawing paths —
> `docs/plans/07-align-everywhere.md` §1.1, §3.3).
>
> Two mechanisms, chosen by how the kind is drawn — new information about
> the device's own drawing, not only a refactor of where the rule lives:
>
> - A **box-drawn** kind (`group`; from a later phase, `shape`, `progress`,
>   `graph`, a hand/pattern rectangle or circle part) resolves alignment
>   **entirely at build time**, by moving the placement box's centre before
>   the rest of that kind's own geometry is computed around it exactly as
>   before (`wfb.layout.alignment_shift`). No codegen or runtime-lib change,
>   and the default (`center`) shift is exactly `0.0` on both axes, so this
>   is byte-identical to pre-plan-07 output wherever neither key is written.
>   **Built for `shape` (rectangle, rounded_rectangle, ellipse, circle, arc —
>   not polygon or line), `progress` (both styles) and `graph` 2026-09-15,
>   plan 07 phase B** — confirming the prediction exactly: `wfb/emit/` and
>   `runtime-lib/` needed no change, because `Layout`'s `_X`/`_CX` constants
>   and the preview both already read the resolved `Placed.center`/`.box`.
> - A **glyph-drawn** kind (`text`; a pattern's `shape: text` part; **`icon`,
>   static and `icon_for:`, built 2026-09-15, plan 07 phase C**) places its
>   glyphs **on the device**, because the
>   drawn string can differ from the build-time estimate (a nullable
>   source's fallback text, a live reading longer than the widest one
>   measured). `align` picks `Dc`'s own `TEXT_JUSTIFY_LEFT/CENTER/RIGHT`
>   flag, exactly as `text` already did. `vertical_align: center` adds
>   `TEXT_JUSTIFY_VCENTER`; `top` adds nothing, `y` being `Dc.drawText`'s own
>   top-left placement. **`bottom` is new, tiny, device-side layout
>   arithmetic this ADR did not previously have**: since
>   `Toybox.Graphics.Dc` has no bottom-justify flag at all (checked against
>   every target's own `api.debug.xml`, the same way §6 checked for a
>   rotated-primitive draw call and found none), the generated code
>   subtracts the font's own `dc.getFontHeight(font)` from the anchor once,
>   per frame, rather than baking a build-time line height in. Only the
>   device's own measured height is exact for a system font, whose pixel
>   size this compiler only scrapes an estimate of from the SDK's device
>   reference (§5) — baking the subtraction in at build time would be wrong
>   exactly where §5's own justification (no device in the loop) matters
>   most. A radial pattern text part folds the same subtraction into the
>   *translation* term of its rotation (the copy's own `cy`, left otherwise
>   unchanged), so it shifts the drawn point straight up on screen
>   regardless of the copy's angle — `runtime-lib/WfbGeom.mc`'s
>   `drawTextRotated` gained no new parameter for it. **`icon`'s own anchor
>   (`Layout.<P>_CX`/`_CY`) never moves either**, by the same reasoning: only
>   its *lint* box moves, through the same build-time `alignment_shift` a
>   box-drawn kind uses, so the geometry checks reason about where the glyph
>   actually lands without the device needing a second code path.
>
> A real bug came with the plan's research, not only a naming
> inconsistency: `text`'s old `vertical_align: baseline` had *already*
> computed its lint box correctly (the box's bottom edge at the point), but
> the device and the preview both drew it exactly like `top` — there being
> no bottom-justify flag, `Resolver._justify` never added `VCENTER` for
> either value, so the lint box and the actual ink silently disagreed
> (`docs/plans/07-align-everywhere.md` §1.2). `baseline` is renamed `bottom`
> (a friendly, no-shim build error catches the old spelling) partly because
> the fix landed at the same time, and partly because the name never
> described what it drew: the bottom of the full line box, never the
> typographic baseline glyphs actually sit on.
>
> **Built 2026-09-15, plan 07 phase D:** the box-drawn mechanism reaches a
> hand or pattern part's own `rectangle`/`circle`, in the part's own
> **frame** (origin the axis/the pattern's `at:`) rather than the parent
> box §6/§7 already resolve against — `Resolver._resolve_hand_part` shifts
> the frame centre by `alignment_shift` before computing corners/reach and
> before the hand-frame's `_round_away`, so the shift turns with a hand or
> steps/turns with a pattern copy for free, the same way the rest of the
> part's geometry already does. `polygon`, `line` and (pattern only) `arc`
> parts reject both keys through the same "key not used by this shape"
> sweep §6/§7 already had, with the reason (no single `at:`; `at:`/`to:`
> already the two ends; always centred on the copy's own origin).
> `type: hands` and `type: pattern` themselves refuse the two keys
> outright, with a friendly pre-schema error: **their `at:` is the pivot
> this whole section is built around — the axis a hand set turns about, or
> the origin a pattern's copies turn about or step from — and "aligning" a
> pivot has no meaning, since moving it would change what the element
> draws, not just where its box sits** (plan 07 §6 choice 2). This is
> deliberately narrower than every other rejection in this ADR: it is not
> a missing platform primitive, but the same reasoning
> `docs/plans/07-align-everywhere.md` §1.3's table already gave for both
> element kinds before any of plan 07 was built.
>
> **Plan 07 is complete as of 2026-09-15 (phase E).** Every kind this
> section lists as accepting the two keys does; the rejections above are
> the whole set that refuses them. `examples/features/align/face.yaml` is the
> reference design exercising every accepting kind with non-default
> alignment on both axes, and `docs/format.md`'s "Placement: `at:` and
> `align:`" section is the one place the rule is written down in full.

## Consequences

- The IR carries **resolved absolute pixels per target device**, computed from
  relative units at build time. Nothing relative survives into generated Monkey C
  — the device does no layout arithmetic, which saves both memory and per-frame
  cost, **except analog hands' own rotation** (§6, amended 2026-09-14): the
  angle is the time, so it cannot be a build-time constant, and the device
  performs that one multiply-add per vertex instead.
  **Patterns** (§7, amended 2026-09-14) are the second exception: the watch
  turns or steps a pattern's resolved template once per copy, because baking
  the copies was measured at roughly 30x the memory.
  **A glyph kind's `vertical_align: bottom`** (§8, amended 2026-09-15) is a
  third, much smaller exception: one `dc.getFontHeight` subtraction from the
  anchor per frame, for a `text` element, an `icon` (static or `icon_for:`,
  built plan 07 phase C) or a pattern text part, because the platform has no
  bottom-justify flag and only the device's own font metrics are exact for a
  system font. Unlike hands' and patterns' own rotation,
  this is a plain arithmetic term, not a per-vertex transform.
  **`complication_slot`** was always a runtime exception on its own terms —
  its icon+reading pair is centred via `Dc.getTextWidthInPixels`/
  `Dc.getFontHeight` because the wearer's pick, and so the actual text, is not
  known until the value is pulled (§8's `icon_size:`/`icon_position:`
  discussion in `docs/format.md`). **Amended 2026-09-15, plan 07 phase C**:
  a non-default `align`/`vertical_align` on it moves that same runtime
  centring, with the equivalent arithmetic (`startX`/`startY` shifted by
  `0`/half/all of the pair's measured extent) computed on the device for
  every `icon_position:`, rather than a build-time box move — one more
  reason this element's position is never fully resolved at build time.
- The preview renderer consumes the **same resolved IR**, so preview and device
  cannot disagree about position. This is the anti-drift mechanism Phase 3.8 asks
  for, and it works only because layout is resolved before codegen.
- Because the resolver is pure (design + device → geometry), it is directly
  unit-testable with no Garmin toolchain.
- `semi-octagon` and `semi-round` need safe-area definitions we do not have yet;
  until then they are unsupported targets rather than silently wrong ones.

## Open

- Exact safe-area geometry for `semi-round` and `semi-octagon`. Resolvable from
  the device files' screen shape data once available.
- Whether to support a constraint solver (element A right-of element B) rather
  than only parent-relative anchors. Deferred: anchors cover the reference design
  and a solver is a large addition. Revisit if real faces demand it.

**Amendment 2026-09-17:** the icon font is no longer committed.
`tools/fetch-icon-font.py` downloads the same Nerd Fonts v3.5.1 "Symbols Only"
file (byte-identical, SHA-256 pinned) during setup and in the Docker build.
"Vendored" above now means "pinned and installed by setup", not "in the
repository"; the element model is unchanged.
