# Plan 07: `align:`/`vertical_align:` as a placement property of every element

- **Date:** 2026-09-15
- **Status:** approved for building, 2026-09-15. The user asked for the
  research, the requirements and a plan, and for the build to go to
  Sonnet subagents, one phase at a time, each integrated and committed.
  §6 lists the choices made without a round-trip, for the user to review
  afterwards (plan 06's precedent). Branch `feat/align-everywhere`, cut from
  `feat/pattern-text-group-align` at `caece04`.
  Delete this file once built (`docs/CLAUDE.md`).
- **Ask (the user's words, condensed):** `align:`/`vertical_align:` landed
  on `group` alone (plan 06 §4). It should have been a basic placement
  property of *every* text, primitive and group. Make it consistent across
  all kinds of object, and refactor the earlier alignment logic where
  needed so there is one model, not several.
- **Builds on:** plan 06 (`git show f5155d7:docs/plans/06-pattern-text-and-group-align.md`),
  ADR 0004 (element model and coordinates).

---

## 1. Research

### 1.1 What exists today

| Where | Keys | Values | Mechanism |
|---|---|---|---|
| `text` element | `align`, `vertical_align` | `left/center/right`, `top/center/baseline` | `Resolver._justify` → `drawText` flags; `_resolve_text` computes the lint box with its own dict literals |
| pattern `shape: text` part | the same two | the same values | `_justify` again; `_pattern_part_ink` repeats the dict literals |
| `group` | the same two | `left/center/right`, `top/center/bottom` | `_group_box`, a third copy of the dict literals |
| every other element | *(unknown key: schema error)* | — | box always centred on `at:` |
| `wfb/preview.py` | — | — | `_blit_bitmap_text` and `_approximate_text` each carry a fourth and fifth copy |

Five hand-written copies of one rule, two spellings of "bottom" (`baseline`
on text, `bottom` on a group), and a schema with three separate inline
enums (`groupElement`, `textElement`, `patternPart`).

### 1.2 A real bug: `vertical_align: baseline` draws as `top`

`Dc.drawText` has **no bottom justification**. The flags are
`TEXT_JUSTIFY_RIGHT` (0), `_CENTER` (1), `_LEFT` (2) and `_VCENTER` (4)
(`$CIQ_SDK/doc/Toybox/Graphics.html`, API 1.0.0). Without `VCENTER`, `y` is
the top of the text: the project already relies on this for `top`.

`Resolver._justify` adds `VCENTER` only for `center`, so `baseline` emits
exactly what `top` emits. `wfb/preview.py` does the same
(`top = ... if vertical_align == "center" else y`, and Pillow anchor `"a"`).
But `Resolver._resolve_text` and `_pattern_part_ink` compute the lint box
for `baseline` as `top = y - line_height`. So **the device and the preview
hang `baseline` text down from the point, while the overlap, safe-area and
clip checks believe it sits above the point.** Found by reading. Phase A
must drive it red before fixing it. No example or test YAML uses
`baseline` (grep: only `tests/test_group_align.py`, which asserts a group
*rejects* it).

### 1.3 What each element's `at:` means

| Kind | `at:` is… | So `align:` is… |
|---|---|---|
| `group` | where its declared `size:` box goes | well-defined |
| `text` | where its line box goes | well-defined (a runtime justify for the width) |
| `shape` rectangle / rounded_rectangle / ellipse | the centre of the `size:` box | well-defined |
| `shape` circle / arc | the centre of the circle | well-defined: the circle's `2·radius` square |
| `shape` polygon | *nothing*: every vertex is its own position | meaningless |
| `shape` line | one end (`to:` is the other) | meaningless |
| `progress` bar / arc | centre of the `size:` box / of the circle | well-defined |
| `icon` | the centre of the glyph box | well-defined (a runtime justify, like text) |
| `graph` | the centre of the `size:` box | well-defined |
| `complication_slot` | the centre of the icon+reading pair | well-defined, but the pair is measured on the device |
| `hands` | **the axis the hands turn about** | meaningless: moving it breaks the rotation |
| `pattern` | **the origin every copy turns about or steps from** | meaningless for the same reason |
| hand/pattern part rectangle | the centre of the `size:` box, in the frame | well-defined, build time |
| hand/pattern part circle | the centre, in the frame | well-defined, build time |
| pattern part text | the anchor, in the frame | already built (plan 06) |
| hand/pattern part polygon, line, pattern part arc | vertices / ends / *no `at:` at all* | meaningless |

Almost everything is already drawn **from build-time constants in the
per-device `Layout` module** (ADR 0004). Moving a box is therefore a
resolver-only change: codegen and the preview both read the resolved
geometry and follow it for free. Only the glyph-drawn kinds (text, icon,
pattern text) and the runtime-measured `complication_slot` need anything
from codegen.

## 2. Requirements

| # | Requirement |
|---|---|
| R1 | **One rule.** `align: left \| center \| right` and `vertical_align: top \| center \| bottom` say which edge (or the centre) of the element's **placement box** sits on the point `at:` resolves to, independently per axis. Both default to `center`. The same keys, values, defaults and meaning apply wherever they are accepted. |
| R2 | **Accepted on:** `group`; `text`; `shape` rectangle, rounded_rectangle, ellipse, circle, arc; `progress` (both styles); `icon`; `graph`; `complication_slot`; hand and pattern parts `rectangle` and `circle`; pattern part `text`. |
| R3 | **Rejected, with the reason, on:** `shape` polygon and line; hand/pattern parts polygon and line; pattern part arc; `type: hands`; `type: pattern`. One error per mistake, not N. The reasons are the §1.3 column: no single point to align on, or `at:` is a pivot. |
| R4 | **The placement box is the declared geometry, never the ink** (the table in §3.1). An outline's pen straddle and an arc's `start_angle`/`sweep` do not move it. Changing `thickness:` or `sweep:` never moves where a shape sits. |
| R5 | **Default output is byte-identical.** With neither key written, every golden file, every example's generated project and every preview PNG is unchanged (`snapshot.sh`, §5). |
| R6 | **`baseline` becomes `bottom`.** `vertical_align: baseline` (text element, pattern text part) is removed with no shim. A friendly error says it was renamed `bottom` and why: it always meant the bottom of the line box, never the typographic baseline. |
| R7 | **Device, preview and lint agree** for every accepted kind and value: the §1.2 bug is fixed, and a test proves each glyph kind's `bottom` puts ink above the point. |
| R8 | **One implementation of the rule**, in each layer (§3.3). No per-kind dict literal of `left/center/right` survives outside the shared helpers. |
| R9 | Warning-free `monkeyc` builds on all three targets for a new `examples/align/face.yaml` that uses every accepted kind with non-default values. |
| R10 | The docs say it once: a "Placement" section in `docs/format.md` owns the rule and the per-kind table; element sections point to it. The schema has one `$defs/align` and one `$defs/verticalAlign`. ADR 0004 is amended. |

## 3. Design

### 3.1 The placement box, per kind

| Kind | Placement box (width × height) |
|---|---|
| `group` | `size:` |
| `text` | widest rendering × line height (as today's lint box) |
| `shape` rectangle, rounded_rectangle, ellipse | `size:` |
| `shape` circle, arc | `2·radius` × `2·radius`, the full circle whatever the sweep |
| `progress` bar | `size:` |
| `progress` arc | `2·radius` × `2·radius` |
| `icon` | the measured glyph box |
| `graph` | `size:` |
| `complication_slot` | the icon+reading pair, from `complication_slot_pair_geometry` (estimated at build time, measured on the device) |
| hand/pattern part rectangle | `size:`, in the part's frame |
| hand/pattern part circle | `2·radius` square, in the part's frame |
| pattern part text | that copy's string width × line height |

### 3.2 Three mechanisms, chosen by how the kind is drawn

**(a) Box-drawn kinds** (group, shape, progress, graph, and the hand/pattern
rectangle and circle parts) resolve alignment **entirely at build time**
by moving the box's centre:

```python
def alignment_shift(width, height, align, vertical_align) -> tuple[float, float]:
    """How far the placement box's centre sits from the at: point."""
    dx = {"left": width / 2, "center": 0.0, "right": -width / 2}[align]
    dy = {"top": height / 2, "center": 0.0, "bottom": -height / 2}[vertical_align]
    return dx, dy
```

Each resolver computes `(x, y)` from `at:` as today, adds the shift, and
then builds its geometry around that centre **with the same expressions as
today**. `center` adds exactly `0.0`, so the default path is byte-identical.
No codegen or runtime-lib change: `Layout` constants and the preview both
read the moved geometry.

A hand/pattern rectangle or circle part does the same in its own frame,
before `_round_away`. For example, `vertical_align: bottom` with
`at: {dy: 0}` puts a hand rectangle's bottom edge on the axis. That saves
writing `dy: -length/2`.

**(b) Glyph-drawn kinds** (text, icon, pattern text part) place the glyphs
**on the device**, because the drawn string or glyph can differ from the
build-time estimate:

- horizontal: the `TEXT_JUSTIFY_LEFT/CENTER/RIGHT` flag at the anchor
  point, as text already does;
- `vertical_align: top`: no `VCENTER`, `y` = the anchor;
- `center`: `VCENTER`;
- `bottom`: no `VCENTER`, `y` = anchor − `dc.getFontHeight(font)`. Garmin has
  no bottom flag. The subtraction uses the font's real height on the device,
  so it is exact even where a system font's scraped `size_px` is not. For
  a radial pattern text part, pass `cy - dc.getFontHeight(font)` as
  `WfbGeom.drawTextRotated`'s `cy`. That shifts the rotated anchor straight
  up in screen space, so no helper signature changes.

`Resolver._justify` stays the one source of the flags, and icons start using
it too. The lint box uses (a)'s shift with the resolved line height. The
preview places ink with the same shared rule.

**(c) `complication_slot`** is ADR 0004's existing runtime exception. Its
pair is measured on the device, so the alignment arithmetic lives there
too:

- horizontal: `startX = CX − {0, total/2, total}`;
- `icon_position: top | bottom`: `startY = CY − {0, total/2, total}`;
- `icon_position: left | right`: the row's `VCENTER` y is
  `CY + {+rowH/2, 0, −rowH/2}`, where `rowH` is the larger of the drawn
  fonts' `getFontHeight`.

The default center/center keeps today's code byte-identical, fast path
included. The layout's estimated box and the preview shift by the same
rule, from `complication_slot_pair_geometry`'s extents.

### 3.3 One implementation per layer (R8)

| Layer | The one place |
|---|---|
| schema | `$defs/align`, `$defs/verticalAlign`; every accepting definition `$ref`s them |
| IR | `Element.align`/`Element.vertical_align` on the **base class** (moved off `Group`/`Text`); `HandPart` keeps its own two fields, with the same names. One `Builder` helper reads both keys for every accepting kind and for `_build_hand_part`. `SHAPE_GEOMETRY_KEYS`, `HAND_PART_GEOMETRY_KEYS` and `PATTERN_PART_GEOMETRY_KEYS` gain `align`/`vertical_align` in the accepting rows, so R3's shape and part rejections come from the existing "key not used by this shape" sweep, with one extra note giving the §1.3 reason. |
| pre-schema | `wfb/validate.py`: the friendly `baseline` rename error (R6), and a friendly refusal on `type: hands`/`type: pattern` (R3), following `_check_hands_seconds_always`'s precedent, so the schema stays closed |
| layout | the module-level `alignment_shift` (above), used by `_group_box`, `_resolve_text`, `_pattern_part_ink` and every new kind; `Resolver._justify` for flags |
| codegen | one helper that emits a glyph draw's `y` (`Layout.…_Y` or `Layout.…_Y - dc.getFontHeight(font)`), shared by text, icon and pattern text |
| preview | `_blit_bitmap_text`/`_approximate_text` place ink through `alignment_shift` (or a thin wrapper), never their own dicts |

## 4. Phases

Each phase goes to one Sonnet subagent, runs **sequentially**, and ends in
one commit that I review and integrate before the next phase starts. Each
phase updates the schema, `docs/format.md` and any doc it makes stale **in
its own commit** (root `CLAUDE.md` §7).

| Phase | Scope | Mechanism |
|---|---|---|
| **A: foundation** | shared helpers in every layer (§3.3); the base-class fields; `baseline`→`bottom` with the friendly error; fix §1.2 for the text element and the pattern text part (device + preview); `group`/`text`/pattern text refactored onto the helpers; the format.md "Placement" section; ADR 0004 amendment | (a), (b) |
| **B: box kinds** | `shape` (rectangle, rounded_rectangle, ellipse, circle, arc; reject polygon/line), `progress` (bar, arc), `graph` | (a) |
| **C: glyph and runtime kinds** | `icon` (static and `icon_for:`), `complication_slot` (every `icon_position:`) | (b), (c) |
| **D: frames** | hand and pattern parts `rectangle`/`circle`; reject polygon/line/arc parts; friendly refusal on `type: hands`/`type: pattern` | (a) |
| **E: example and wrap-up** | `examples/align/face.yaml` (R9) plus a preview check; `docs/limitations.md`; root `CLAUDE.md` §6 "Recently built"; `examples/CLAUDE.md`; `docs/history.md`; delete this plan | — |

## 5. Verification (every phase)

1. `./.venv/bin/python -m pytest -m "not slow"`: the only failures are the
   8 known ones in `tests/CLAUDE.md` (the analog/hands ones, big-clock-3,
   dashboard, enduro).
2. **Byte-identity (R5):** `snapshot.sh` (the orchestrator's scratchpad)
   regenerates every example and the slice fixture with `--no-compile`,
   plus every preview PNG. It must diff clean against the pre-plan snapshot
   taken at `caece04`. The only exception is a phase's own deliberate
   `baseline`-related change, which no example uses.
3. **Drive red:** every new diagnostic and every geometry test is shown
   failing against the old code, or a knowingly broken helper, before it is
   trusted (`tests/CLAUDE.md`).
4. A phase that changes codegen builds one affected face with real
   `monkeyc` on all three targets, warning-free (`-m slow` or `wfb build`).

## 6. Choices made without a round-trip (for review)

1. **`baseline` is renamed `bottom`, with no shim**, only a friendly error.
   This follows the project's removal precedent (`on_tap:`, `scale:`). The
   old spelling never meant a typographic baseline, and on the device it
   drew as `top` (§1.2). A true typographic baseline, from font ascent,
   could be added later as its own value.
2. **`hands` and `pattern` reject element-level alignment.** Their `at:` is
   a pivot, and aligning a pivot has no meaning. Their *parts* align
   instead. An alternative, left unbuilt: align a *linear* pattern's
   drawn-ink box. It is useful for a row, but it would make `at:` mean two
   things on one element kind.
3. **Circle and arc align by the full circle (`2·radius`)**, not the swept
   span's box, so changing `sweep:` never moves the centre.
4. **The placement box is the declared geometry, not the ink** (R4). This
   matches how an outlined rectangle already reports its geometry.
5. **A glyph's `bottom` subtracts `dc.getFontHeight` on the device**, one
   subtraction a frame, rather than baking a build-time line height. Only
   the device's own height is guaranteed right for a system font. ADR 0004
   is amended to record it.
6. **Builders are Sonnet, not Haiku.** The IR, layout and codegen modules
   are thousands of lines each, with strict same-commit doc rules. Haiku
   was judged too likely to miss a layer.
