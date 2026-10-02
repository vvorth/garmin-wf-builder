# 26 — The single draw program

**Status: accepted (2026-10-01); slices 0–7 done, 8–10 to go. Building it was decided by
the user on 2026-10-01 (research 27 §8, E1–E4), and P1–P4 (§1) were
accepted as recommended the same day. Q1 (§7) waits on a simulator capture,
needed only partway through slice 1.** Delete this file once every slice has
shipped (`docs/CLAUDE.md`).

Research:
- `docs/research/27-draw-program.md`: the case, the three backends, layers
  and sequencing;
- `docs/research/28-editor-open-questions.md`: the `text` spike, and what
  was closed.

In short:

* Every element kind draws twice today: `emit_draw` writes Monkey C,
  `draw_preview` paints Pillow. The two are kept in step by hand. Two
  disagreements are measured (research 27 §2.5):
  - a filled circle's or rectangle's grown `outline:` ring, which the
    preview stamps;
  - every half-degree arc start, which the preview rounds 1° off
    `WfbArc.drawSpan`.
* A kind will instead **lower** each placed element, once, into a small
  program of drawing steps over `Layout` constants, readings and palette
  references. Three backends consume it:
  1. a **printer** that writes the `draw<Id>` body;
  2. an **evaluator** that paints it in Pillow (the preview, the
     burn-in lint, per-element layers);
  3. a **partial evaluator** that folds readings to their sample values
     and leaves `Layout` constants symbolic, producing a JSON op list per
     layer for the editor's browser canvas.
* Spikes did this for `shape` and `text`, the two kinds that cover 266 of
  the 395 example elements. The printer was byte-identical to today's
  `emit_draw` on 163/163 and 102/102 elements. The evaluator matched
  today's preview on every element except the grown rings.
* **The oracle is `tools/snapshot.py`.** Each port is proven by it:
  - generated code byte-identical;
  - preview pixels identical, except where a slice names the preview fix
    it makes.

  Nothing is reverted first (research 27 E1).

What this plan does **not** do: the editor itself (its own plan, which
starts after slice 3, research 27 E4); any format change; any change to
what the watch draws, except possibly Q1's ring.

## 1. Decisions

### Decided

- **E1–E4 (research 27 §8, 2026-10-01):**
  - revert no feature;
  - a geometry-only first GUI;
  - A7 with three backends;
  - order S3: core, `shape` and `text`, then the GUI viewer, then the
    remaining kinds while the GUI grows.
- **D1–D3 (ADR 0002 amendment, 2026-10-01):** a local web app on
  Starlette and uvicorn, with no front-end build step. They bind this plan
  only through the JSON form in slice 3.

- **P1–P4 accepted as recommended (2026-10-01).**
  - P1: a `wfb/draw/` package; each kind gains `lower()`.
  - P2: printed code is byte-identical while a kind is being ported;
    deliberate changes come afterwards.
  - P3: frame membership and the per-element wrapper's guards are in the
    program, and `view.py`'s frame skeleton stays hand-written.
  - P4: this plan specifies and tests the JSON form.

  The options as they were weighed:

- **P1: where the program lives.**
  - **A (recommended):** a new package `wfb/draw/` holds the op and value
    types, the printer, the evaluator, the partial evaluator and the
    primitive twins. A kind's module gains one hook, `lower()`, and loses
    `emit_draw`/`draw_preview` when it is ported.
  - **B:** ops live in `wfb/emit/`, the evaluator in `wfb/preview.py`.

  A keeps "what a kind draws" in one place and the backends free of kind
  knowledge. That is the point of the plan.
- **P2: byte-identical forever, or only while porting?**
  - **A (recommended):** while a kind is being ported, its printed code
    must equal today's byte for byte; the snapshot is the proof. Once the
    port is done, the generated code may change deliberately, in its own
    commit with its own `--build-stats` figure, like any other emitter
    change.
  - **B:** the program must always reproduce the pre-port emitter.

  B freezes the hand-tuned emitter forever for no benefit once the old
  code is gone.
- **P3: the frame, too, or only element bodies?** The preview duplicates
  frame-level rules as well as element bodies:
  - which elements draw in the awake, sleep and AOD frames;
  - the layout switch;
  - the awake-only second hand;
  - the `visible:` and absent guards in each `draw<Id>`'s wrapper
    (`view._emit_element_method`).

  The options:
  - **A (recommended):** single-source frame membership as one shared
    function, and move the per-element wrapper's guards into the
    program. The view's frame skeleton stays hand-written in `view.py`:
    `onUpdate`, the static buffer, `onPartialUpdate`, the sleep hooks.
    Those are app structure, not drawing, and the preview has no twin of
    them.
  - **B:** program the whole frame skeleton too. That is a large rewrite
    of `view.py` for code with no second implementation.
- **P4: where the browser's JSON form is specified.**
  - **A (recommended):** this plan builds and tests the partial evaluator
    and its JSON form, with a Python reference rasteriser of the JSON that
    must equal the evaluator's layer pixel for pixel. The GUI plan builds
    the JavaScript rasteriser against that contract.
  - **B:** both go in the GUI plan.

  A puts the contract next to the code that defines it.

## 2. The program

The spikes fix its shape. Each part is named here so slices can refer to
it.

**Values.** A value is one of:
- a `Layout` constant, as a name plus this device's value;
- a literal;
- either of those shifted by a build-time integer (a stamp offset), or
  grown (`plus`);
- a colour `Expression`;
- a string value:
  - a literal;
  - a formatted reading (`formatting.emit` / `formatting.render`, already
    one source);
  - a concatenation;
  - a local;
- a reading local, i.e. an `Expression` already compiled and evaluated
  from one AST by `wfb/expr.py`.

**Ops.** The ops are:
- `SetColor`, `SetPen`;
- the `Dc` primitives in use: 24 distinct across the examples (research
  27 §2.3);
- the barrel's drawing calls (`WfbArc.drawSpan`, `WfbGeom.fillRotated`,
  …), one op each;
- `LoadFont`, with its null behaviour;
- `drawText`, `drawAngledText`, `drawRadialText`;
- `Let` (a local);
- `If` on a value (null guards, `_aod`), with `else`;
- `For` over a range (segments, ticks);
- `Comment` and `Blank`, which only the printer sees.

**Annotations.** Each element's program carries:
- its id, and so its author `span` (research 28 §1);
- whether it is a ring pass (`RingPass`).

A group ring is its own program, addressed by the group's id.

**Printer.** It writes through the emitter's own `Writer` (`call`,
`block`, `blank`), so wrapping and spacing come out the same by
construction.

**Evaluator.** It emulates `Dc` on today's `Renderer` machinery:
- glyph sources;
- `draw_text`, `draw_vector_text`;
- the `ImageDraw` primitives.

The barrel's arithmetic is transcribed from `runtime-lib/*.mc` (the
pattern `tests/test_arc_barrel.py` already uses). The evaluator draws
either onto the frame or onto a transparent layer.

**Partial evaluator.** It folds every reading, colour and string to its
sample value and keeps `Layout` constants symbolic, with their values. The
result is a JSON op list per layer: plain numbers, RGB colours, glyph runs
by sheet and glyph id, and `Layout` names where the editor may change
them.

## 3. Slices

Each slice ships with:
- the fast suite green;
- a real build warning-free on the three verification devices;
- `tools/snapshot.py compare` against a baseline saved at the slice's
  start, showing **no output change** except the diffs the slice lists by
  name.

Every new diagnostic or guard is driven red.

### Slice 0 — the core, and primitive twins with property tests: done

Built as below:
- **`wfb/draw/`:**
  - `program` (values, ops, `DrawContext`);
  - `printer`;
  - `evaluator`;
  - `barrel`, the transcriptions;
  - `emit_body` and `paint`, which route each element to its program
    or its kind's old methods.
- `ElementKind.lower()` defaults to `None`. `view._emit_element_method`
  and `Renderer.render_element` go through the router.
  `ElementKind.lowers` (true only when `lower` is overridden) lets the
  router skip building a `DrawContext`, and the preview its `ReadPlan`,
  for an unported kind. Today's renders therefore cost what they did.
- **The preview lowers with always-on code present** and takes the branch
  of the frame it paints, which is the pixel result of any build's
  choice. `Renderer.value_guards` gives a program's `LetText` the same
  locals the view does.
- **`tests/test_draw_barrel.py`:** the `WfbArc`/`WfbGeom` statements
  looked up in the source, and the evaluator's arc swept over every
  half-degree start against a model of `drawArc`'s cells.
- **`tests/test_draw_program.py`:** the printer for every op, the
  evaluator against today's preview for every plain primitive and literal
  text, and the router in both stages.
- Each guard was seen to fail against a broken twin. The old
  `preview.arc_span` fails the sweep at exactly the half-degree starts.

Found while building it: `docs/lore/codegen.md` says the preview's
stamped ring "paints the same pixels" a grown copy does. Research 27 §2.5
measured that it does not. Slice 1 corrects that line along with the
preview.


- `wfb/draw/` (P1): the value and op types, the printer, the evaluator and
  `lower()` on `ElementKind`. A kind without `lower()` keeps
  `emit_draw`/`draw_preview`, so the two coexist per kind.
- **The primitive twins, each with a sweep test against its barrel
  function's own arithmetic.** These are transcribed from the `.mc` source
  and fed *the argument the watch is given* (the Garmin start angle, not
  the author's). That is exactly what `tests/test_arc_barrel.py` did not
  do, and why it missed the half-degree start. Slice 0 adds `drawSpan`,
  `drawProgress`, `roundAway` and the rotation helpers
  (`WfbGeom.rotatedX`/`Y`). Each later slice adds the barrel functions its
  kind calls.
- Nothing is ported. Snapshot: no change.

### Slice 1 — `shape`, with AOD and group ring passes: done

Built as below. `ShapeKind.lower` replaces `emit_draw`, `draw_preview` and
their private helpers. The program gained four things for it:
- `AodPick`: a length's `aod:` override, `(_aod ? a : b)`;
- three paints: `AodRestyled` (`AodStyle.color` / `Renderer.aod_color`),
  `AodDimmed` (`.dimmed` / `.aod_dimmed`) and `RingColor` (a group's
  `ringColor`);
- `Disagreement`, which prints one side and paints the other.

The printer takes the build's `AodStyle`; the preview lowers with
`on=True` and picks by frame.

`tools/snapshot.py`: 537 unchanged, the 2 `wfb doctor` path lines as
before. That is every generated file and every preview variant (awake,
asleep, all styles, AOD, the masked minutes, the heat map). Real builds of
`features/shapes` and `features/profile` are warning-free on all three
targets.

How the two expected diffs actually landed:
1. **The half-degree arc start** is fixed by the port itself. A shape's arc
   is now painted from `WfbArc.drawSpan`'s transcription fed the Garmin
   start, so no shim kept the old rounding. No example or fixture has a
   half-degree start, which is why the snapshot is unchanged. The
   follow-up commit adds the test that shows it. A gauge's arc keeps
   `preview.arc_span` until slice 5.
2. **The grown ring** is a `Disagreement` op until Q1: the watch is sent
   the grown copy, as before, and the preview paints the stamp, as before.
   Resolving Q1 removes the op, one way or the other.


- `ShapeKind.lower()` covers:
  - every primitive;
  - filled and stroked;
  - its own ring, grown or stamped, and polygon ring copies;
  - `aod:` overrides (the `_aod ? … : …` ternaries and the
    `if (_aod) … else` filled toggle);
  - the `RingPass` mode for an outlined group.

  `emit_draw`/`draw_preview` for `shape` are deleted.
- The preview is now the evaluator for shapes. **Expected diffs, each its
  own commit after the identical port:**
  1. the half-degree arc start (preview pixels only; no example face has
     one, so a new test fixture shows it);
  2. the grown ring (preview pixels of `features/profile`'s ringed
     circles, rectangles and rounded rectangles). This follows Q1. If the
     watch stamps, the emitter changes instead, and this becomes a code
     diff with its `--build-stats` figure.
- Tests: the spike's two comparisons become regression tests over every
  shape element in `examples/` and the AOD and outline fixtures.

### Slice 2 — `text`: done

Built as below. `TextKind.lower` replaces `emit_draw`, `draw_preview` and
eight private helpers. The program gained:
- `AodStr` (an `aod: {format: ...}` string);
- `Font.asleep` (an `aod: {font: ...}` face);
- `AodPaint` (an `aod: {outline: ...}` colour);
- `IfAwake` (`if (!_aod)`);
- `Text.align`;
- a `LoadFont` that takes any source and null note (`fontFinal`).

`wfb.draw.drawn_text` returns the string a lowered element draws, for the
two tests that used to import the preview's private `_text_value`.

The fixture `tests/fixtures/text_fallback/` (`absent: {value: 0}` on
`"{heart_rate.current} bpm"`, plain and ringed with an `aod:` restyle, on
an AMOLED and a MIP target) was run through the code before this slice in
a scratch worktree. Its generated project and its awake and AOD previews
were identical to the port's. A test checks the substitute goes through
the format (`0 bpm`).


- `TextKind.lower()` covers every font route (baked, system, vector,
  upright, `angled`, `radial`), every value route (literal, formatted,
  several placeholders, `placeholder`, `fallback`), ring fonts and stamps,
  `aod:` overrides of `format`, `font` and `outline`, and the ring pass.
- A `fallback:` fixture is added, since no example has one (research 28
  §6).
- Expected diffs: none (research 28 §6: 102/102 both ways).

### Slice 3 — layers, and the editor's JSON form: done

Built as below:
- `wfb/draw/frames.py` (`frame_members`, `in_layout`). `view._drawn_in`,
  `ReadPlan`'s always-on ids and `preview.render` read it.
- `preview.render` now composes `sample_values`, `new_renderer`,
  `frame_items` and `finish_frame`, which the layer stack reuses.
- `wfb/draw/layers.py`: `Layer`, `layers`, `compose`, and the matte from
  a black and a white render.
- `wfb/draw/jsonform.py`: `to_json`, with arcs as the `drawArc` call and
  fonts by id, and the reference `rasterise`.

Tests:
- Stacking is within one level of `render` for all 29 example faces,
  awake and, where a face has one, always-on. It is exact on every face
  without anti-aliased text, and `analog-custom` rounds exactly as research
  27 §5.4 measured: 2 938 px at one level, 24 after the palette snap.
- The JSON contract holds for every lowered element of every example in
  both frames.
- The JSON names a rectangle's four `Layout` constants and a stamp's
  offsets.
- Group rings sit right before their first member (`features/rings`, and
  `features/profile` under its `ring1` style).
- Each guard was seen red: a matte without un-premultiplying, and a
  reference circle one pixel short.


- `wfb.draw.layers(resolved, options)` returns each drawn element's
  layer, in draw order, plus one per outlined group's ring. Each layer
  has:
  - an id, the author span and a kind;
  - an RGBA image;
  - for ported kinds, the partly evaluated JSON op list.

  An unported kind's layer image comes from today's `render_element` on a
  transparent ground. It has no op list yet, so the editor shifts its
  image instead.
- The whole-frame steps run once on the stack, never per layer: clear,
  quantise, bezel mask, AOD mask, skin.
- **Frame membership single-sourced (P3 A).** One function,
  `frame_members(resolved, frame, style)`, answers which elements draw in
  awake, sleep or AOD, under the layout switch and the awake-only second
  hand. `view._drawn_in`, `_emit_layout_guarded`, `_emit_aod_body` and
  `preview.render` all read it.
- **The contract (P4 A).** A Python reference rasteriser of the JSON
  form must equal the evaluator's layer image pixel for pixel, for every
  ported element. Stacking all layers must equal `preview.render`, within
  the anti-aliased rounding research 27 §5.4 measured. Both are tests.
- After this slice the GUI plan can start (research 27 S3).

### Slice 4 — `icon`: done

Built as below. `IconKind.lower` replaces `emit_draw` and `draw_preview`.
The program gained:
- `Glyph`: an icon's glyph, printed as an upright `drawText` (the text
  printer's own upright path, now shared) and painted as its baked tile at
  the icon's measured box, moved as far as a stamp moves `x`/`y`. That is
  exactly where today's preview pasted it; a `drawText` placement would
  have moved odd-width glyphs by the box's rounding.
- `IconChoice`: a dynamic icon's glyph. It prints
  `IconGlyphs.glyph(WfbWeather.chooseIcon(<reading>))` and evaluates
  through `wfb.icons.choose_weather_icon`, the twin of `chooseIcon`
  (`weather_unknown` for a null or out-of-range condition, as the barrel
  does), over the existing drift-tested table.
- `evaluator.paste_glyph`, shared by the evaluator and the JSON form's
  `glyph` op.

The preview's sample readings gained the three weather conditions, all
`Weather.CONDITION_RAIN`, the glyph a dynamic icon's box is measured with.
So a default preview draws what it drew before, and a different sample
condition now draws its own glyph.

Proven before the old methods were deleted, on every icon in `examples/`
and `tests/fixtures/`, on each face's targets:
- printed code byte-identical to `emit_draw`: **1 422/1 422** (no `aod:`,
  `aod:` on, `aod:` with `dim:`; own ring, and 1 px and 2 px ring passes);
- whole-frame renders identical with the program and with the old
  methods: **144/144** (1×, 2×, asleep, AOD).

`tools/snapshot.py`: 551 unchanged against the slice's starting snapshot,
the sample conditions included. Real builds of `features/rings` (an
outlined icon) and `generated_by_skill/trail-utility` (a dynamic icon) are
warning-free on all three targets.

Tests (`tests/test_draw_icon.py`): the printed glyph and chooser, a ring
pass drawing only the ring, the ring font painting exactly the stamp of the
glyph, the glyph each sample condition chooses (with a contrast between
two), the barrel's fallback, and the JSON naming the `_CX` constant. The
chooser was seen red against a constant glyph.

### Slice 5 — `progress` (gauge): done

Built as below. `ProgressKind.lower` replaces `emit_draw`, `draw_preview` and
their seventeen private helpers. The program gained:
- numbers the watch computes: `FloatLit`, `NumLocal`, `Read` (a bound
  expression), `Bin`, `Paren`, `Call` (a barrel or `Math` function, its
  twin in `barrel.CALLS`), `Conv` (`toNumber`/`toFloat`) and `NumPick`. A
  `Bin` prints bare, and the evaluator reads a chain the way Monkey C parses
  the printed text, `/` of two `Number`s truncating;
- conditions: `Present` (value guards, probed by their expressions on the
  host), `LocalsSet`, `Cmp`, `NotPulsing`;
- ops: `Let`, `Assign`, `If`, `For`, `ArcProgress` (`WfbArc.drawProgress`),
  `Part` (a rotated or translated part and its `WfbRing`/`WfbRingWide`
  ring), `LetSlotPick`, `LetAutoScale`, and `WrapperGuard`, the view's own
  guard, which the printer leaves to the view and the evaluator honours
  until slice 10;
- paints `AodPart` and `PaintPick`; `DrawContext.complications_guarded`.

A gauge's arc now paints through `WfbArc.drawSpan`'s transcription.
The host's complication is always present, with the sample as its value, so
a `max: auto` gauge with no sample reading keeps its track, as the guide
says. A bar's or a needle's filled-circle ring stays a `Disagreement` until
Q1.

Proven before the old methods were deleted, on every gauge in `examples/`
and `tests/fixtures/` on each face's targets:
- printed code byte-identical: **1 440/1 440** (no `aod:`, `aod:` on, with
  `dim:`; 1 px and 2 px ring passes; `Complications` guarded or not);
- whole-frame renders (1×, 2×, 3×, AOD): **156/204** identical. The other
  48 are one named preview fix: **a bar's fill was one preview pixel too
  wide** (the old preview filled to `X + filled` inclusive; `fillRectangle`
  stops a column short of it). With the old width emulated, renders are
  **204/204** identical. Affected: `features/align`, `features/profile`,
  `features/rings`, `showcase`, `tests/fixtures/outline_pattern_gauge`.

`tools/snapshot.py`: 534 unchanged, 17 changed against the slice's starting
snapshot, every one a preview of those five faces (default, asleep, time,
all styles); no generated file changed. Real builds of `features/progress`,
`features/slot-gauge` and `outline_pattern_gauge` are warning-free on all
three targets.

Tests (`tests/test_draw_gauge.py`): the parse order and integer division,
`percent`'s clamp, the bar's last fill column, segments lit 7 and 6 of 10,
`max: auto` with and without a reading, a slot gauge's editor check and a
scaleless pick, and a needle's ring through the barrel. Seen red: tree-order
evaluation, the one-column-wide fill, truncated segment rounding, and a
scale that vanished with its reading.

### Slice 6 — `pattern`: done

Built as below. `PatternKind.lower` replaces `emit_draw`, `draw_preview` and
nine private helpers. The copy loop is a `For` with `copy`, which binds the
readings' `copy` to the loop index on the host; a skip is `If(AnyOf(...))`
around a `Continue`; a part's own `visible:` is `If(Truthy(...))`. The
program gained:
- `Continue`, `For.copy`, the conditions `AnyOf` and `Truthy`;
- `PerCopy`, a text part's string: printed as before, and on the host the
  copy's own string rendered at build time;
- `FontDrop`, a `bottom` line's height subtracted where the code puts it
  (inside a radial copy's `WfbGeom.rotatedY`), which the host ignores since
  it places the line by `vertical_align`;
- `Text.split_x`, `Text.shift_y`, a `Num` angle (`_text_angle`),
  `IfNotNull.present` (a vector font this device does not resolve),
  `ArcSpan.pen_first`, the `note:` comments on `SetColor`/`SetPen`/`Let`,
  `WrapperGuard.sources`, and the `WfbGeom.rotatedX`/`Y` twins in
  `barrel.CALLS`. The evaluator now resets the pen after an arc, as
  `WfbArc.drawSpan` does.

Proven before the old methods were deleted, on every pattern in `examples/`
and `tests/fixtures/` on each face's targets:
- printed code byte-identical: **1 392/1 392** (no `aod:`, `aod:` on, with
  `dim:`; 1 px and 2 px ring passes);
- whole-frame renders (1×, 2×, 3×, AOD): every difference has one of two
  named causes, shown by emulating the old behaviour:
  1. **A radial copy's angle is the printed one**, `start + i * step` in
     radians, not `radians(start + i * step)`. The two differ only in the
     last bit, which at a cardinal angle decides which pixel a line end or
     a circle lands on. With the old angle emulated, 158 of 172 renders are
     identical, and of the other 14, 5 differ only at 3×, where the old preview
     scaled the centre and the rotated offset separately (one to a few
     pixels).
  2. **A ringed pattern's text part rings with its own glyphs**: the watch
     draws the text at each ring offset in the ring colour, and the preview
     now does, so an anti-aliased glyph's ring blends at its edges. The old
     preview pasted a hard-edged dilation of the text's silhouette (the 9
     remaining renders, all of `tests/fixtures/outline_pattern_gauge`'s
     `numerals`; every differing pixel was solid ring colour and is now a
     blend).

`tools/snapshot.py` against slice 5's starting snapshot: 521 unchanged, 30
changed, every one a preview. Seventeen are slice 5's bar fills; the other 13
are `analog-custom`, `features/gauge`, `features/vector-text` and
`generated_by_skill/navy-classic` (cause 1) and more of
`outline_pattern_gauge`. No generated file changed. Real builds of
`features/patterns`, `features/grid`, `features/vector-text` and
`outline_pattern_gauge` are warning-free on all three targets.

Tests (`tests/test_draw_pattern.py`): a skipped copy draws nothing, a colour
reading `copy` alternates per copy, a grid's rows step by whole division,
the radial angle is the printed literal, and a ringed text part draws five
texts a copy. Seen red: `continue` ignored, `copy` unbound, and `/` as a
float division.

### Slice 7 — `hands`: done

Built as below. `HandsKind.lower` replaces `emit_draw`, `draw_preview` and
`_emit_one_hand`. Each hand is the needle's machinery (`Part`, ringed
through `WfbRing`/`WfbRingWide`, a filled circle part's grown ring a
`Disagreement`), with the angle a new value, `HandAngle`
(`WfbHands.<fn>(clock)`, evaluated at the sample time), and an `awake`
second hand under the new condition `NotSleeping` (`!_sleeping`). The angle
twins moved from the kind into `wfb.draw.barrel` (`hour_angle`,
`minute_angle`, `second_angle`), unchanged; `HAND_ANGLES` points at them.

Proven before the old methods were deleted, on every `hands` element in
`examples/` and `tests/fixtures/` on each face's targets:
- printed code byte-identical: **552/552** (no `aod:`, `aod:` on, with
  `dim:`; 1 px and 2 px ring passes);
- whole-frame renders identical: **125/125** (1×, 2×, 3×, AOD, asleep).
  A hand's rotation was already float, as the barrel's is.

`tools/snapshot.py`: the same 30 previews as slice 6, pixel counts and all;
nothing else changed. Real builds of `features/analog`, `analog-custom` and
`outline_hands` are warning-free on all three targets.

Tests (`tests/test_draw_hands.py`): the second hand gone asleep and in AOD,
the minute hand turned by 9 × 6° at 10:09, and each hand's ring before its
own parts. Seen red: an always-awake condition, and every hand on the
hour's angle.

### Slices 8–9 — the remaining kinds

One kind per slice, in this order. Each deletes its `emit_draw` and
`draw_preview` and is proven by the snapshot:

| Slice | Kind | New ops and twins | Notes |
|---|---|---|---|
| 4 | `icon` | glyph from the icon font, `WfbWeather.chooseIcon` (a dynamic icon) | ring by ring font |
| 5 (done) | `progress` (gauge) | `WfbArc.drawProgress`, segments, needle and scale, slot scale (`WfbScale`, `SlotScale`) | the fraction's clamp and minimum (plan 25) as program values |
| 6 (done) | `pattern` | `For` over copies, rotated parts (`WfbGeom.fillRotated` and the rest), pattern text | the largest kind (about 1 170 lines) |
| 7 (done) | `hands` | `WfbHands.*Angle`, rotated parts, the second hand's low-power path | `onPartialUpdate`'s clip stays in `view.py` (P3) |
| 8 | `graph` | `WfbSeries.*` | series sampling stays host-side as now |
| 9 | `complication_slot` | `WfbComplications.valueOf`/`count`, the slot's icon and text, the editor-highlight box | about 700 emitter lines today |

Each kind's JSON op list joins the editor's layers as it lands.

### Slice 10 — the wrapper and the close-out

- The per-element wrapper's guards move into the program (P3 A):
  - `visible:`;
  - absent → hide;
  - the nullable colour guard;
  - the anti-alias bracket.

  The view prints a `draw<Id>` whose body is wholly the program.
- Delete what has no caller left: the `twin of` helpers in `preview.py`
  (`aod_color`/`aod_field`/`aod_geometry`, `silhouette`/`dilate` if no
  kind still uses them, `arc_span`), and the parity comments.
- Docs, in the same commit as the code they describe:
  - `docs/development.md` "Element kinds" and "Adding an element kind":
    `lower()` is the drawing hook;
  - `docs/lore/codegen.md`;
  - `docs/lore/roadmap.md`: the draw program moves from "decided" to
    built;
  - ADR 0004: a dated amendment, "one lowering, rule-free backends" as the
    anti-drift guarantee;
  - ADR 0003's barrel note, where it changes;
  - `docs/limitations.md` for the preview fixes;
  - the root `CLAUDE.md` §6 pipeline table: a "Draw program" row.
- Delete this plan, and add its row to `docs/plans/README.md`.

## 4. Tests, beyond each slice's own

- **The snapshot is the gate**, run at every slice. A diff that is not
  listed fails the slice.
- **Golden files** (`tests/golden/`) change only where a slice lists an
  expected code diff.
- **Primitive property tests** (slice 0 onwards), as above.
- **Layer stacking** (slice 3 onwards): every example's stacked layers
  equal `preview.render`, with the measured anti-aliased tolerance and
  nothing else.
- **`mypy --strict`** stays clean over `wfb/` (`pytest -m typecheck`).

## 5. What stays the same

- The format, the schema, the guide's description of every key.
- The IR, layout, lints, `Layout` constants and `ReadPlan`. The program
  reads them; it does not replace them.
- `view.py`'s frame skeleton and the app, delegate and settings menu
  modules (P3 A).
- Generated code, byte for byte, through slice 10, except where a slice
  lists a diff (P2 A).

## 6. Risks

- **`pattern` and `complication_slot` are large and unspiked.** Each
  slice may take more than one commit. The snapshot keeps every
  intermediate state honest.
- **A program that can print *more* than today's emitter is no risk
  while P2 A holds:** the snapshot proves it prints exactly today's.
- **Preview speed.** The evaluator replaces the preview's silhouette-and-
  dilate rings, its slowest path (up to 102 ms for one element, research
  27 §2.1), with the emitter's stamps and ring fonts. It should be faster.
  It is measured at slice 1 and slice 2 with research 26's latency probe.
- **Memory on the watch.** Unchanged while code is byte-identical. Any
  later deliberate change carries its `--build-stats` figure.

## 7. Open question

- **Q1: grown or stamped ring on the watch** (research 28 §7). Run
  `build/ring-probe/ring-probe/ring-probe-fenix8solar47mm.prg` in the
  simulator on the host, save a screen capture, and run
  `docs/research/probes/ring-on-device/compare.py CAPTURE.png`.
  - If the grown cells match the evaluator, slice 1's preview fix stands.
  - If they match the stamp, slice 1 changes the emitter to stamp these
    shapes, with its draw-count and memory figures.

  Needed before slice 1's second expected-diff commit, not before slice 0.
