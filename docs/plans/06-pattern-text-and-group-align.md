# Plan 06: Text parts in a pattern, and `align:` on a group

- **Date:** 2026-09-15
- **Status:** approved for building, 2026-09-15. The user asked for the
  research, a plan, a task split, and for the build to go to subagents one
  by one, each integrated and committed. §6 lists the choices made without
  a round-trip, for the user to review afterwards. Branch
  `feat/pattern-text-group-align`. Delete this file once built
  (`docs/CLAUDE.md`).
- **Ask (the user's words, condensed):**
  1. Place text with a pattern, using `copy` in `value:` or `text:` ("take
     the best approach or create another key") — twelve hour numerals as
     one radial pattern instead of twelve polar `text` elements.
  2. `align:` on a `group` is rejected, yet a group is a rectangle, so
     aligning it is well-defined. Research it and implement it.
- A third ask, "a `%`/`%r` size or thickness that resolves below 1px
  becomes 1px", is built on its own branch (`feat/min-1px-relative-lengths`)
  and is not part of this plan.
- **Builds on:** plan 05 (patterns, `git show f9115ca:docs/plans/05-patterns.md`),
  in particular §9 D5, which deferred "text/numeral parts
  (index-dependent text)", and the 2026-09-15 `copy` amendments to
  ADR 0005.

---

## 1. Research

| Question | Answer | Evidence |
|---|---|---|
| Can a bitmap font rotate? | **No.** `Dc.drawText(x, y, font, text, justification)` draws upright text only. | `$CIQ_SDK/doc/Toybox/Graphics/Dc.html`; plan 05 §5.2 |
| Does upright text suit numerals? | **Yes.** A dial's numerals stay upright. Only the anchor point has to turn with the copy, and that is plain vertex arithmetic, the `WfbGeom` formula. | `runtime-lib/WfbGeom.mc` |
| Does `drawText` take a Float position? | Yes: `x as Lang.Numeric, y as Lang.Numeric`. We still round explicitly (§3.4), so the preview and the device agree on the pixel. | `Dc.html` |
| Is `copy` already an expression binding? | Yes. It is `expr.COPY`, bound to the loop index `i` while a pattern's colours and part `visible:` compile (`Builder._build_pattern_element`). | `wfb/expr.py`, `wfb/ir.py` |
| Can the host evaluate a `copy` expression? | Yes. `expr.evaluate(ast, {"copy": i})` plus `formatting.render(spec, value, type)` is exactly how the preview draws a `text` value today. | `wfb/preview.py::_text_value` |
| Why the host has to know every string | A custom font is **subsetted** to the glyphs the design can draw (`wfb/emit/resources.py::glyph_set`), and a pattern's `box` is its measured ink (plan 05 §5.5). Both need every copy's actual string at build time. | same |
| Why does `align:` fail on a group? | The schema's `groupElement` is `additionalProperties: false` and has no `align` key, so the error is "unknown key". `Resolver._group_box` always centres the box on `at:`. Nothing in the platform is involved: a group is resolved entirely at build time and never reaches the device as an object. | `schema/wfb-face-1.schema.json`, `wfb/layout.py::_group_box` |

**Open question, UNVERIFIED:** Monkey C's `%` on a negative dividend.
Python's `-1 % 12` is `11`, and Java-style truncation would give `-1`.
The SDK's `Basic_Syntax.html` does not say which Monkey C does. This
matters only to an expression whose `%` sees a negative operand (for
example `(copy - 1) % 12`). It is **pre-existing** and already affects
`copy` colours and `visible:`. Recorded here, not fixed. `(copy + 11) % 12 + 1`
is the safe spelling, and it is the one used in the docs and the example.

## 2. Requirements

| # | Requirement |
|---|---|
| T1 | A pattern part may be `shape: text`: upright glyphs at an anchor point that **turns (radial) or steps (linear) with the copy**. |
| T2 | `value:` is an expression that may read `copy`, and nothing else but literals. `text:` is a fixed string. Exactly one of the two is given, the same pair a `text` element has. |
| T3 | `format:`, `font:`, `align:`, `vertical_align:`, `color:`, `visible:` and `at:` behave as they do on a `text` element or another pattern part. |
| T4 | Every drawn copy's string is known at build time, so the font's glyph subset, the pattern's `box`/`reach`, the glyph lint and the preview are all exact. |
| T5 | Warning-free builds on all three targets. A preview drawn from the same resolved geometry. One error, not N, per mistake. |
| G1 | `align: left \| center \| right` on a `group` says which edge (or the centre) of the group's box sits at `at:` horizontally. `vertical_align: top \| center \| bottom` does the same vertically. The default is `center`/`center`, which is today's behaviour, byte-identical. |

## 3. Pattern text parts

### 3.1 The YAML

```yaml
hours:
  type: pattern
  pattern: radial
  count: 12                      # step defaults to 30deg
  at: { anchor: center }
  color: config.colors.fg
  parts:
    - shape: text                # a part's kind is `shape:`, as on every part
      value: "(copy + 11) % 12 + 1"   # copy 0 -> 12, copy 1 -> 1, ... copy 11 -> 11
      font: font.hourfont
      at: { dy: -80%r }          # copy 0's anchor: 80%r above the centre (+y is down)
      align: center              # default center
      vertical_align: center     # default center
```

### 3.2 Semantics

- **Keys on a `shape: text` part:** `at` (a hand-frame position, default
  the origin), `value` **xor** `text`, `format`, `font` (default
  `FONT_MEDIUM`, as on `text`), `align`, `vertical_align` (the same enums
  and defaults as `text`), `color`, `visible`. Any geometry key of another
  shape (`points`, `size`, `to`, `radius`, `thickness`, `filled`,
  `start_angle`, `sweep`) is an error, through the existing
  `_check_hand_part_keys` sweep. The text keys on a non-text part are an
  error through the same sweep.
- **`value:`** compiles in the pattern's `copy`-bound scope. Every `Ref`
  in it must be `copy`. A data source, `palette.*` or `config.*` is a
  build error that names the offending reference: "a pattern text part's
  value may read only 'copy'". Its type must be `number`, `float` or
  `string`. `format:` is the numeric format of the `text` element.
- **Per-copy strings:** for each copy index `0..count-1`, `texts[i] =
  formatting.render(format or "{}", expr.evaluate(ast, {"copy": i}), type)`.
  They are computed once in the IR, device-independently, and stored on
  the part. `text:` gives the same string for every copy.
- **Transform:** the anchor `(x, y)` in the template frame goes through
  the copy's `PlacedPattern.transform(i)`, the same formula every other
  part uses, and is then **rounded half up** (`floor(v + 0.5)`) to whole
  pixels. The glyphs are placed upright at that point with `align` and
  `vertical_align`, exactly as a `text` element places them on its `at:`.
- **Draw order:** unchanged. Copy by copy, and within a copy parts in list
  order.
- **Anti-aliasing:** a glyph's softness comes from its font
  (`fonts: <name>: antialias:`). The pattern's `antialias:` still brackets
  the pattern's primitives. A text part is neither affected by it nor
  rejected for it.
- **`static:`** is fine, since a copy-only value is fixed per copy.

### 3.3 Build-time checks (all errors, each driven red by a test)

1. `value:` and `text:` both given, or neither.
2. `value:` reads anything but `copy` (data, palette, config). One error
   per part, naming the references.
3. `value:` typed boolean/colour/time/date.
4. The existing part rules: an unknown shape key, `thickness`/`filled` on
   a text part, no colour.
5. `font:` naming an undeclared font gets the same diagnostic a `text`
   element gets. Reuse `_resolve_font` and do not write a second copy.
6. The glyph lint (`check_glyphs`): a font with an explicit `glyphs:` that
   lacks a character some drawn copy renders.

### 3.4 Interfaces

**IR (`wfb/ir.py`).** `HandPart` gains text fields, which stay `None` or
defaults on every other part:

```python
text_value: Expression | None = None    # `value:` (copy-bound)
text_literal: str | None = None         # `text:`
format: str | None = None
font: str = "FONT_MEDIUM"
font_is_custom: bool = False
align: str = "center"
vertical_align: str = "center"
texts: tuple[str, ...] = ()             # host-rendered string per copy index, len == count
```

`PATTERN_PART_GEOMETRY_KEYS["text"] = {"at", "value", "text", "format",
"font", "align", "vertical_align"}`, and `"text"` leaves
`PATTERN_PART_REJECTED_SHAPES` (it stays in `HAND_PART_REJECTED_SHAPES`).
`PatternElement._own_expressions` includes each `text_value`, so
permissions, the barrel and the read plan see it. It can read only
`copy`, so nothing new reaches them.

**Layout (`wfb/layout.py`).** `ResolvedHandPart` for `shape == "text"`
carries `x`, `y` (the rounded anchor in the template frame, via
`_round_away`, as a circle's centre is), `font_reference`,
`font_is_custom`, `font_px`, `justify` (reuse `Resolver._justify`'s flags),
`align`, `vertical_align`, `line_height`, `texts`, and `widths` (per copy
index, measured with the baked font, or `fonts.fallback.measure` for a
system font, as `_resolve_text` does). `_pattern_part_ink` gains an
`index` argument and a text branch: anchor = the rounded-half-up
transformed `(x, y)`, then the box that `_resolve_text` computes for that
anchor, width and line height. Radial `reach` for a text part is the
farthest corner of any drawn copy's text box from the centre, because
upright text is *not* rotation-invariant. `box` stays the union over the
drawn copies.

**Resources (`wfb/emit/resources.py::glyph_set`).** The characters of
`texts[i]` for every *drawn* copy of a text part with a custom font go
into that font's bucket.

**Barrel (`runtime-lib/WfbGeom.mc`).**
`drawTextRotated(dc, x as Number, y as Number, cx as Number, cy as Number,
sin as Decimal, cos as Decimal, font as Graphics.FontType, text as String,
justify as Number) as Void` rotates the anchor, rounds half up with
`(v + 0.5).toNumber()` (the same rule the host uses), and calls
`dc.drawText`. Check `Graphics.FontType` and the justification parameter
type against `bin/api.debug.xml`.

**Codegen (`wfb/emit/monkeyc.py`).** Layout constants `P_<j>_X`/`P_<j>_Y`
for a text part. In the loop the value is either the literal or
`formatting.emit(format or "{}", value.code, type)`, where `value.code`
already reads `i`. Radial parts call `WfbGeom.drawTextRotated(...)`.
Linear parts call `dc.drawText(ox + Layout.P_j_X, oy + Layout.P_j_Y, ...)`.
A custom font is loaded into a local **before** the loop, with the
existing `if (font == null) { return; }` guard. Every custom font a
pattern text part uses joins `_loaded_fonts`. `_pattern_needs_math`
treats a text part like a filled circle's centre. The per-part
`visible:` gate and the colour rules are unchanged, and a text part uses
no pen.

**Preview (`wfb/preview.py::_pattern`).** Per drawn copy, draw
`texts[i]` at the same rounded anchor with the same justification, through
the existing bitmap-text blit (or the approximate path for a system
font). Refactor `_blit_bitmap_text`/`_approximate_text` to take an anchor
and flags instead of a `PlacedText`, if that is the cleanest route.

### 3.5 Sites to check

Run `grep -n "font_is_custom\|PlacedText\|isinstance(.*Text)" wfb/` and
check every hit: font loading, unused-font or font-usage checks, glyph
lints, and text-fit lints. A font used *only* by a pattern text part must
still be baked, loaded and considered used.

## 4. `align:` on a group

- **Schema:** `groupElement` gains `align` (`left`/`center`/`right`,
  default `center`) and `vertical_align` (`top`/`center`/`bottom`,
  default `center`). A group has no baseline, so the vertical enum is
  `bottom`, not `text`'s `baseline`.
- **IR:** `Group.align`, `Group.vertical_align`.
- **Layout:** `_group_box` computes `left = x - {left: 0, center: w/2,
  right: w}[align]` and `top = y - {top: 0, center: h/2, bottom: h}`.
  Every child resolves against that box. `on_hold:`, clips and lints
  already read the group's `box`.
- **Tests:** `align: right` puts the box's right edge at `at:`.
  `vertical_align: bottom` puts its bottom edge there. A child anchored
  `center` moves with the box. The default output is byte-identical
  (goldens unchanged).
- **Docs:** `docs/format.md` "`group`", with the user's data-window case as
  the example.

## 5. Build phases

| phase | who | scope | commit |
|---|---|---|---|
| A | subagent | §4 in full: schema, IR, layout, tests, `docs/format.md` | after review |
| B1 | subagent | §3: schema (`patternPart`), IR, layout, `glyph_set`, glyph lint, tests of every §3.3 check, driven red | after review |
| B2 | subagent | §3.4 barrel and codegen, codegen tests, a `shape: text` part in `examples/patterns/face.yaml`, warning-free `monkeyc` on all 3 targets | after review |
| B3 | subagent | §3.4 preview and preview tests | after review |
| C | orchestrator | docs (`format.md`, `limitations.md` §2 row, ADR 0005/0004 amendment note, `lore/roadmap.md`, root `CLAUDE.md` §6, `examples/CLAUDE.md`, `history.md`); this plan deleted | final |

**Acceptance:** `pytest -m "not slow"` shows only the baseline failures:
the 3 in `tests/CLAUDE.md`, plus 5 that were already red at this branch
point, all from `examples/analog/face.yaml` edits in `45db779`/`6fab053`
(the `analog` template-clean test, two `test_hands_codegen`, and two
`test_hands_preview`). `examples/patterns/` builds warning-free on
`fenix8solar47mm`, `fenix8solar51mm` and `fr955`.

## 6. Decisions made without a round-trip (for the user to review)

- **D1: `shape: text`, not `type: text`.** Every template part names its
  kind with `shape:`. The user's sketch wrote `type: text`, and that
  spelling would be the only part keyed differently.
- **D2: `value:` (expression) xor `text:` (literal)**, the pair a `text`
  element already has, rather than a new key. `copy` is simply in scope
  in `value:`.
- **D3: a text value may read only `copy`.** Data would make the strings,
  and so the glyph subset and the extent, unknowable at build time, and
  it would need `when_absent:`. It is deferred and listed in
  `docs/limitations.md` §2.
- **D4: the strings are compiled, not baked.** The device evaluates the
  compiled `value:` per copy, as it already does a `copy` colour
  (ADR 0005). The host evaluates the same tree only for glyphs, extents,
  lints and the preview.
- **D5: a text part's anchor is rounded half up** on both host and device,
  so the preview pixel is the device pixel.
- **D6: `vertical_align:` on a group** is added next to the requested
  `align:`. Nobody asked for it, but it is symmetric and costs nothing.
  Its bottom value is `bottom`, not `baseline`.
- **D7: only `group` gains `align:`.** A `shape`, `progress` or `graph` box
  stays centred on `at:`. Wrapping it in an aligned group gives the same
  effect.
