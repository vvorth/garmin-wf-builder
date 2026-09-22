# Patterns

A pattern draws **one template many times** — hour and minute ticks, a
segmented ring, a row of week dots — as a single element instead of dozens.
This chapter covers the `pattern` element: the `radial`/`linear` placement
rule, the six part shapes a template can use, and how colour, `visible:` and
text can vary per copy.

## At a glance

| Key | Values | Default | Meaning |
|---|---|---|---|
| `pattern` | `radial`\|`linear` | required | how copy `i` is placed — see the table below |
| `at` | anchor / `dx`,`dy` / `angle`,`radius` | — | radial: the centre every copy turns about; linear: copy 0's own origin |
| `count` | integer, 1–360 | required | how many copies |
| `step` | radial: an angle; linear: required `{dx, dy}` | radial: `360deg / count` | the gap between copies |
| `start` | angle (radial only) | `0deg` | the angle of copy 0 |
| `skip` / `skip_every` | copy indices / an integer | — | leave copies undrawn |
| `parts` | 1–16 of `polygon`\|`rectangle`\|`line`\|`circle`\|`arc`\|`text` | required | the template, drawn in list order — keys per shape below |
| `color` | palette entry, literal, `config.*`, conditional, plus `copy` and any data source | — | the default for every part without its own |
| `when_absent` | `hide` | — | required once a colour or part `visible:` can read absent data |
| `visible` (on a part) | boolean expression, `copy` bound | — | per-copy — see [Per-copy part `visible:`](#per-copy-part-visible) |
| `static` | `true`\|`false` | `false` | most patterns belong here — see [Elements](elements.md#static--draw-it-once-then-blit-it) |
| `antialias` | `true`\|`false` | face default (`false`) | brackets the whole pattern's drawing |
| `min_1px` | `true`\|`false` | face default (`false`) | inherited by every part; a part may override again |

## Example

```yaml
hour_ticks:
  type: pattern
  pattern: radial
  count: 12
  skip: [0]                          # no tick at 12: a doubled marker goes there
twelve:
  type: pattern
  pattern: linear                    # copies step in a straight line
  count: 2
  step: { dx: 6%r }
week_dots:
  type: pattern
  pattern: linear
  count: 7
  step: { dx: 10%r }
  parts:
    - shape: circle
      radius: 2%r
      color: "copy == (date.weekday + 5) % 7 ? palette.cyan : palette.black"  # today lit
test_visibility:                     # a move-bar meter
  type: pattern
  pattern: linear
  count: 5
  when_absent: hide                  # no move-bar reading: hide the whole row
  parts:
    - { shape: rectangle, size: { width: 4%r, height: 4%r },
        visible: "copy <= activity.move_bar_level - 1" }   # per-copy visibility
```

![patterns example](../screenshots/patterns.png)

A pattern draws one template many times: `radial` turns each copy about the
centre, and `linear` steps it by whole pixels. `copy` is the copy's index. You
can use it in a colour, a part's `visible:`, or a text part's `value:`. Parts
may also be an `arc` centred on the pattern (the slate ring segments).
`start:` rotates the first copy (the orange diagonal triangles).

### `pattern`

```yaml
static:
  minute_ticks:
    type: pattern
    pattern: radial            # radial | linear
    at: {anchor: center}       # the centre every copy turns about
    count: 60                  # 1 to 360 copies
    # step: 6deg               # default: 360deg / count
    # start: 0deg              # where copy 0 points (default 12 o'clock)
    skip_every: 5              # leave copies 0, 5, 10, ... to the hour ticks
    color: palette.gray        # the default for every part without its own
    antialias: true
    parts:                     # copy 0, drawn at 12 o'clock; origin = at:
      - {shape: line, at: {dy: -94%r}, to: {dy: -88%r}, thickness: 1px}

elements:
  week_dots:                                     # Monday to Sunday, today lit
    type: pattern
    pattern: linear
    at: {anchor: center, dx: -30%r, dy: 36%r}   # copy 0's origin
    count: 7
    step: {dx: 10%r}                             # copy i sits at at + i * step
    color: "copy == (date.weekday + 5) % 7 ? palette.cyan : palette.black"
    parts:
      - {shape: circle, radius: 2%r}
```

A pattern is **one template drawn many times**: 1 to 16 primitives (its
`parts:`) and a rule for where each copy goes. Hour and minute ticks, a
segmented ring and a row of dots are each one element instead of sixty.

**The template is authored like a hand** (see [Analog hands](analog-hands.md#analog-hands)):
it is copy 0, drawn **as it looks at 12 o'clock**, in a frame whose
**origin is the pattern's `at:`**. `dx` is positive to the right and `dy`
positive *down*, so a tick near the rim sits at negative `dy`. Part
positions take `px` and `%r` only, and no `anchor:` (the origin is the
anchor). A polar `{angle, radius}` position works too. Every part length
resolves to whole pixels at build time, rounded half away from zero, the
same as a hand part.

| `pattern:` | copy `i` is | `step:` | `start:` |
|---|---|---|---|
| `radial` | the template turned **clockwise** by `start + i × step` about `at:` | an angle; default `360deg / count`; negative turns counter-clockwise | the angle of copy 0; default `0deg` |
| `linear` | the template moved to `at + i × step` | **required**: `{dx, dy}`, lengths as in `at:` (`px`, `%`, `%r`; not `pt`), either may be omitted | an error: there is nothing to turn |

A linear `step:` is resolved to **whole pixels once**, so every gap is the
same size. The price is that the whole row may be up to half a pixel per copy
longer or shorter than `count × step`, which is less visible than uneven
gaps.

**Leaving copies out.** `skip: [0, 6]` skips those copy indices (0-based).
`skip_every: 5` skips every copy whose index is a multiple of 5. The two
combine. This is how a minute ring leaves room for the hour ticks without a
second rule.

**Parts** are the four hand primitives, plus `arc` and `text`:

| `shape:` | keys | per copy |
|---|---|---|
| `polygon` | `points` (3–64) | each vertex transformed, `fillPolygon` |
| `rectangle` | `at` (its centre, default the origin), `size`, `align`, `vertical_align` | **becomes a 4-point polygon at build time**, because a turned rectangle is a polygon |
| `line` | `at` (start, default the origin), `to`, `thickness` (default 1px) | both ends transformed, `drawLine` |
| `circle` | `at` (default the origin), `radius`, `filled` (default true), `thickness` (only when `filled: false`), `align`, `vertical_align` | the centre transformed, `fillCircle`/`drawCircle` |
| `arc` | `radius`, `thickness` (default 1px), `start_angle`, `sweep`; **no `at:`, no `align`/`vertical_align`** | centred on the copy's origin. In a radial pattern its start angle turns with the copy, which gives a segmented ring |
| `text` | `at` (the anchor, default the origin), `value` **or** `text`, `format`, `font`, `align`, `vertical_align`, `curve`, `if_unavailable` | the anchor transformed and rounded half up; the glyphs stay **upright**, unless `curve:` and a `face:` font turn them too (see [Text parts](#text-parts) below) |

`rounded_rectangle` and `ellipse` are rejected, because no `Dc` call draws
either one turned. `icon` is rejected too (see [Not yet
implemented](../limitations.md#2-not-implemented-yet)). So is `filled: false` on
`polygon`/`rectangle`, because there is no `drawPolygon`. `at:` on an `arc`
part is rejected: an off-centre arc would have to move its centre as well
as its angle, and nothing needed it yet. A key a part's shape does not read
is an error, as everywhere else — including `align`/`vertical_align` on
`polygon`, `line` and `arc`, rejected for the reasons in
[Placement: `at:` and `align:`](placement.md#placement-at-and-align), which also covers
how `rectangle`/`circle` align in the template's own frame, turning or
stepping with the copy like the rest of the part (unlike a `text` part's
anchor-only alignment, above).

**A part may also declare its own `min_1px:`**, overriding whatever it
would otherwise inherit from the pattern element. It governs the same
`%`/`%r` lengths as everywhere else this key applies: a `rectangle` part's
`size:`, a `line`/`circle`/`arc` part's `thickness:`, a `circle`/`arc`
part's `radius:`. See [`min_1px:`](elements.md#min_1px--never-let-a-relative-length-round-to-nothing).

The element itself, `type: pattern`, refuses `align`/`vertical_align` too —
its `at:` is the origin every copy turns about or steps from, not a box —
see [Placement: `at:` and `align:`](placement.md#placement-at-and-align).

**Colours** work as on a hand. The element's `color:` is the default, and a
part's own `color:` overrides it. A part left with neither is an error. A
colour may be a palette entry, a literal, `config.*`, or a conditional over
those, and, unlike a hand's, it may also read two more things:

* **`copy`**, the index of the copy being drawn (0-based, in the same
  numbering `skip:` uses). It is bound in a pattern's colours, its parts'
  `visible:` (below) and a text part's `value:`, and nowhere else. `copy % 2 == 0 ? palette.a :
  palette.b` alternates two colours.
* **Any data source**, including one that can be absent (`activity.steps`,
  `complication.*`), which needs the pattern's **`when_absent:`** (below).
  `wfb sources` shows which sources can be absent.

Together `copy` and a data source let one copy stand out. `date.weekday` is
1 (Sunday) to 7 (Saturday), so `(date.weekday + 5) % 7` is 0 on Monday, and
`copy == (date.weekday + 5) % 7` is true for exactly one copy of a seven-copy
row: today's.

The data is read once per frame, before the loop. A colour that reads `copy`
is set inside the loop, once per copy, and every other colour is set before
the loop.

#### Text parts

A `shape: text` part draws a string at a point that turns
(radial) or steps (linear) with the copy. Twelve hour numerals are one
pattern instead of twelve polar `text` elements:

```yaml
static:
  hour_numerals:
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 12                          # step defaults to 30deg
    color: palette.white
    parts:
      - shape: text
        value: "(copy + 11) % 12 + 1"  # copy 0 -> "12", copy 1 -> "1", ... copy 11 -> "11"
        font: font.hourfont
        at: {dy: -55%r}                # copy 0's anchor, above the centre: +dy is down
```

**The glyphs stay upright by default.** A bitmap font cannot turn, and a
dial's numerals need not either. Only the anchor point goes through the
copy's transform. It is then rounded half up to a whole pixel, on the watch
and in the preview alike, and the text is placed on it with `align:`/
`vertical_align:` following the one placement rule every accepting kind
shares: [Placement: `at:` and `align:`](placement.md#placement-at-and-align). This
part's placement box is that copy's own string width × line height, in the
pattern's frame.

**Unless `font:` names a `face:` (vector) font and the part carries its own
`curve:`** (plan 11 slice 2) — then the glyphs turn too, tangent to (or
around) the copy's own position, not just the anchor. This is what finally
answers "a bitmap font cannot turn": twelve hour numerals, each rotated to
sit tangent to its own radius, as one pattern:

```yaml
fonts:
  bezel:
    face: [RobotoCondensedBold, RobotoCondensedRegular]
    size: 9%r
elements:
  - id: hour_numerals
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 12
    color: palette.white
    parts:
      - shape: text
        value: "(copy + 11) % 12 + 1"
        font: font.bezel
        at: {dy: -74%r}
        curve:
          style: angled
          angle: 0deg          # this part's own LOCAL angle, for copy 0
```

`curve:` here takes exactly the same `style:`/`angle:`/`radius:`/
`direction:` a standalone `text` element's own `curve:` does (see
["`curve:` — rotated and radial text"](text.md#curve--rotated-and-radial-text)
above for the full rules: a `face:` font is required, `radius:`/
`direction:` are rejected on `angled`, `vertical_align: bottom` is a build
error under `style: angled` but accepted under `style: radial`).
**The one real difference:** `angle:` is in the *template's
own local frame*, for copy 0 alone — a radial pattern turns every later
copy's angle right along with its anchor, the same way a pattern `shape:
arc` part's own `start_angle:` already turns with the copy (its own row
above). So `angle: 0deg` above draws every numeral tangent to its own
radius (pointing outward from the dial's centre), with one authored angle,
not twelve. A linear pattern never turns at all, so its copies simply keep
the part's own angle unchanged — there is no copy angle to compose with.
`style: radial`'s `radius:` is a `handLength` here (px or `%r` only — a
pattern part's frame has no parent box for `%` and no font in scope for
`pt`, the same restriction every other pattern-part length already
carries), and its circle is centred on that copy's own anchor, not a fixed
point.

`if_unavailable:` (`error`/`hide`) works the same way here as on a
standalone `text` element, set on the part to override the font's own
value outright — `error` fails the whole build naming the device and the
missing face(s); `hide` makes just that one part not draw on a target that
fails the font's availability gates, leaving every other part of the same
pattern (and every other element sharing the font) unaffected.

The keys are those of a `text` element. **`value:`** is an expression in
which `copy` is bound. **`text:`** is a fixed string, the same on every copy.
Give exactly one of the two. `format:` (a numeric format, as on `text`)
applies to `value:` only. `font:` names a `fonts:` entry or a system font,
and defaults to `FONT_MEDIUM`. `align:` is `left`/`center`/`right` and
`vertical_align:` is `top`/`center`/`bottom`, both defaulting to `center`
(`bottom` as on [`text`](text.md#text)). `color:` and `visible:` work as on any part.

**`value:` may read only `copy`** and literals. A data source, a palette
entry or `config.*` in it is a build error. The compiler renders every
copy's string at build time, because a custom font is subsetted to the
glyphs the design can draw, and the pattern's extent is measured from the
real strings. A reading taken on the watch would make both unknowable. Data
in a text part is not implemented yet (see [Not yet
implemented](../limitations.md#2-not-implemented-yet)). A conditional over `copy` covers labels
that are not numbers: `copy == 0 ? "M" : copy == 1 ? "T" : ...`.

On the watch the compiled `value:` is evaluated once per copy, like a
`copy` colour. The host evaluates the same expression only to measure,
subset the font and draw the preview. **Write `%` with a non-negative left
side**: `(copy + 11) % 12 + 1` rather than `(copy - 1) % 12`. Python and
Monkey C may disagree about the sign of `%` on a negative number, which is
unverified and applies to every expression, not only this one.

A text part in a pattern costs little. The two text patterns in
`examples/features/patterns/` (12 numerals and 7 weekday initials, in one custom
font) add about 470 B together on `fenix8solar47mm`.

#### `when_absent:` on a pattern

A colour (the element's own, or any part's) or a part `visible:` (below) may
read a source that can be absent, but only once the pattern declares
`when_absent: hide`. There is no `placeholder:`/`fallback:` here -- unlike
`text`/`progress`, a pattern has no single *value* to substitute one for.
Absence hides the **whole pattern**: every copy, every part, not just the
one binding that turned out missing. This is deliberately blunter than the
per-element `visible:` rule ("absent means hidden," but only for *that*
element): the reading is taken once per frame, before the copy loop, so its
absence is a fact about the frame, not about one copy -- there is no "copy 3
specifically has no data" to react to.

`when_absent: hide` is **required** as soon as any such reading exists, and
is a **note** ("has no effect") when declared but nothing on the pattern is
ever absent -- the same wording the compiler gives every other element
kind's unnecessary `when_absent:`.

#### Per-copy part `visible:`

A part may carry its own `visible:`, a boolean expression evaluated
**separately for each copy**, with `copy` bound the same as in a colour:
false hides that part, for that one copy, leaving other parts and other
copies untouched. It takes the same boolean-only rule the element-level
`visible:` does (no truthiness, `activity.steps > 0` not `activity.steps`).

A move-bar row shows both together -- an always-drawn track, and a lit part
gated per copy:

```yaml
elements:
  move_bars:
    type: pattern
    pattern: linear
    at: {anchor: center, dx: -20%r, dy: 25%r}
    count: 5
    step: {dx: 10%r}
    when_absent: hide                 # required: the lit part below reads
                                       # a source that can be absent
    parts:
      - {shape: rectangle, size: {width: 8%r, height: 8%r}, color: palette.gray}
      - {shape: rectangle, size: {width: 6%r, height: 6%r}, color: palette.black}
      - shape: rectangle
        size: {width: 4%r, height: 4%r}
        visible: "copy <= activity.move_bar_level - 1"
        color: palette.orange
```

A source that can be absent, read inside a part `visible:`, is governed by
the pattern's own `when_absent: hide` -- the whole pattern hides -- **not**
by "absent means this part is hidden," which is what the same nullable
reading would mean inside an ordinary element's `visible:`. This is a
deliberate difference from element-level `visible:`, for the reason above:
the reading is per-frame, not per-copy.

A **hand** part does not accept `visible:` -- writing it there is a schema
error naming the key, not a silent no-op.

**Draw order** is copy by copy, in ascending index, with a copy's parts in
list order.

**It takes the common keys** `id`, `type`, `at`, `modes`, `z`, `visible`,
`static`, `antialias`, `min_1px`, `lint` and `overrides`. `size:` does not exist,
because the extent comes from the ink. `on_hold:` is not accepted; hold a
`group` around the pattern instead. `modes:` may not contain `low_power`.
A fixed pattern gains nothing from `onPartialUpdate`, and its clip would be
its whole extent.

**`static:` is where most patterns belong.** The loop then runs once, when
the buffer is filled, instead of once a second. A pattern whose colour or
part `visible:` reads a data source cannot be static (the ordinary
static-binding error: the buffer would freeze the reading). One that reads
only `copy` can, because a copy's index never changes.

**`antialias:` works exactly as on a `shape`.** The element's own value,
or the one it inherits from its group or the face, brackets the whole
pattern. It counts toward `antialias-dither` like any other primitive. A
turned tick is where anti-aliasing helps most: without it, a rotated edge
stair-steps.

**`min_1px:` works the same way, one level deeper.** The element's own
value, or the one it inherits from its group or the face, is what every
part inherits in turn — and, unlike `antialias:`, a part may override it
again with its own `min_1px:`, both ways, exactly as everywhere else this
key applies. See [`min_1px:`](elements.md#min_1px--never-let-a-relative-length-round-to-nothing).

**How it is drawn: the watch loops.** The template (every part, and the
origin) is resolved to per-device `Layout` constants like any other
element. The generated method loops over the copies and transforms the
template once per copy: one `sin`/`cos` pair for a radial copy, an integer
add for a linear one. It uses the same rotate-and-draw helpers as analog
hands (`runtime-lib/WfbGeom.mc`) and the same `WfbArc.drawSpan` as every
other arc. Baking the copies at build time was measured and rejected:
sixty minute ticks as separate elements add about 5 KB to the 128 KB
budget, and the loop adds about 170 B whatever the count
(`docs/research/probes/pattern-cost/`). This is the second exception to
"the watch does no layout arithmetic" (ADR 0004). Hands were the
first.

**Checks.** These are build errors, each reported on your own line:

* a radial `step:` that is not an angle, or is `0deg`;
* a linear `step:` that is not `{dx, dy}`, or is missing;
* `start:` on a linear pattern;
* radial copies that land on each other, `|step| × (count − 1) ≥ 360°`;
* a `skip:` index that is out of range or repeated, a `skip_every:`
  larger than `count`, and skipping every copy;
* on a `text` part: both `value:` and `text:`, or neither; a `value:` that
  reads anything but `copy`, or is not a number or string; `format:` with
  `text:`;
* a colour or part `visible:` reading a source that can be absent, with no
  `when_absent: hide` (one error, naming every such source, not one per
  expression) -- and, the mirror case, `when_absent: hide` declared when
  nothing on the pattern is ever absent (a note).

A part `visible:` that folds to a build-time constant `false` is the
suppressible `dead-element` lint, naming `<id>.parts[N]`: the part is never
drawn, and emits no draw code at all.

Per device, the `pattern-step` lint is an error when a linear step rounds
to `{0, 0}` pixels, which would stack every copy on the first.

The element's extent is the bounding box of every drawn copy's ink -- what
`off-screen` (the rectangular framebuffer check) tests against. On a round
screen, `safe-area` tests something tighter instead: for a radial pattern,
the disc of its farthest ink from the centre, not that bounding box's own
corners. `circular_extent()`/`visible_reach()` check a full-dial tick ring,
or a full ring of `shape: text` numerals (`curve: {style: radial}` or
`angled`), as the disc or annulus sector it really is, the same way they
already check hands and a bare `shape: arc`/`circle` -- a full ring's own
bounding box is a square whose corners sit well outside the ring, so
checking *that* against the round panel would call every full-width ring
cropped even when every glyph sits comfortably inside the bezel.

See `examples/features/patterns/face.yaml` for every part shape, both kinds,
`start:`, `skip:` and `skip_every:`, a two-part template, patterns in and
out of `static:`, a per-copy colour (`week_dots`, today lit), and
`when_absent: hide` with a per-copy part `visible:` (`test_visibility`, a
move-bar row).

**What is verified, and what is not.** Verified: warning-free builds under
`-l 3` on all three targets, and `wfb preview`, which transforms the same
resolved template with the same formula. Not verified, because nothing
here runs a simulator or a watch: what the ticks look like on the panel,
how the firmware rasterises the Float coordinates a turned copy produces,
and the loop's CPU cost when a pattern is not in `static:`. See
[`docs/limitations.md`](../limitations.md).

## Not built yet

Still open for [patterns](#pattern): a text part whose `value:` reads data,
`pattern: grid`, `on_hold:` and `low_power` on a pattern, per-copy variation
other than skipping, colour and visibility, `rounded_rectangle`/`ellipse`
parts in a linear pattern, and an arc part off the pattern's centre.

See [`docs/limitations.md`](../limitations.md) §2 for all of it.

## See also

- [`examples/features/patterns/face.yaml`](../../examples/features/patterns/face.yaml) — every part shape, both kinds, `start:`, `skip:` and `skip_every:`, a two-part template, patterns in and out of `static:`, a per-copy colour, and `when_absent: hide` with a per-copy part `visible:`.
- [Analog hands](analog-hands.md#analog-hands) — the template is authored the same way a hand is.
- [Text](text.md#curve--rotated-and-radial-text) — `curve:` on a standalone `text` element, which a `shape: text` part shares.
- [Elements](elements.md) — the common keys every element shares (`modes`, `z`, `lint`, `overrides`).
- [`docs/limitations.md`](../limitations.md) — everything still open, in one list.
