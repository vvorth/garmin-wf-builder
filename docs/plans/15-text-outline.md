# 15 — `outline:`: the stamped ring as an author-facing text feature

**Status: slices 1 and 2 built (§14) — `outline:` on a standalone `text`
element and on a pattern's own `shape: text` part, warning-free on all
three verification targets. Slice 3 (examples/screenshots) open.**
Delete this file when slice 3 lands (`docs/CLAUDE.md`). What slices 1-2
shipped is documented in `docs/guide/text.md`, `docs/guide/patterns.md`,
`docs/guide/lints.md`, `docs/guide/colors.md`, `docs/limitations.md` §2
and `docs/lore/codegen.md`; this file remains only as the design record
for the slice still to come, plus four amendments: §16 (a schema
correction found during slice 1 implementation), §17 (`text-outline-
interior`/`contrast` made colour-aware so slice 1's own canonical fixture
is warning-free, found building it), and §18 (two places slice 2's own
text, taken literally, did not match what was actually built, plus a
real `monkeyc` finding neither slice 1 nor the plan anticipated).

`docs/research/13-outline-vector-text.md` found that the platform's own
outlined-text mode (FreeType's stroker, a real two-pass "ring in one
colour, glyph in another" run) exists in Garmin's engine but is switched on
by a font-record bit no Connect IQ API can ever set — outline text is not a
draw-time switch, on this platform, full stop. `docs/research/
14-stamped-ring-text.md` measured the one workable substitute research 13
§5 named — draw the string N times at small offsets in a ring colour, then
once more at the centre in a fill colour — and closed every question
needed to build it, **except** the format itself, which research 14 §8
left as an unbuilt proposal with five open questions. The user told the
orchestrator to proceed through research, plan and implementation; this
plan resolves those five (plus a few the orchestrator's own brief raised)
under **"Decisions (orchestrator, on user's go-ahead)"** (§13) — each
recorded with its reasoning so the user can overturn any single one
without unwinding the rest, the same way plan 14 §7 records D1–D5.

---

## 1. What this builds

An `outline:` key, sibling to `color:`, on a `text` element and on a
pattern's own `shape: text` part. It draws the stamped ring research 14
measured: the string drawn N times at small integer pixel offsets in the
ring colour, then once more, unshifted, in the element's existing
`color:` — the same interior pass the format already has, doing double
duty as the fill. `outline: none` (or simply omitting the key) is
today's plain fill, byte-for-byte unchanged.

```yaml
- id: clock
  type: text
  value: time.clock
  color: palette.text
  outline: { color: palette.text_outline, width: 2 }
```

Every fact this plan leans on is already measured in research 14, not
re-derived here: the offset set (disc-perimeter, exact against a true
dilation at every radius tested), the per-font-kind reach (baked, system
and vector fonts alike; upright, `curve: angled` and `curve: radial`
alike, including the geometry proof that a screen-space offset is a valid
dilation contribution under rotation), the anti-aliasing interaction
(harder and grainier, never softer, under `alphaBlendingSupport: false`),
the cost (a loop over a small constant array, ~0.2–0.3% of the watch-face
budget at the draw counts this format actually needs), and the interior
pass's own nature (a flat paint, not a transparency reveal — confirmed
against the SDK's own documented blend-mode formulas, research 14 §6).

---

## 2. The format

### 2.1 On a `text` element

```yaml
outline: none                        # default -- no ring, today's plain fill

outline: palette.text_outline        # shorthand -- color only, width defaults to 2

outline:
  color: palette.text_outline        # required in object form -- same grammar as color:
  width: 2                           # px, 1-3; default 2 -- see D2 (§13)
```

### 2.2 On a pattern's `shape: text` part

Identical shape, one level down, following `curve:`'s own precedent
(`docs/guide/patterns.md` "Text parts"): a part's own `outline:` behaves
exactly as a standalone element's, in the template's own local frame —
there is nothing here for a radial pattern's per-copy rotation to compose
with, because (unlike `curve.angle`) an offset is a screen-space
translation, valid at any rotation without correction (research 14 §3.2).

```yaml
parts:
  - shape: text
    value: "(copy + 11) % 12 + 1"
    font: font.bezel
    color: palette.white
    outline: { color: palette.black, width: 1 }
```

### 2.3 Schema

A new `$defs/outline`:

```jsonc
"outline": {
  "description": "The stamped-ring outline (research 13/14, plan 15): draws the text N times at small pixel offsets in this colour, then once more, unshifted, in the element's own 'color:' -- the fill pass every text element already has. 'none' (the default) draws no ring at all, byte-identical to today. The shorthand form (a bare colour expression) is 'width: 2' with that colour.",
  "oneOf": [
    { "const": "none" },
    { "$ref": "#/$defs/colorExpression" },
    {
      "type": "object",
      "required": ["color"],
      "additionalProperties": false,
      "properties": {
        "color": { "$ref": "#/$defs/colorExpression" },
        "width": {
          "type": "integer",
          "minimum": 1,
          "default": 2,
          "description": "Ring width in pixels, not a Length -- always pixels, on every device, the same way a pattern's own 'count:' is a bare integer with no unit (docs/guide/patterns.md). Capped at 3 -- a build error above that, not a schema bound, so the message can cite research 14's own numbers (D6, §13). Never %/%r: the ring is a fixed visual stroke weight, the same way Garmin's own engine strokes at a fixed 2.0px regardless of device (research 13 §2.1)."
        }
      }
    }
  ]
},
```

Referenced from `textElement.outline` and from the `text`-shaped branch of
`handPart` (the pattern part schema already keeps every other key closed
per shape — `curve`/`if_unavailable` are `text`-only there today, and
`outline` joins them the same way).

### 2.4 IR

```python
@dataclass(frozen=True)
class Outline:
    """`outline:` on a `text` element or a pattern's `shape: text` part
    (plan 15) -- the stamped ring research 14 measured. `color` follows
    `Text.color`'s own grammar exactly (palette/config/data, `_color_
    expression`); `width` is a plain pixel integer, 1-3 (`Builder.
    _build_outline` rejects >3 with a friendly, research-citing error --
    not a schema bound, D6 §13-of-plan-15)."""
    color: Expression
    width: int = 2
```

`Text.outline: Outline | None = None` (mirrors `Text.curve`); the same
field on `HandPart` for a `shape: text` part. `Text._own_expressions`/
`PatternElement._own_expressions` both grow to include `outline.color`
alongside `color`, so permission derivation, the barrel and the read plan
pick it up for free — the exact reason `Element.expressions()` exists as
a hook at all.

---

## 3. Colour

**The interior pass is unchanged: the element's own `color:`.** `outline:`
adds no second "fill" key — the hollow look is `color:` set to whatever
sits underneath (often the background), with `outline.color` carrying the
visible ring, exactly research 14 §8.1's own proposal:

```yaml
- id: clock
  type: text
  value: time.clock
  color: palette.bg                  # interior -- reads as empty against a flat background
  outline: { color: palette.text, width: 2 }
```

**No `background` colour role exists in this format, and this plan does
not invent one** (D1, §13). A face's background is an ordinary `shape:
rectangle` element with whatever `color:` the author gave it
(`docs/guide/shapes.md`); "hollow, reads as the background" is spelled by
repeating that same palette reference in the text element's own `color:`,
the same way `docs/guide/colors.md`'s own `config.colors.<role>` examples
already ask an author to name a role explicitly rather than infer one.
This is a real authoring trap worth documenting plainly (research 14 §6.4,
adopted verbatim into `docs/guide/text.md`): **the interior pass paints
over whatever is beneath it — it does not reveal it.** `Graphics.
BlendMode` has no destination-out formula reachable from `drawText`
(research 14 §6.1–6.2, checked directly against the SDK docs, not
inferred), so an `outline:` block whose interior colour was chosen to
match the *face's* background looks wrong the instant the same text
crosses a tick ring, a bezel, or another element — never like the earlier
content showing through, always like a flat-coloured cutout stamped on
top of it. The guide says this once, next to `outline:`'s own
description, and the new `text-outline-interior` lint (§7) catches the
mechanical half of it — the two never overlap in z-order at all — without
pretending to check the colour match itself.

**`outline.color` follows exactly the same rules as `color:`** — palette
entry, literal, `config.*`, or a full conditional expression over any of
those, including a data source — because both go through the same
builder call, `_color_expression(node, key)` (already generic over the
node/key it is handed, `wfb/ir/builder.py:4201`), and both compile to an
`Expression` whose `.code` drops straight into `dc.setColor(...)` the
same way `_color()` already reads `element.color` (`wfb/emit/monkeyc/
common.py:221`). On a pattern part, `outline.color` may read `copy`
exactly as the part's own `color:` does (`docs/guide/patterns.md`
"Colours") — the ring can alternate by copy the same way the fill can.
A nullable data source in `outline.color` is governed by the same
absence rule the interior colour already has: `_check_other_absence` on a
`text` element, the pattern's own `when_absent: hide` on a part.

---

## 4. Anti-aliasing

**No lint, no forced setting — documented guidance only** (D4, §13).
`antialias:` is not a `text` element key at all (`_reject_text_
antialias`): a custom font's anti-aliasing is a *resource* attribute
shared by every element that references that font, not a per-element
switch, and that architectural fact is exactly why the compiler cannot
quietly force it off for one `outline:` element without silently
changing every sibling element sharing the same `fonts:` entry. A system
or vector font's anti-aliasing is the device's own rendering, entirely
outside this compiler's reach either way. So `outline:` stamps whatever
the font already is, unconditionally, and `docs/guide/text.md` states
research 14 §3.3's finding next to it: stacking N opaque, non-blended
stamps of an anti-aliased glyph (`alphaBlendingSupport: false` on every
MIP target) **hardens and thickens the edge, never softens it**, and then
dithers harder on the 64-colour palette on top of that. The project's own
baked-font default is already 1-bit (`antialias: false`), which is
already the cheap, dither-free input `outline:` wants — the guidance is
"don't turn antialias on for a font you plan to stamp," stated once,
where an author will read it while writing `outline:`, not enforced.

---

## 5. Rotated and curved text

**The mechanism is one wrapper, reused by every draw call this format
already has** (research 14 §3, §7): loop over the resolved offset table,
setting the ring colour and drawing at `(anchor + offset)` each time, then
draw once more unshifted in the interior colour — no new draw call, no
new rotation math, because a screen-space anchor shift commutes with
whatever rotation the call already applies (research 14 §3.2's derivation,
confirmed against the real `drawAngledText`/`drawRadialText` signatures,
which take `(x, y)` as a plain argument separate from `angle`/`radius`).

| Draw call | What shifts per stamp | What stays fixed |
|---|---|---|
| `dc.drawText` (baked or system font, upright) | `(x, y)` | everything else |
| `dc.drawText` (vector font, upright, no `curve:`) | `(x, y)` | everything else |
| `dc.drawAngledText` (`curve: {style: angled}`) | `(x, y)` | `angle`, justify |
| `dc.drawRadialText` (`curve: {style: radial}`) | `(x, y)` — the **circle's centre** | `angle`, `radius`, `direction`, justify |
| pattern `shape: text` part, any of the above | the copy's own already-rotated/translated `(x, y)` | the part's own per-copy angle (already composed with the pattern's rotation, `_emit_pattern_text_angle_expr`) |

**Gate 4 (a vector font resolving to `null` at runtime) already wraps the
one draw call `_emit_vector_text_draw`/`_emit_pattern_text_draw` make in
`if (font != null)`.** The stamp loop and the interior draw both move
inside that same guard, unchanged in shape — a missing font draws nothing
at all, ring included, exactly as it draws nothing today.

**Pattern text parts multiply draw count by copy count**, not just by
ring width: twelve numerals at width 1 (4 offsets) become 12 × 5 = 60
draws a frame instead of 12. This is called out explicitly in
`docs/guide/patterns.md`'s own text: it is the same "N+1 per element"
cost research 14 §4.3 measured, now paid once per copy — cheap in bytes
(the loop body is emitted once regardless of copy count, the same "loop,
not unroll" shape the pattern's own template loop already uses), unmeasured
in CPU (research 14 §4.2's own honesty: no per-operation figure exists to
weigh it against, on this platform, at all).

---

## 6. Placement: layout grows with the ring

**The ink box grows by `width` on every side, and every geometry check
that already reads `PlacedText.box`/the pattern's own ink box inherits
this for free — no new geometry, no new lint.** `wfb.layout.Resolver.
_resolve_text` computes three different box shapes today depending on
`curve.style` (plain rectangle; `_rotated_text_box` for `angled`; an
annulus sector via `radial_text_angle_span`/`radial_text_band`/`arc_bbox`
for `radial`) — all three take the **measured** `width`/`line_height` as
input. Growing the ink by the ring is therefore: when `element.outline`
is set, feed `width + 2 * ring_px` and `line_height + 2 * ring_px` into
whichever of the three box functions `curve_style` already selects,
instead of the bare measured `width`/`line_height` (D9, §13) — the exact
same geometry math every `curve:` style already has, run on a slightly
larger rectangle before rotation/annulus-projection, rather than new
per-style padding logic hand-derived three times. This is conservative by
construction (a Minkowski dilation of the pre-transform box, then the
same transform, bounds the true dilated ink at least as tightly as the
existing box already bounds the plain ink) and it is what makes
`off-screen`/`safe-area`/`static-overlap`/`partial-update-budget` all
correct for a ringed element with zero new code in `wfb/lint.py` — they
already read `placed.box`. The equivalent growth applies to a pattern
`shape: text` part's own ink box (`_pattern_part_ink`, `docs/lore/
codegen.md`'s own citation for that function).

**`min_1px:` does not apply.** `width:` is already a bare pixel integer,
never `%`/`%r`, so there is no relative length here to round to zero
(§2.3's schema note); the schema does not offer `min_1px:` inside
`outline:` for the same reason it is absent from `text`/`icon`/
`complication_slot` today.

---

## 7. Lints

**`text-outline-interior` — new, suppressible.** Fires when an
`outline:`-bearing element's own (now-grown) box overlaps an
**earlier-drawn** element's box, in the same modes and layout — the
mechanical half of §3's authoring trap, modelled directly on
`check_static_overlap`'s own `_intersects`/`authored_draw_order` shape
(`wfb/lint.py:1977`), generic over `Placed` so it needs no separate code
path for a standalone `text` element versus a `pattern` element (both are
just boxes by the time this check runs). Scope: it reports the
*element's* resolved box against earlier boxes — for a pattern, the whole
pattern's own bounding box, the same granularity `off-screen`/`safe-area`
already use for a pattern, not a per-copy check. WARNING, confidence
"exact — resolved geometry, but boxes rather than ink," the same honesty
`static-overlap` states for itself: two boxes can intersect while the
glyphs never actually touch. Message: "`<id>`'s outline interior may
paint over `<other>`: the interior pass paints over what's beneath it, it
does not reveal it — check the interior colour matches what's actually
there, or move one of them." Added to `SUPPRESSIBLE` and
`docs/guide/lints.md`'s table.

**Amended 2026-09-22 (§17): the as-built check is not a bare box-overlap
test.** Building the slice 1 fixture (`tests/fixtures/outline_text/
face.yaml`) with this rule as originally written fired on every outlined
element for the trivial, correct reason that a full-screen `background`
element overlaps everything — including the canonical hollow idiom itself
(`color:` repeating the background's own colour), which is exactly the
one case that is *supposed* to be safe. §17 records the fix: a pair is
now suppressed when it can be *proven* invisible (same build-time colour
constant, and the earlier element is a filled box-covering shape whose
box fully contains the later one's), and still reported otherwise — see
`wfb.lint.check_text_outline_interior`'s own docstring for the full
reasoning, including why partial coverage never suppresses even with a
colour match. `check_contrast` needed the matching companion fix (§17)
since it independently flagged the same correct idiom on the interior
colour alone.

**Cost: no new lint — the existing ones already see the grown box.**
`check_partial_update_budget`'s clip-area trigger reads the union of
`low_power` elements' own boxes, which already includes the ring once §6
grows it, so an `outline:` element drawn in `low_power` mode is flagged
exactly as any other element with a bigger clip would be, with no new
code. There is still no per-`drawText`-call CPU figure to threshold a new
check on (research 14 §4.2's own conclusion, restated rather than
re-litigated) — a numeric "N+1 draws is too many" lint would be
inventing a budget this project has explicitly declined to invent
anywhere else (ADR 0008). `docs/guide/patterns.md` states the per-copy
multiplier in prose instead (§5 above).

**AOD lit-pixel implications: none checked yet, by design.** Plan 14's
own burn-in lint (its slice 4) does not exist, so there is nothing for
this plan to hook into today. Once it does, it measures lit-pixel/
luminance fraction from the resolved `--aod` render per AMOLED target —
the same resolved box (and, for a ring, the same smaller lit-pixel count
research 14 §4.1 already measured: a `disc-perimeter` r=2 ring lights
roughly a quarter of what the same glyph solid would) — so `outline:`
needs no special-casing there either; it is simply a design that already
lights fewer pixels than its own solid equivalent, which the future
lint will report accurately once it exists. See §11 for the format-level
compatibility with plan 14's `aod:` overrides.

---

## 8. Codegen

**Offsets are computed once, at build time, in Python — never authored**
(already decided by the orchestrator's brief, restated here as the
mechanism): `disc-perimeter` at radius `r` is every integer `(dx, dy)`
with `(r-1)² < dx² + dy² ≤ r²` (`docs/research/probes/stamped-ring/
stamp_experiment.py:107`'s own algorithm, reused verbatim, not
re-derived). For `r = 1, 2, 3` this is exactly 4, 8, 16 points — matching
research 14 §1's own measured table:

* `r=1`: `(1,0) (-1,0) (0,1) (0,-1)`
* `r=2`: `(1,1) (1,-1) (-1,1) (-1,-1) (2,0) (-2,0) (0,2) (0,-2)`
* `r=3`: 16 points (8 at `d²=5`, 4 at `d²=8`, 4 at `d²=9`) — algorithm, not
  hand-listed; same formula.

**Emitted as a flat `Array<Number>`** (`[dx0, dy0, dx1, dy1, ...]`), one
per **distinct width actually used anywhere in the design** — deduplicated
the same way a `face:` font's `_FACE`/`_SIZE` constants are emitted once
per font name, not once per element (`docs/lore/codegen.md`). Research 14
§4.3 measured the loop form as flat at both N=8 and N=16 (1,933 B of code,
only the data growing, ~5 B/`Number`) and "close to a wash" against
unrolling at N=8, pulling ahead at N=16 — **the loop is the format's
default, unconditionally**, both because it is never worse in the sizes
this format actually uses and because it is the one shape that lets
`width:` be a data value rather than a rewrite of call sites, exactly
research 14 §4.3's own closing recommendation. Placement: alongside the
other per-element geometry arrays `wfb/emit/monkeyc/layout_constants.py`
already emits (the `_POINTS` precedent for a polygon), keyed by width
rather than by element id, in each device's own `Layout.mc` — cheap
enough (three tiny arrays, worst case) that de-duplicating *across*
devices into a separate device-independent module is not worth the extra
machinery; the implementing slice measures this rather than assuming it,
per ADR 0008.

**The generated shape, per element:**

```monkeyc
dc.setColor(<outline.color.code>, Graphics.COLOR_TRANSPARENT);
var offsets = Layout.OUTLINE_OFFSETS_2;
var i = 0;
while (i < offsets.size()) {
    dc.drawText(Layout.CLOCK_X + offsets[i], y_expr + offsets[i + 1], font, text, justify);
    i += 2;
}
dc.setColor(<color.code>, Graphics.COLOR_TRANSPARENT);
dc.drawText(Layout.CLOCK_X, y_expr, font, text, justify);
```

(**Amended 2026-09-22:** `dc.setColor` moved above the loop, once, rather
than repeated on every stamp -- `outline.color` is one fixed expression
per element, never per-offset, and neither `_emit_plain_text_call` nor
`_emit_vector_draw_call` touches `Dc`'s colour state, so nothing between
one `setColor` and the next stamp could ever need a different one. Found
and fixed alongside §17, moving the same line the original snippet showed
inside the loop to just above it in `_emit_outline_loop`
(`wfb/emit/monkeyc/shapes.py`); every generated call still ends up in the
same colour, only issued once per element's ring instead of once per
stamp.)

`drawAngledText`/`drawRadialText` follow the identical shape with their
own argument lists (§5's table); a `null`-font vector branch wraps the
whole thing, loop and interior draw both, in one `if (font != null)`, not
two. A pattern text part nests this same loop inside the existing
per-copy body (`_emit_pattern_text_draw`), reading the part's own
`outline` the same way it already reads `part.color`.

---

## 9. Preview parity

**No new drawing primitive** (research 14 §7, confirmed against the two
call sites that already exist): `wfb.preview._Renderer._text` and
`._pattern_text` each already resolve to exactly one of `_draw_text`
(baked/system) or `_draw_vector_text` (vector, any `curve_style`),
`wfb/preview.py:721-745` and `:679-719`. Both calls take a plain `anchor:
tuple[int, int]` and a `color: tuple[int, int, int]` already. Outline
support is: when `placed.element.outline`/`part.outline` is set, call the
same method N times with `anchor` shifted by each resolved offset and the
outline colour, then once more unshifted with the existing `color`/
`anchor` call — the identical wrapper, at the Python level, that §8's
codegen loop is at the Monkey C level, so the two cannot drift on *which*
pixels light. The one thing that is not "loop the existing call":
reproducing the "harder, never softer" MIP compositing model for an
anti-aliased stamped font (§4's own guidance case) would need drawing
into a single-channel buffer with `max()` compositing instead of Pillow's
default alpha paste, the same scoped change research 14 §7 already
identifies — worth doing only if an example actually stamps an
anti-aliased font, which this plan's own guidance discourages authoring
in the first place (§4); the fast path (opaque 1-bit stamps, Pillow's
ordinary paste) is correct as-is and is what every example in §12 uses.

---

## 10. Interaction with `curve:`, `if_unavailable:`, `when_absent:`

No new interaction to design: `outline:` never changes which draw call is
selected (`curve:`'s own machinery, gates 1–4, `if_unavailable:`) or which
string is drawn (`value:`/`text:`, `when_absent:`/`fallback:`/
`placeholder:`) — it only wraps whichever single draw call and whichever
already-computed string those existing mechanisms produced, in a loop
plus one more call. A `text` element or pattern part that already
resolves to "draw nothing" (hidden font, absent data with
`when_absent: hide`) draws nothing with `outline:` too, for the same
reason it draws nothing today: the wrapping guard sits *outside* both the
loop and the interior draw, not between them.

---

## 11. Interaction with plan 14 (`aod:`)

Plan 14 §2.1's own `aod:` override allowlist already names `outline` as
the concrete use case that motivated writing research 13/14 at all
(research 13 §5's closing line: "If plan 14 (`aod:`) wants outlined
digits, this is the one to model"). This plan is not plan 14's to build —
plan 14 is unbuilt — so this section states compatibility only, for
whoever builds plan 14 next:

* **`outline` should join `text`'s own `aod:` overridable-keys row**
  (plan 14 §2.3's table currently lists `color`, `font`, `format` for
  `text`) — an `AodOverride` carries an optional `Outline | None`
  alongside its optional colour/font/format, resolved key-by-key the same
  way every other override field already is (plan 14 §3).
* **The canonical "hollow AOD digit" example plan 14 §2.1 already
  sketches is exactly this format**, unchanged:
  ```yaml
  aod:
    color: palette.background        # interior -- reads as empty
    outline: { color: "#555555", width: 1 }   # ring -- what actually reads
  ```
  This plan's §3 (no `background` role; repeat the palette reference) and
  §7 (`text-outline-interior`, which should run against the **resolved
  AOD frame's own draw order** once plan 14 exists, not only the awake
  one) both carry over unchanged to that override.
* **Plan 14's own D2 ("face default: hide vs show", §7) and its slice 4
  burn-in lint are unaffected by this plan** — an `outline:`-carrying
  `aod:` override is just one more resolved colour/geometry input to
  whichever lit-pixel accounting plan 14 eventually builds, per §7 above.
* **No change to plan 14's own scope or slices is proposed here** — this
  is a forward-compatibility note, not an edit to `docs/plans/14-aod.md`.

---

## 12. Examples and screenshots

**New:** `examples/features/outline/face.yaml`, named "Feature outline" to
match its siblings (`examples/features/vector-text/`, `.../patterns/`).
Exercises, per §12's own "what shipped" discipline (one example proving
every claim by rendering, not just parsing):

* a plain upright `text` element with `outline:`, baked font, hollow
  (`color:` matching a palette background entry, `outline.color` the
  visible ring) — the canonical case;
* the same element with `outline: <colour>` (shorthand form);
* `curve: {style: angled}` text with `outline:`, to show the ring
  survives rotation;
* `curve: {style: radial}` text with `outline:`, bent around the dial;
* a pattern `shape: text` part (hour numerals or similar) with
  `outline:`, plain and with `curve:`, to show the per-copy composition
  is unaffected;
* one deliberate `lint: {allow: [text-outline-interior], reason: ...}`
  case, so the new lint is proven to fire and to be suppressible, the
  same way `examples/antialias/`'s removed original proved
  `antialias-dither` (`docs/lore/`'s own citation of that example).

**Screenshot:** a `docs-shots` entry, `"outline": ("features/outline",
[], None)` in `tools/docs-shots.py`'s own table (the `"vector-text"`/
`"patterns"` entries are the precedent, `tools/docs-shots.py:44,48`),
embedded in `docs/guide/text.md` next to `outline:`'s own section and
cross-linked from `docs/guide/patterns.md`'s "Text parts".

---

## 13. Decisions (orchestrator, on user's go-ahead)

Made under the user's 2026-09-22 go-ahead to proceed through research,
plan and implementation, following plan 14 §7's own precedent of naming
each decision so it can be overturned individually. None of these has
been separately confirmed with the user; flag any the user wants revisited
before implementation starts.

**D1 — no `background` colour role.** Research 14 §8.2 item 1 asked
whether "hollow, reads as the background" needs a new palette role.
**Decided: no** — document the pattern (repeat the palette reference in
`color:`) instead. A background role is a real, separate format question
(it would also help a future transparency feature, which research 14 §6
independently found the platform cannot give text anyway) and inventing
one as a side effect of `outline:` would be exactly the kind of
format-shape decision CLAUDE.md §7 says to stop and ask about on its own,
not bundle into this plan.

**D2 — default `width`: 2.** Research 14 §8.2 item 2 left this a product
call with no usability evidence. **Decided: 2px** — the one value with
direct platform evidence (Garmin's own FreeType stroker radius, research
13 §2.1, and research 14 §2's own IoU-0.9+ agreement between that stroke
and a plain raster dilation at r=2). 1 or 3 remain one-line changes to a
face's own `outline: {width: ...}}` for an author who wants thinner or
bolder.

**D3 — no `offsets:` escape hatch; always `disc-perimeter`.** Matches
research 14 §8.2 item 3's own recommendation and the orchestrator's brief
directly: `square8` overshoots (measured, corners bulge) and `cross4`
undershoots with a quality gap that *widens* as the ring grows and is
*rotation-variant* around a radial run (research 14 §1, §3.2) — there is
no case in the evidence gathered where exposing a worse offset set buys
back enough draw-count savings to be worth the author-facing failure
mode. Offsets are computed at build time from `width:` alone (§8) and
never appear in the schema.

**D4 — `antialias:` interaction is documented guidance, not a lint or a
forced setting.** Research 14 §8.2 item 4 asked which. **Decided:
guidance only** (§4) — a forced setting is not architecturally available
without splitting a shared font resource per referencing element (the
same reason `antialias:` itself is rejected on `text` today,
`_reject_text_antialias`), and a lint would need to know whether the
*referenced font* was baked with `antialias: true`, which is checkable
but adds a whole new suppressible code for a case research 14 §3.3
already gives a one-sentence fix for ("don't"). A `text-outline-
antialias` advisory lint remains a plausible, scoped follow-up (research
14's own words) if it turns out authors hit this in practice — not
designed further here.

**D5 — scope stays `text` and pattern `shape: text` parts only.**
Research 14 §8.2 item 5 flagged `hands`/`icon` as open. **Decided: out of
scope**, matching the orchestrator's brief exactly. `hands` parts are
never text; `icon` is a single glyph from a baked icon font with no
`color:`/interior-vs-ring split of its own today, and extending outline
to it is a genuinely separate design question (does a ring make sense
around a solid glyph shape at icon sizes?) that nothing in this plan's
own evidence answers.

**D6 — width capped at 3, rejected as a build error, not a schema
bound.** The orchestrator's brief named this explicitly; the cap's
*value* comes from research 14 §1 (every offset set tested stops at
r=3) and §4.1 (ring/solid pixel ratio, already the point of a hollow
face, keeps climbing past r=3 with no further evidence gathered).
**Decided: a builder-level error** (`wfb/ir/builder.py`, code
`text-outline`, reusing the `text-curve` naming precedent of one code
shared between the element and the pattern-part builder paths), not a
schema `maximum`, so the message can cite the measured numbers (draw
counts, ring/solid ratios) the way `_check_curve_font` cites the SDK
sentence it is enforcing — a bare "must be <= 3" from jsonschema would
not explain *why*.

**D7 — shorthand `outline: <colour>` is adopted.** The orchestrator's
brief asked to check `desugar.py` for precedent and skip the shorthand if
none exists. **Decided: adopt it, but not through `desugar.py`** —
`desugar.py` itself has exactly two rewrites, both structural
(mapping-form `elements:`, the top-level `static:` block), with no
per-key "bare scalar as sugar for an object" precedent to extend. The
schema layer has a closer, better-fitting one instead:
`$defs/configChoice` (§2.3's neighbour, `schema/wfb-face-1.schema.json`
line 311) is already "either a bare `palette.<name>` reference … or an
inline `{color, label}`" for exactly the same reason — a colour is the
one field that matters most of the time, the rest have good defaults.
`outline:`'s shorthand is modelled on that precedent (a schema `oneOf`
branch, resolved in the builder, not a textual rewrite before the schema
runs), which is the right layer for it: unlike `desugar.py`'s two
rewrites, this sugar does not change element *identity* or *draw order*,
only how one key's value is spelled, so it never needs a byte-identical-
output gate the way `desugar.py`'s own two rewrites do — it is resolved
once, in `Builder._build_outline`, into the same `Outline` IR node either
spelling produces.

**D8 — `outline.color` gets full parity with `color:`, by construction,
not by a parallel implementation.** Both route through the same
`_color_expression(node, key)` (`wfb/ir/builder.py:4201`), already
generic over which key it is handed. Recorded as a decision rather than
left implicit because it rules out a plausible alternative (a narrower
"outline colour must be a palette entry or literal, no data-conditional"
restriction) that nothing in research 14 or the orchestrator's brief
asked for, and that would have been a second, needlessly restrictive
grammar to document and test.

**D9 — layout growth is done by inflating the measured rectangle, not by
padding three box shapes separately.** `width + 2*ring_px` /
`line_height + 2*ring_px` are substituted wherever `_resolve_text`
currently feeds the bare measured values into a box-computing function
(§6). **Decided over** hand-deriving a padded rectangle, a padded
rotated-box, and a padded annulus-sector independently, which would be
three chances to get the conservative-bound argument subtly wrong in one
of the three and a real maintenance hazard the next time any of those
three functions' own geometry changes.

**D10 — the new lint is `text-outline-interior`, scoped like
`static-overlap`, element-level (not per-copy) for a pattern.**
Research 14 §6.4 named the check but explicitly left it "not designed
further"; the orchestrator's brief asked for it as a real lint. **Decided:**
box-level, both-directions-of-z-order-agnostic-except-earlier-only
(matching `static-overlap`'s own "only report the pair that actually
changed" discipline, minus the hoist-detection half, which does not apply
here — nothing about `outline:` reorders draw order). A per-copy pattern
check was considered and rejected for v1: it would need the per-copy ink
box exposed at lint time in a way nothing else in `wfb/lint.py` currently
needs, for a check whose own confidence is already "boxes, not ink" —
diminishing returns for real new plumbing.

**Amended 2026-09-22 (§17):** "box-level" above turned out to mean "boxes
overlap" was too coarse a trigger on its own — it fired on the safe,
intended case (the hollow idiom's interior colour matching a fully-
covering background) just as readily as on a real risk. D10's own
"boxes, not ink" scoping stands; what changed is that a box overlap now
also needs to fail a build-time colour-equality-plus-full-containment
proof before it is reported, rather than being reported unconditionally.
See §7's own amendment and §17 for the full reasoning.

**D11 — no new cost lint; the existing `partial-update-budget` check
already sees the grown clip.** Stated as a decision because the
orchestrator's brief listed "cost" as a lint to consider adding, and the
conclusion here is that no *new* one is warranted (§7) — worth recording
explicitly rather than leaving it looking like an oversight.

**D12 — no AOD-specific lint or format change in this plan.** Plan 14's
own burn-in lint does not exist yet to extend (§7, §11). Deferred to
whoever builds plan 14 slice 4, with the forward-compatibility note in
§11 for what it should pick up automatically.

**D13 — two implementation slices for the feature itself, a third for
examples**, mirroring plan 11's own slice 1 (a whole standalone-element
vertical slice: schema through docs) / slice 2 (pattern parts) / slice 3
(examples/screenshots) shape exactly, rather than splitting by
architectural layer (schema slice, then IR slice, then codegen slice...),
which plan 11 tried in spirit and rejected: a layer-by-layer split leaves
every intermediate commit unable to build a real, warning-free `.prg`
demonstrating the feature, which is a worse state to hand between agent
sessions than "half the element kinds fully work."

---

## 14. Slices

Every slice is warning-free `monkeyc -w -l 3` on `fenix8solar47mm`,
`fenix8solar51mm` and `fr955`, and green on `pytest -m "not slow"` (the
pre-existing `test_example_is_clean_on_every_target[showcase]` failure
excepted, per `tests/CLAUDE.md`), with docs updated in the same commit
(root `CLAUDE.md` §7's same-commit rule).

### Slice 1 — `outline:` on a standalone `text` element

Every draw shape a standalone element can take: upright (baked or system
font), `curve: {style: angled}`, `curve: {style: radial}` — all on a
vector font, since `curve:` requires one.

**Files:**
- `schema/wfb-face-1.schema.json` — `$defs/outline` (§2.3); referenced
  from `textElement`.
- `wfb/ir/model.py` — `Outline` dataclass (§2.4); `Text.outline`;
  `Text._own_expressions` grows to include `outline.color`.
- `wfb/ir/builder.py` — `_build_outline(node, key) -> Outline | None`
  (parses both spellings, D7; applies the width default and the >3
  build error, D6; calls `_color_expression`, D8); wired into
  `_build_text`.
- `wfb/layout.py` — `_resolve_text`'s three box branches grow the
  measured `width`/`line_height` by `2 * outline.width` when set (D9,
  §6).
- `wfb/lint.py` — `check_text_outline_interior` (D10, §7); added to
  `SUPPRESSIBLE`.
- `wfb/emit/monkeyc/layout_constants.py` — `OUTLINE_OFFSETS_<W>` arrays,
  deduplicated by width (§8).
- `wfb/emit/monkeyc/shapes.py` — `_emit_text_draw`/
  `_emit_vector_text_draw` grow the stamp loop (§8) ahead of the existing
  interior draw, inside the existing vector-font null guard where one
  already exists.
- `wfb/preview.py` — `_text` wraps `_draw_text`/`_draw_vector_text` in
  the same loop-plus-one shape (§9).
- Tests: a new `tests/test_text_outline.py` (schema/IR/builder: both
  spellings accepted, `width: 4` fails red-then-green citing the cap,
  missing `color:` in object form is a schema error, `outline.color`
  reads a palette/config/data expression exactly like `color:`);
  `tests/test_text_outline_layout.py` (box growth, all three
  `curve_style` branches, off-screen/safe-area still correct against
  the grown box); a golden fixture
  (`tests/fixtures/outline_text/face.yaml`, following `tests/
  test_vector_text_golden.py`'s own precedent) plus
  `tests/test_text_outline_golden.py`; `tests/test_text_outline_
  preview.py` (a rendered PNG shows more lit pixels at the glyph's edge
  than the plain-fill render, and the ring pixel count roughly matches
  research 14 §1's own disc-perimeter counts for a known glyph); a
  `check_text_outline_interior` case in `tests/test_lint.py`, driven red
  (two overlapping elements, no `outline:`, i.e. no finding) then green
  (the same pair, one gains `outline:`, the finding appears) then
  suppressed (`lint: {allow: [text-outline-interior]}` silences it).
- Docs: `docs/guide/text.md` (`outline:` section, the "at a glance"
  table row, the interior-paints-not-reveals guidance from §3, the
  anti-aliasing guidance from §4); `docs/guide/lints.md` (new row,
  eighteen becomes nineteen); `docs/guide/colors.md` (a one-line
  cross-reference, "see `outline:`'s own colour rules"); `docs/lore/
  codegen.md` (the offset-array/loop-vs-unroll precedent, mirroring the
  existing pattern-cost citation); `docs/limitations.md` §2 — add a row:
  "`outline:` on a pattern `shape: text` part | plan 15 §14 slice 2 —
  standalone `text` elements ship in slice 1" (removed again in slice
  2).

### Slice 2 — `outline:` on a pattern `shape: text` part

Every draw shape a part can take, including per-copy rotation
composition (§5's table, last row).

**Files:**
- `schema/wfb-face-1.schema.json` — `outline` added to the `text`-shaped
  branch of `handPart`.
- `wfb/ir/model.py` — `HandPart.outline`;
  `PatternElement._own_expressions` grows to include each part's
  `outline.color` alongside `part.color`/`text_value`.
- `wfb/ir/builder.py` — the `shape: text` branch of `_build_hand_part`
  calls the same `_build_outline` slice 1 added.
- `wfb/layout.py` — `_resolve_hand_part`'s text branch (and `_pattern_
  part_ink`, `docs/lore/codegen.md`'s citation) grow by the part's own
  `outline.width` the same way slice 1 grew a standalone element.
- `wfb/lint.py` — `check_text_outline_interior` needs no code change
  (already generic over `Placed`); remove the slice-1 scope note from
  its docstring once this lands.
- `wfb/emit/monkeyc/layout_constants.py` — the same `OUTLINE_OFFSETS_<W>`
  table, now also consulted for a part's own width (dedup already covers
  it — no new emission path).
- `wfb/emit/monkeyc/rotated.py` — `_emit_pattern_text_draw` grows the
  same stamp loop ahead of its own draw call, nested inside the existing
  per-copy body; the vector-font null guard wraps loop and interior draw
  together, same as slice 1.
- `wfb/preview.py` — `_pattern_text` wraps its own `_draw_text`/
  `_draw_vector_text` call the same way.
- Tests: `tests/test_pattern_text_outline.py` (builder/schema, following
  `tests/test_pattern_text_curve.py`'s own shape); `tests/test_pattern_
  text_outline_codegen.py` + a golden fixture extending slice 1's;
  `tests/test_pattern_text_outline_preview.py` (a radial ring of
  numerals with `outline:` renders a visibly thicker/ringed glyph at
  every copy, not just copy 0 — the "rotation-invariant" claim research
  14 §3.2 measured, proven against this project's own renderer); extend
  the lint test to a pattern case.
- Docs: `docs/guide/patterns.md` ("Text parts" section: `outline:` row,
  the per-copy draw-count multiplier note from §5); `docs/limitations.md`
  §2 — remove slice 1's row.

### Slice 3 — Example and screenshot

**Files:** `examples/features/outline/face.yaml` (§12); `tools/docs-
shots.py` (new `"outline"` entry); `docs/guide/text.md`/`patterns.md`
(embed the screenshot, cross-links); `docs/README.md` (a row if it
indexes example faces the way it indexes guide chapters — check its
current shape before assuming); root `CLAUDE.md` §6 "Shipped" bullet list
(add `outline:`, one line); `docs/lore/roadmap.md` (mark it shipped);
this file — delete it (`docs/CLAUDE.md`'s "built plans are deleted"
rule), after recording the build commit for each slice in the deletion
table other deleted plans already have (`docs/CLAUDE.md`'s own table).

---

## 15. What the user should look at before slice 1 starts

Everything in §13 is the orchestrator's own call under the existing
go-ahead, not a synchronous confirmation — flagging the three most likely
to be worth a second look:

- **D1 (no `background` role)** is the one closest to "changes the
  format's shape" (CLAUDE.md §7's own bar for stopping to ask) — it was
  kept out of scope deliberately, but a future transparency or
  background feature would revisit exactly this ground, so it is worth
  the user confirming "document the pattern" is really preferred over
  "add the role now, while a real motivating use case exists."
- **D2 (default width 2px)** and **D6 (cap at 3px)** are both
  product/taste calls dressed as technical ones — the *evidence* points
  at 2 and 3 respectively, but "what looks right on a wrist" was never
  measured (research 14 says so plainly, §4.2/§8.2 item 2) and only the
  user has seen a real watch.

---

## 16. Amendments found during slice 1 implementation (2026-09-22)

Two places where the plan's own text, taken literally, would not have
produced a correct or even a valid implementation — recorded here per the
orchestrator's brief ("choose the closest faithful alternative, amend the
plan in place with a short note explaining why") rather than silently
diverging from what is written above.

**§2.3's schema `oneOf` is ambiguous as written, and was fixed at
implementation time.** The literal three-branch `oneOf` (`{const: "none"}`,
`colorExpression`, the object form) rejects the value `outline: none`
outright under JSON Schema's own semantics: `colorExpression` is `{type:
string, minLength: 1}`, which the bare string `"none"` also satisfies, so
`"none"` matches *two* of the three `oneOf` branches and `oneOf` requires
exactly one. The schema actually shipped (`schema/wfb-face-1.schema.json`
`$defs/outline`) wraps the colour-expression branch in `allOf: [
colorExpression, {not: {const: "none"}} ]` instead, so a bare `"none"`
matches only the first branch and everything else matches only the second
— verified directly against the real schema with `jsonschema` before and
after (the unpatched draft fails to validate `outline: none` at all; the
shipped one accepts it, and rejects nothing else the plan's own examples
use). No format-level change: the three spellings (`none`, a bare colour,
the object form) behave exactly as §2.1/§2.2 describe; only the schema
*text* needed the fix.

**§6/D9's layout-growth description ("feed `width + 2 * ring_px` into
whichever box function `curve_style` already selects") is under-specified
in a way that would have produced an incorrect, *unsafe* (under-reporting)
box for a non-centred `align:`/`vertical_align:`, and was implemented via
an explicit `pad:` parameter instead of literal value substitution.** The
issue: `_rotated_text_box`/`radial_text_angle_span`/`radial_text_band` (and
the plain-box branch) all compute the box's *placement* (the `align`
shift, or — for radial — the angular start/end) from the same `width`/
`line_height` value that also sets the box's *size*. Substituting a grown
`width + 2*ring_px` into both uses at once does not dilate the box
symmetrically about its own centre (a true Minkowski dilation, and what
D9's own prose claims): for `align: left`, it leaves the box's already-at-
the-anchor left edge exactly where the *unringed* box's left edge was, and
pushes all of the growth onto the right edge — silently under-reporting
the ring's real reach on the aligned side, where an actual stamped ring's
left-shifted copies (offset `(-r, 0)`, drawn with the same left-justify
re-applied at the shifted anchor) genuinely do extend `ring_px` further
left than the anchor. This is not a hypothetical: `tests/
test_text_outline_layout.py::test_upright_box_grows_past_the_align_edge_
too` drives exactly this case red against a literal-substitution
implementation and green against the one shipped. The fix: `rotated_rect_
corners`/`_rotated_text_box`/`radial_text_angle_span`/`radial_text_band`
each grew a new `pad: float = 0.0` parameter (default `0.0`, so every
pre-existing call site is byte-for-byte unaffected) that pads the box's
*half-extent*/*angular reach* by `ring_px` **after** its placement is
computed from the unpadded dimensions — the "Minkowski-dilate the pre-
transform box, *keeping its own centre*, then apply the same transform"
construction D9's prose actually intends, just not the literal value-
substitution its own worked description would produce. `_placed_text_
curve_reach` (the round-screen `safe-area` shape-aware reach function,
which independently re-derives its geometry from `PlacedText`'s stored
fields rather than reading the already-grown `.box`) needed the same
`pad:` threaded through it for the same reason — not mentioned in §6 at
all, found only because `visible_reach`'s own docstring says plainly that
it recomputes rather than trusts `.box`.

---

## 17. Amendments found building the slice 1 fixture (2026-09-22)

Building `tests/fixtures/outline_text/face.yaml` — the golden fixture §14
slice 1 itself calls for — with `text-outline-interior` and `contrast` as
shipped in the same commit (`0cebdf0`) produced 12 `text-outline-interior`
warnings and 9 `contrast` warnings, all false positives on the exact
hollow-text idiom §3 documents as correct, breaking root `CLAUDE.md` §7's
"the build bar is warning-free" rule on the feature's own canonical
example. Both checks are fixed here, not loosened past the point of still
catching a real mistake — every pre-existing red/green pair in
`tests/test_lint.py` for either check still passes unmodified except the
two noted below, and new red/green pairs were added for the cases that
motivated the fix.

**`text-outline-interior` (D10) was a pure box-overlap test with no colour
reasoning at all**, so it fired on *every* outlined element that overlaps
a full-screen background, regardless of whether the interior colour
actually matched that background — including the case it exists to
permit. **Fixed:** a pair is now suppressed only when it can be *proven*
invisible — see `wfb.lint.check_text_outline_interior`'s own (rewritten)
docstring for the exact three-part test (build-time colour equality, a
filled box-covering shape, full box containment) and the worked reasoning
for why a colour match against a *partially* covering earlier element
(research 14's own "crosses a tick ring" example) still does not suppress.
`_same_provable_color`, `_is_solid_backdrop_shape` and `_fully_contains`
are the three new helpers this decomposes into. Two of the slice 1 tests
in `tests/test_lint.py` asserted the old, over-broad behaviour on exactly
the now-safe case (`clock`'s interior and the `check` fixture's
`background` both `palette.bg`) and were rewritten to assert the new,
correct behaviour instead
(`test_outline_interior_matching_a_fully_covering_backdrop_is_silent`,
and `test_outline_interior_can_be_suppressed`'s base case switched to a
genuinely non-matching colour so suppression has something to suppress);
every other slice 1 test for this check already used non-matching
colours and needed no change. New tests cover the partial-coverage case
and a data-conditional colour that can never be proven equal
(`test_outline_interior_matching_colour_but_only_partial_coverage_still_
warns`, `test_outline_interior_data_driven_colour_still_warns`).

**`contrast` (unrelated to any plan 15 decision — it predates this
plan) judged every element, outlined or not, on its own `color:`
against the backdrop**, so an outlined element's *interior* — which the
hollow idiom deliberately sets equal to the backdrop — was judged for
legibility on exactly the colour that carries none: the ring is what
actually reads. **Fixed:** `check_contrast` now special-cases an
`outline:`-bearing element, judging its ring colour instead, against two
independent neighbours (ring-vs-backdrop, ring-vs-interior) rather than
the interior — see that function's own (rewritten) docstring for what a
failure of each one looks like to an author. This was not a plan 15
design gap so much as `contrast` simply predating `outline:` and never
being taught about it; no plan decision (§13) is revised by this, only
the implementation. Three new tests
(`test_outline_interior_matching_the_backdrop_is_not_judged_for_contrast`,
`test_outline_ring_with_poor_contrast_against_the_backdrop_warns`,
`test_outline_ring_with_poor_contrast_against_its_own_interior_warns`)
drive both the silent and both warning paths red-then-green.

**The fixture itself needed one real fix, not a suppression.** Once both
checks above were corrected, one warning remained: `brand`'s (ring-grown)
box genuinely overlapped `clock`'s box on all three targets, and neither
element's interior colour matches the other's — a real, unresolved risk
(if `brand`'s black interior sits on top of part of `clock`'s visible
orange ring, that part of the ring is erased), not a false positive of
either check. Per the orchestrator's brief ("fix the fixture... if some
warning is genuinely correct"), `brand`'s position moved (`dy: -30%r` →
`dy: -55%r`) so the two elements no longer overlap on any of the three
verification targets, rather than adding a `lint: {allow: ...}` to paper
over a genuine geometry problem in the fixture's own layout. `clock`'s
`color:` also changed from `palette.text` to `palette.bg`, matching the
other three elements and actually demonstrating the canonical hollow
idiom §12 calls for (a leftover `palette.text` interior meant `clock` was
never hollow to begin with, despite the fixture's own header comment
describing it as one); the now-unused `palette.text` entry was removed
from the fixture's `palette:` block. `tests/golden/outline_text__*`
were regenerated for the resulting position/colour changes (`BRAND_Y`
and `Palette.TEXT`→`Palette.BG` only — no other generated line changed).
`./.venv/bin/python wfb.py build tests/fixtures/outline_text/face.yaml`
is warning-free after all three fixes.

---

## 18. Amendments found building slice 2 (2026-09-22)

Three places where §14 slice 2's own text, taken literally, would not have
produced a correct or even a compiling implementation, plus one real
`monkeyc` finding neither slice 1 nor the plan's own worked description
anticipated — recorded per the orchestrator's brief rather than silently
diverging from what §14 says.

**§14 slice 2's file list says `outline` is added "to the `text`-shaped
branch of `handPart`" — the actual schema location is `patternPart`, a
separate `$defs` entry.** `handPart` (`schema/wfb-face-1.schema.json`) is
the schema for an actual `hands:` set's parts, which reject `shape: text`
outright (`HAND_PART_REJECTED_SHAPES`, "a bitmap font cannot rotate") — a
hand part can never carry `outline:` at all. The pattern-template
vocabulary that *does* accept `shape: text` is the sibling `patternPart`
def. §14's own text conflates the two because the **code-level** dataclass
both share is named `HandPart` (`wfb/ir/model.py`) and both go through the
same builder method, `Builder._build_hand_part` (parameterised by
`context="hand"`/`"pattern"`) — a real, deliberate sharing at the IR/
builder layer that has no counterpart in the JSON Schema, which keeps two
separate, independently-`additionalProperties:-false` definitions. No
format-level change: `outline:` reaches exactly the same one place (a
pattern's own `shape: text` part) either way; only the plan's own
schema-location description was imprecise. Built: `outline` added to
`patternPart`'s own properties (`schema/wfb-face-1.schema.json`), and
`"outline"` joined the `"text"` row of `PATTERN_PART_GEOMETRY_KEYS`
(`wfb/ir/builder.py`) — the code-level table that *is* named after the
shared `HandPart` type, which is the one place §14's "handPart" language
is actually correct.

**§14 slice 2's file list says `check_text_outline_interior` "needs no
code change (already generic over `Placed`)" — this undersold what a
`PatternElement` actually needed.** The check (as slice 1 shipped it)
reads `getattr(later.element, "outline", None)` and `getattr(later.
element, "color", None)` directly off the element — correct for a `Text`
element, whose `outline`/`color` really do live at that level, but a
`PatternElement` has neither: `outline:` (and its own interior `color:`)
live on each **part** (D10 already says the check stays element-level,
not per-copy, but that is a statement about *copies*, not about where
`outline:` is authored on the element graph). Left as `getattr(...,
"outline", None)` alone, the check would simply never fire for any
pattern, silently — a false "no code change" that would have shipped a
gap rather than a suppressible warning. Built: a new `_outlined_
interiors(element)` helper (`wfb/lint.py`) returns every `(outline,
interior colour)` pair an element draws with — a `Text` element's own
single pair, or, for a `PatternElement`, one pair per outlined part — and
`check_text_outline_interior` iterates that instead of the element's own
two attributes directly. The suppression rule itself needed one further
generalisation, beyond D10's own text: for a pattern with more than one
outlined part, a given earlier element is provably safe only when **every**
outlined part's own interior colour independently matches it (`all(...)`
over `_outlined_interiors`' pairs) — a pattern with two outlined parts in
two different interior colours, only one of which happens to match a
fully-covering backdrop, is not safe, because the other part's own patch
is still unaccounted for. `tests/test_lint.py::test_pattern_outline_
interior_all_outlined_parts_must_match_to_suppress` drives this red
against an "any one match suppresses" implementation and green against the
"all must match" one actually built.

**Real `monkeyc` finding, not anticipated by §8's worked codegen shape:
a pattern's own copy loop already owns the local name `i`, so `_emit_
outline_loop`'s slice-1 hardcoded `var i = 0;`/`var offsets = ...;`
does not compile once nested inside it.** `wfb.emit.monkeyc.rotated.
_emit_pattern` already declares `for (var i = 0; i < element.count; i++)`
as the per-copy loop's own index — the exact same generated method every
part of one pattern shares. Nesting an outlined text part's stamp loop
inside that body with slice 1's own bare `var i = 0;` produced a real,
reproducible `monkeyc` error, `Redefinition of variable 'i'`, the moment
`tests/fixtures/outline_text/face.yaml` gained its first pattern-with-
outline element — Monkey C does not scope a `var` to the block it is
declared in the way this might suggest; a straight-line re-declaration
later in the same method is rejected outright, even nested inside an
unrelated `if`/`while`. Two outlined text parts in the *same* pattern
would collide with each other the same way, for the same reason, once
one bug was fixed superficially (e.g. by simply renaming the loop
variable once, globally). Fixed by giving `_emit_outline_loop`
(`wfb/emit/monkeyc/shapes.py`) two new keyword parameters, `index_var`/
`offsets_var`, defaulting to `"i"`/`"offsets"` — so every slice-1 call
site (one generated method per standalone element, no collision possible)
is byte-for-byte unaffected — with the pattern caller
(`wfb.emit.monkeyc.rotated._emit_pattern_text_draw`) deriving unique
names per part from its own `part_prefix` (`f"outlineI{part_prefix}"`/
`f"outlineOffsets{part_prefix}"`), the same per-part uniqueness every
other generated constant name for that part already relies on. Caught
only by a real `monkeyc` build (`./.venv/bin/python wfb.py build
tests/fixtures/outline_text/face.yaml`), not by any Python-level test —
`tests/test_pattern_text_outline_codegen.py::test_pattern_outline_uses_
unique_variable_names_per_part` and `::test_golden_fixture_pattern_
methods_have_no_redefinition_regressions` now pin the fixed shape so a
future change cannot silently reintroduce a bare `var i =`/`var offsets =`
inside a pattern's own draw method.

**The golden fixture itself.** `tests/fixtures/outline_text/face.yaml`
gained `dial_numbers` (`curve: {style: angled}`) and `dial_ring`
(`curve: {style: radial}`), both small (3-copy, ~12° apart) radial
patterns of outlined `shape: text` parts, chosen deliberately small and
clustered rather than a full 12-copy ring: a full ring's own bounding box
(the union of every copy's ink) inherently spans from edge to edge of the
disc through the centre, which would overlap every other element already
on the fixture (none of them solid backdrop shapes) and warn
`text-outline-interior` for a real, not false-positive, reason — the same
"why full containment, not just a colour match" logic §17 already
documents, just newly visible once a pattern's own (much larger) box
enters the picture. Each part's own `color:` is set directly on the
**part**, not the pattern element's own default: `check_contrast`
(unextended by this plan, and not in §14 slice 2's own file list) reads
only a `PatternElement`'s own top-level `color:` and has no notion of
per-part outline at all, so leaving the element-level default unset is
what keeps that pre-existing, unrelated-to-this-plan gap from firing a
false "contrast ratio 1.0" against the very colour meant to be invisible
against the backdrop — extending `check_contrast` to patterns is a
real, separate gap, not something this plan's own evidence asks to fix.
`./.venv/bin/python wfb.py build tests/fixtures/outline_text/face.yaml`
is warning-free on all three verification targets with both new elements
in place.
