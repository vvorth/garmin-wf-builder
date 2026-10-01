# Text and rotated text

`type: text` draws a data-bound or literal string, upright by default. Give it
a `curve:` and, with a device-resident `face:` font, it bends along a line or
around a circle instead — the only way to get a bezel numeral or a curved
wordmark on this platform.

![vector text example](../screenshots/vector-text.png)
*Rotated and radial text, from `examples/features/vector-text/face.yaml`.*

## At a glance

| Key | Values | Default | Meaning |
|---|---|---|---|
| `text:` | a literal string, or a template with `{expr:spec}` placeholders | required | [The `text:` template](#the-text-template) |
| `units:` | `auto`/`metric`/`statute` | — | show the placeholder's reading in the wearer's units — see [Units](data.md#units) |
| `font:` | `font.<name>` or a system name | — | [Fonts](fonts.md#fonts) |
| `color:` | colour expression | — | [Colours](colors.md) |
| `align:` | one of the nine anchor names, or a compass alias | `center` | [Placement: `at:` and `align:`](placement.md#placement-at-and-align) |
| `absent:` | `hide`, a string, or `{value: <expr>}` | — | required for a nullable reading — see [Data binding](data.md#absence-is-the-normal-case) |
| `curve.style:` | `angled`/`radial` | — | [`curve:`](#curve--rotated-and-radial-text) |
| `curve.angle:` | `Angle` | — | rotation (`angled`) or start position (`radial`) — [`curve:`](#curve--rotated-and-radial-text) |
| `curve.radius:` | `Length` | — | `radial` only — [`curve:`](#curve--rotated-and-radial-text) |
| `curve.direction:` | `clockwise`/`counter_clockwise` | `clockwise` | `radial` only — [`curve:`](#curve--rotated-and-radial-text) |
| `unsupported:` | `error`/`hide` | inherits the font's own (`error` for the subscreen) | [Fonts](fonts.md#unsupported--and-what-error-actually-promises) |
| `outline:` | `none`, a colour expression, or `{color, width}` | `none` | [`outline:`](#outline--the-stamped-ring) |

## Example

```yaml
resources:
  fonts:
    clock: { source: assets/ChivoMono-Bold.ttf, size: 24%r }   # baked, as usual
    dial: { face: [BionicSemiBold, RobotoCondensedBold], size: 8%r }   # device-resident

elements:
  hour_numerals:                   # a pattern's type: text part can turn too
    type: pattern
    pattern: radial
    count: 12
    color: color.fg
    parts:
      - type: text
        text: "{(copy + 11) % 12 + 1}"
        font: font.dial
        curve: { style: angled, angle: 90deg }

  wordmark:                        # a standalone text element, bent round a circle
    type: text
    text: "FIELD TRACK"
    font: font.dial
    curve: { style: radial, angle: 165deg, radius: 60%r, direction: counter_clockwise }
```

`Dc.drawAngledText`/`Dc.drawRadialText` are the only way to draw text that
rotates, and they refuse a resource font -- so a `fonts:` entry can name a
**device-resident scalable face** with `face:` instead of `source:`, alongside
an ordinary baked font in the same design. `face:` takes a list tried in
author order and resolved per device: `BionicSemiBold` is only on the two
solar fenix targets, so the ring and wordmark render in a different face on
fr955, where the list falls through to `RobotoCondensedBold`. `curve:` bends
a `text` element (`angled`, a straight tilt; `radial`, around a circle) or a
pattern's own `type: text` part -- twelve hour numerals, each rotated tangent
to its own radius, as one pattern instead of twelve elements. The tilted
"SOLAR" badge uses a face with no fallback at all and `unsupported: hide`:
on fr955, which doesn't publish it, the badge is simply absent rather than
failing the build -- fitting, since fr955 isn't a solar watch either.

See [Fonts](fonts.md#vector-face-fonts-device-resident-scalable-and-turnable)
for `face:` fonts, and [Text parts](patterns.md#text-parts) for a pattern's
own `type: text` part.

### `text`

```yaml
clock:
  type: text
  text: "{time.clock:%h:%M}"  # one reading, through a format spec
  font: font.clock
  at: { anchor: center, dy: -4% }
  color: color.text
  align: center               # any of the nine anchor names
  absent: hide
```

#### The `text:` template

`text:` is the whole string, with **placeholders** in braces:

| `text:` | draws |
|---|---|
| `"XX%"` | the literal `XX%` |
| `"{activity.steps}"` | the reading, in its default rendering |
| `"{activity.steps:d}"` | the reading through a format spec |
| `"{activity.steps / 1000.0:.1f}k"` | an expression, a spec, and literal text after it |
| `"{time.clock:%H:%M}"` | a time through `strftime` codes |
| `"{heart_rate.current:d} bpm / {activity.steps:d}"` | two readings in one string |
| `"{{x}}"` | the literal `{x}`: a brace is written twice |

The placeholder is an **expression** over data sources (the language is in
[Data binding](data.md)), then optionally `:` and a **format spec**, exactly
the specs [Formats](data.md#formats) lists. The expression ends at the first
`:` outside parentheses, brackets and quotes, so a ternary is written in
parentheses: `"{(activity.steps > 0 ? activity.steps : 0):d}"`. Literal text
may sit on either side of the placeholder. `{unit}` is not a placeholder: it
is the reading's unit label under [`units:`](data.md#units).

**Several placeholders** draw several readings in one string,
`"{time.hour:02d}:{time.minute:02d}"`, each through its own spec, measured
and baked as one text. The element is **absent when any reading is**:
`absent: hide` hides the whole string, and `absent: "--"` draws `--` in its
place. Three things speak of a single reading, so they are errors beside
several: `absent: {value: <expr>}` (there is no one reading to substitute),
`units:` and its `{unit}` label (a conversion has one reading to convert),
and an `aod: {text: ...}` restyle (not implemented yet; the always-on frame
draws the same template). A pattern's text part reads one placeholder.

A template whose reading can be absent needs `absent:` (`hide`, a string
drawn instead, or `{value: <expr>}` substituted into the placeholder); see
[Data binding](data.md#absence-is-the-normal-case). A literal `text:` has
nothing to be absent.

`align:` follows the one placement rule every accepting kind
shares: [Placement: `at:` and `align:`](placement.md#placement-at-and-align). A `text`
element's placement box is the widest rendering × the line height (the same
box the `off-screen`/`overlap` lints already check); `at`/`anchor`/`dx`/`dy`
only ever compute *one point*, and `align:` says which point of that box
sits there. It defaults to `center`, which is why `at: {anchor: top, dy: 7%}`
by itself puts the *centre* of the text at 7% down from the top, not its
edge.

To anchor the text's own **bottom** edge to a point instead (so growing text
extends upward from a fixed point, for instance), set `align: bottom`:

```yaml
at: { anchor: top, dy: 7% }
align: bottom             # the box's bottom edge sits at dy: 7%, not its centre
```

`top` puts the box's top edge at the point instead, and `bottom_left`,
`top_right` and the rest set both edges at once.

`bottom` is the bottom of the full line box (ascent + descent), not the
typographic baseline glyphs sit on (which excludes a descender like the tail
of a "g" or "y"). `Dc.drawText` has no bottom-justify flag, so it draws by
subtracting the font's own on-device `getFontHeight` from the anchor -- exact
even for a system font, whose pixel height this compiler only knows at build
time from the SDK's published device reference, the installed device's
`simulator.json`, or its `.cft` font -- or, for a device the SDK's reference
has no page for at all, derived from a located real `.ttf`/`.otf`'s own
`head`/`hhea` tables when the user's own licensed Garmin fonts are installed.

#### `outline:` — the stamped ring

![outline example](../screenshots/outline.png)
*The hollow idiom, a solid-interior ring, and outlined upright, angled,
radial and pattern text, from `examples/features/outline/face.yaml`.*

```yaml
clock:
  type: text
  text: "{time.clock:%h:%M}"
  font: font.clock
  color: color.bg                  # interior -- reads as empty against a flat background
  outline: { color: color.text_outline, width: 2 }
```

There is no filled-outline draw mode on this platform (`Dc.drawText` has no
switch for it, and the one that exists in Garmin's own font engine is not
reachable from Connect IQ).
`outline:` is the workable substitute this project measured instead: the
string drawn a handful of times at small pixel offsets in the ring colour,
then once more, unshifted, in the element's existing `color:` — the ordinary
fill pass every `text` element already has, doing double duty as the
interior. `none` (the default, and simply omitting the key) draws no ring at
all, byte-identical to plain text.

```yaml
outline: none                        # default -- no ring, today's plain fill

outline: color.text_outline          # shorthand -- colour only, a 1px ring

outline:
  color: color.text_outline          # required in object form -- same grammar as color:
  width: 2                           # px, 1-3, default 1
```

**In a baked font the ring is one draw.** The build bakes a companion font
holding just the glyphs your ringed text uses, each dilated by the ring's
width, and draws the string once in it before the interior
([Outlines](outlines.md#three-exact-ways-to-draw-a-ring)). A system or
vector font is stamped as above.

`width:` is 1, 2 or 3, always pixels, never `%`/`%r` — a fixed visual
stroke weight, the same way Garmin's own font engine strokes at a fixed
2.0px regardless of device. A bare colour is 1px; a hollow always-on clock
usually wants 2px, where 1px can lose whole strokes. Above 3px is a build
error. `outline.color` follows exactly the same rules as `color:` — a
`color.<name>`, a literal, or a full conditional expression over either,
data sources included.

**The interior pass paints over whatever is beneath it — it does not reveal
it.** There is no `background` colour role in this format (a face's
background is an ordinary `type: rectangle` element with its own `color:`),
so "hollow, reads as the background" means repeating that same colour
reference in `color:`, as the example above does. This works perfectly
wherever the element sits over nothing but that one flat colour — but
`Graphics.BlendMode` has no destination-out formula reachable from
`drawText` (checked directly against the SDK docs), so the moment the same
text crosses a tick ring, a bezel, or another element, the interior paints a
flat-coloured patch shaped like the letterforms on top of it, never like the
earlier content showing through. Choose an interior colour that matches what
is actually underneath *at that position*, not just the face's overall
background — and see the `text-outline-interior` lint ([Lints](lints.md)),
which catches the mechanical half of this. It fires whenever the outlined
element's box overlaps an earlier-drawn one it cannot *prove* is safe: proof
needs the interior colour to be the exact same build-time constant as that
earlier element's own colour, *and* that element to be a filled, box-filling
shape (a `rectangle`/`circle`/…, not another line of text) whose box fully
contains the outlined one's — a colour match against something that only
partly crosses the box (that tick ring) still leaves the rest of the box
unaccounted for, so it still warns. The idiom above (`color:` repeating the
full-screen background's own `color:`) is exactly the case this proves safe
and stays silent about.

**Contrast is judged on the ring, not the interior.** The `contrast` lint
treats an `outline:`-bearing element differently from a plain one: since the
interior is *supposed* to match whatever is underneath it — that is the
entire point of the idiom above — checking *it* for contrast would flag
every correctly hollow element as illegible. Instead the ring is compared
against the element's own interior (a poor ring here means its inner edge
disappears into the fill, so the glyph reads as one soft blob rather than a
crisp outline), and, whenever the interior does not itself read against
the backdrop, against the backdrop too (a poor ring there means the whole
character can vanish into the page, since a hollow interior draws no other
ink at all) — two independent comparisons, either of which can warn on its
own.

**Stamp a non-anti-aliased (1-bit) font.** `outline:` stamps whatever the
referenced font already is, unconditionally — there is no way to force
anti-aliasing off for one element, since a custom font's anti-aliasing is a
*resource* attribute shared by every element that references it (the same
reason `antialias:` itself is not a `text` element key at all). Stacking
several opaque, non-blended stamps of an anti-aliased glyph
(`alphaBlendingSupport: false` on every MIP target) **hardens and thickens
the edge, never softens it**, and then dithers harder on the 64-colour
palette on top of that. This project's own baked-font default is already
1-bit (`antialias: false`), which is exactly the cheap, dither-free input
`outline:` wants — so the practical guidance is simply: don't turn
`antialias:` on for a font you plan to stamp.

`outline:` reaches every draw shape a `text` element can take — plain
upright text, `curve: {style: angled}`, and `curve: {style: radial}` alike
— wrapping whichever single draw call `curve:`/`unsupported:` already
selected in one more loop, ahead of the interior pass; it changes nothing
about which call runs or which string is drawn. The element's own
placement box grows by `width:` on every side to cover the ring, so
`off-screen`/`safe-area`/`static-overlap`/the partial-update clip are all
already correct for a ringed element with no separate check of their own.

On an AMOLED target, `aod: {outline: ...}` gives the always-on frame a ring
of its own — `none` to drop the awake one, or a different colour or width,
or a ring the awake design does not have at all (hollow AOD digits). The
box grows by whichever of the two rings is wider. See
[Always-on display](always-on-display.md#per-element-or-group).

A pattern's own `type: text` part accepts `outline:` too — see [Text parts](patterns.md#text-parts) for the one thing that
differs there: a radial pattern's per-copy rotation composes with the
ring the same way it already composes with `curve:`, and `outline.color`
may additionally read `copy`.

`outline:` is not only for text: every other drawable and a whole `group` take the same
key ([Outlines](outlines.md)).

#### `curve:` — rotated and radial text

```yaml
brand:
  type: text
  text: "GARMIN"
  font: font.bezel                # must be a face: (vector) font -- see [Fonts](fonts.md#fonts)
  at: { anchor: center, dy: -30%r }
  curve:
    style: angled
    angle: 45deg                  # a rotation from upright: 0 = level, clockwise positive
```

```yaml
bezel_text:
  type: text
  text: "BEZEL"
  font: font.bezel
  at: { anchor: center }          # radial: at: is the CENTRE OF THE CIRCLE, not a point the text passes through
  curve:
    style: radial
    angle: 90deg                   # a position: this format's own convention, 12 o'clock = 0, clockwise
    radius: 44%r
    direction: clockwise          # or counter_clockwise; default clockwise
```

Bends a `text` element's content along a straight line (`style: angled`,
`Dc.drawAngledText`) or around a circle (`style: radial`,
`Dc.drawRadialText`), instead of the plain upright `Dc.drawText` every other
`text` element draws through.

* **`curve:` requires a `face:` (vector) font.** A baked or system font
  under `curve:` is a build error quoting the SDK directly: "These APIs
  only support scalable fonts and do not support custom fonts loaded as
  resources" (`$CIQ_SDK/doc/docs/Core_Topics/Graphics.html` §Scalable
  Fonts). See ["Vector (`face:`) fonts"](fonts.md#vector-face-fonts-device-resident-scalable-and-turnable).
* **`style:` is a required discriminator**, the same precedent a `gauge`'s
  `style:` sets: the *binding* stays identical and only the rendering
  differs. `radius:`/`direction:` are rejected on `angled` — an angled line
  has no circle for either to describe.
* **`angle:` means something different per `style:`** (see ["Angles"](placement.md#angles)
  above) — never Garmin's 3-o'clock/counter-clockwise one either way; the
  compiler converts, and the generated `Layout` constant carries both values
  in a comment, exactly as `arc` already does.
  * **`radial`: a position**, [this format's own universal direction
    convention](placement.md#angles) (12 o'clock = 0, clockwise positive) — where around
    the circle the text starts, the same convention an arc's `start_angle:`
    or a pattern's `start_angle:` uses.
  * **`angled`: a rotation** — how far the text's own baseline is tilted
    away from level, clockwise positive, where `0deg` means unrotated
    (level text). This is *not* the same zero as every other angle in the
    format: `angle: 0deg` under `curve: {style: angled}` draws level text,
    not text standing on end pointing at 12 o'clock.
* **`style: radial`'s `at:` is the centre of the circle**, not a point the
  text passes through or is anchored to — the one genuinely surprising
  thing in this format, so it bears repeating. This is the same
  reinterpretation a `gauge`'s `style: arc` gives its `at:`.
* **`direction:`** (`radial` only, default `clockwise`) says which way the
  text runs around the circle starting at `angle:`.

`align:`'s horizontal half maps straight onto `TEXT_JUSTIFY_LEFT`/`CENTER`/`RIGHT`, the same
device-side justify an upright `text` already uses. A vertical `center`
OR's in `TEXT_JUSTIFY_VCENTER` (confirmed against the SDK's own
`TrueTypeFonts` sample, which does the same under both calls); what `top`
and `bottom` mean depends on `style:`:

* **`style: angled`: `top` omits `VCENTER`, and any `bottom` alignment is
  a build error.** An upright text's `bottom` is implemented by subtracting
  the font's own on-device height from the anchor *in screen space*, and
  once the baseline is rotated that subtraction no longer points along the
  text's own vertical axis, so the ink would land somewhere this compiler
  cannot predict. Use `top` or `center` instead. (`drawAngledText`'s actual
  no-`VCENTER` device behaviour is otherwise unmeasured — an open question.)
* **`style: radial`: all three values are accepted.** Measured on the real
  simulator (`fenix8solar47mm`, 2026-09-21): without `TEXT_JUSTIFY_VCENTER`,
  `Dc.drawRadialText` puts the text's **baseline** on the circle, and each
  glyph grows toward its own "up" — outward under `direction: clockwise`,
  inward under `counter_clockwise`. That *is* `bottom`, used as-is: the
  ascent lands on the glyphs' "up" side of the circle, the descent on the
  other. `top` hangs the *line box's* top edge on the circle instead, so
  the compiler emits the radius shifted by one `Graphics.getFontAscent`
  toward the glyphs' "down" side (`Layout.<P>_RADIUS -/+
  Graphics.getFontAscent(font)`, minus for clockwise, plus for
  counter_clockwise) rather than the bare radius — the whole line then
  falls on the "down" side, as an upright `top` puts the whole line below
  its anchor. `center` needs no adjustment; it is `VCENTER`, as above.

`unsupported:` (`error`/`hide`, see [Fonts](fonts.md#fonts)) works exactly the same
way on a curved element as on any other `face:`-font `text` element, and can
still be set on the element to override the font's own value outright.

**On a round screen, `safe-area` checks the curved run's own real shape, not
its bounding box's corners.** A `style: radial` run's box is a tight annulus
sector, over the angular span the text actually sweeps: `radius:` +/- half a
`line_height` for a vertical `center`; the full `line_height` to one
side for `top` (which side set by `direction:`, above); and the ascent
split off from the descent, one on each side, for `bottom` (the device's
own native, un-centred placement — see `direction:` above for which side
gets the ascent). A `style: angled` run's is that sector's or
rectangle's own rotated corners — an axis-aligned box drawn *around* either
shape has corners that are not points on the shape at all once it sits off
a multiple of 90 degrees from the screen centre, and checking those phantom
corners against the visible disc over-warns a run that never actually
reaches the bezel. `off-screen` (the rectangular *framebuffer* check) is
unaffected either way — the framebuffer really is rectangular, so its own
AABB is the right shape to test there.

> **Which way a radial glyph faces.** `direction: clockwise` faces glyphs
> outward and `counter_clockwise` faces inward, so text running along the
> bottom of the dial reads right-side up. Each glyph is rotated
> individually about its own centre, so its own vertical midline lies on
> the radius through that glyph's own centre — a ring of glyphs reads like
> spokes, confirmed against the real simulator on `fenix8solar51mm`
> (2026-09-21) with `examples/showcase`'s large roman numerals. Facing
> itself was confirmed against the real simulator on `fenix8solar47mm`
> (2026-09-21), using this project's own
> `examples/features/vector-text/face.yaml`, which authors **both**
> directions: `wordmark` (`counter_clockwise`) and `left_cw`
> (`clockwise`), plus the controlled pair `top_ccw`/`top_cw` — the same
> `angle:` and `radius:`, opposite `direction:`, isolating facing from
> position. The simulator's rendering agrees with `wfb preview` on facing,
> angular position and the twelve tangent hour numerals, for both
> directions.

Everything else on `text` keeps working untouched under `curve:` —
`text:`, `color:`, `outline:`, `visible:`, `absent:`, `sleep_update:`,
`on_hold:`, and a place in a `static:` block.

A `pattern`'s own `type: text` part accepts `curve:` too —
see [Text parts](patterns.md#text-parts) for how the authored angle composes with
the copy's own rotation.

## See also

- [`examples/features/vector-text/face.yaml`](../../examples/features/vector-text/face.yaml) — the rotated and radial text shown above.
- [Fonts](fonts.md#vector-face-fonts-device-resident-scalable-and-turnable) — `face:` fonts, required for `curve:`.
- [Patterns](patterns.md#text-parts) — a pattern's own `type: text` part, which accepts `curve:` too.
- [Placement](placement.md#placement-at-and-align) — `at:` and `align:` for every element kind.
- [Colours](colors.md) — `outline.color`'s own colour rules, identical to `color:`'s.
- [Lints](lints.md) — `text-outline-interior`, the overlap check `outline:` gets for free.
