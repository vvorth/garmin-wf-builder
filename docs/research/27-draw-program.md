# 27 — Before the editor: narrow the GUI, cut features, or build the single draw program?

**Question (user, 2026-10-01), following research 26.**

1. Should the first GUI leave features out? It would place elements by type,
   size and align them visually, and write YAML that the author then
   extends by hand. Or should the project itself shrink first, reverting
   `overrides:`, `outline:`, slots and `graph`, so that a base GUI is easier
   to build? The features would come back later, designed with the new live
   preview in mind.
2. The GUI must support editing in layers, one element at a time, so
   `wfb preview` will not help much. Is plan 19's option A7, "a single draw
   program", the better base? Designed with a live per-layer preview in
   mind, it would serve codegen, the live preview and the static preview
   alike.

**Short answer.**

1. **Narrow the GUI, not the compiler.** A geometry-only editor (place by
   type, size, align, add and delete) is research 26's slices 1–3 plus "add
   an element". Text patches carry every other feature through untouched,
   so it needs nothing removed. A one-way generator ("emit YAML, then edit
   it by hand") is cheaper only until the first hand edit: after that the
   GUI cannot reopen the file (§3).
2. **Do not revert features.** Each one costs the editor little or nothing
   (§4). `overrides:` never reaches drawing at all. And the features in
   question are where a single draw program pays off most: `outline:` is
   both the preview's slowest path and the one place where the spike found
   the preview and the emitted code disagreeing (§2.5). The decisive point
   is that today's implementation is the **oracle**. `tools/snapshot.py`
   can prove a port output-identical only while the old code exists.
   Reverting and reintroducing gives that up.
3. **Layered editing does not *require* A7.** Today's `Renderer` already
   draws one element at a time. Alone, an element costs a median 0.06 ms
   (§2.1). Eight Pillow calls cover every element in the examples (§2.4), so
   a per-layer list of drawing calls can be recorded today.
4. **A7 is still the better base, and the GUI is what tips it.** Plan 19
   advised against A7 because the preview was only a check. In an editor
   the preview is the main view, so every remaining disagreement shows up
   as "the editor was wrong". A spike lowered the `shape` kind (164 of 395
   example elements) to one program:
   - its Monkey C printer reproduced today's `emit_draw` **byte for byte
     for 163 of 163 elements**;
   - its Pillow evaluator matched today's preview pixel for pixel for 158;
   - the 5 that differ are the grown outline rings, where today's preview
     draws a stamp and the watch is sent a grown copy (§2.5).

   The spike also found a 1° arc-start disagreement at every half-degree
   start angle. VERIFIED, on the Pillow model.
5. **Recommendation: build A7 first, kind by kind, designed around three
   backends.** These are a Monkey C printer, a Python evaluator (the static
   preview and per-layer PNGs) and a serialisable, partly evaluated form
   that the browser can redraw while a drag is in progress. The GUI viewer
   starts once A7's core and `shape`/`text` are ported. Kinds not yet
   ported keep their current two halves behind the registry, so nothing is
   reverted (§5, §6).

Every claim is marked VERIFIED or UNVERIFIED. The probes are
`docs/research/probes/draw-program/probe.py` and `spike_shape.py`. Their
output is in `results.txt` and `spike_results.txt` beside them.
**No compiler code changed.**

---

## 1. What is being decided

Research 26 recommended a local web app that is a thin client over
`preview.py`, built in slices: viewer, text pane, drag, then per-element
layers. It placed A7 as a decision to take before the layer slice. The user
asks whether that ordering is backwards, and whether the project should
shrink first to make the base easier.

Plan 19's A7, as written
(`git show d325e77:docs/plans/19-architecture-refactor.md` §3): "Lower each
element once into a small display list of drawing steps over symbolic
expressions. Preview evaluates it, emit prints it as Monkey C. This removes
P2 entirely, but rewrites most of `preview.py` and `emit/monkeyc/`.
Recommendation: don't, unless the user expects many more drawing features."

## 2. Experiments

Every example face except `examples/dashboard` (the user's playground) is
used, 29 in all, on `fenix8solar47mm`.

### 2.1 What one element costs to draw alone

Each drawn element went through `Renderer.render_element` on its own, at
2×. The figure is the minimum of five warm runs.

| | ms |
|---|---:|
| median over 330 elements | 0.06 |
| p90 | 0.44 |
| p99 | 31.7 |
| max (`features/outline` `wordmark`, an outlined text) | 101.5 |

Every slow element is a ring or vector text:
- `features/rings` `ticks`, an outlined pattern: 65 ms;
- `features/vector-text`: up to 32 ms per element;
- an outlined hand: 17 ms.

The preview's ring paints the element twice on scratch canvases, then
dilates the mask (`Renderer.silhouette`, `dilate`). The emitted code instead
stamps or grows the primitive. VERIFIED.

**Consequence:** re-rendering one layer is effectively free once layout has
run, apart from rings and vector text. The floor of an edit is load and
resolve (research 26 §3.1), not drawing.

### 2.2 What is not "one element drawing itself"

These are the structures a per-layer model must handle, counted over 395
elements (groups excluded):

| Coupling | Elements | Faces | What it means for layers |
|---|---:|---:|---|
| in a `static:` subtree | 114 | 17 | drawn once into an offscreen buffer on the watch, but still one element each |
| scoped to a Styles `layouts:` entry | 124 | 5 | a filter on the layer list |
| own `outline:` | 41 | 3 | a ring drawn before the element; part of its layer |
| member of an outlined **group** | 6 (3 groups) | 2 | the ring is the union's dilation, drawn before the first member: **the one genuinely cross-element layer** |
| bound to a `config: slots:` slot | 12 | 5 | one wearer choice drives several elements; selection is per element |
| `aod:` override | 4 | 2 | a second frame; same layers, other values |
| `overrides:` | 0 | 0 | resolved before drawing (§4) |

By kind, the example elements are:

| Kind | Elements |
|---|---:|
| shape | 164 |
| text | 104 |
| icon | 35 |
| progress | 32 |
| pattern | 31 |
| hands | 14 |
| complication_slot | 9 |
| graph | 6 |

`shape`, `text`, `icon` and `progress` make up 335 of 395 (85 %). VERIFIED.

### 2.3 The drawing vocabulary the program must express

All 29 faces were run through `wfb build --no-compile` on their own targets.
The generated views total 12 635 lines, in 439 `draw<Id>` functions:

- **24 distinct `Dc` methods.** The most used are `setColor` (548),
  `drawText` (210), `setPenWidth` (198), `fillRectangle` (67) and
  `drawLine` (61). The rest is the fill/draw set, radial and angled text,
  bitmaps, clip, and `setAntiAlias`.
- **33 distinct barrel functions.** The most used are `WfbArc.drawSpan`
  (60) and `WfbGeom.fillRotated` (47). Some are drawing calls; others
  compute values (`WfbMath.percent`, `WfbHands.*Angle`,
  `WfbComplications.valueOf`).
- **Control flow:** `if` 589, `for` 65, `else` 49, `switch` 17.

So the program is not a flat display list. It needs the following, as the
generated code already does:
- runtime conditions: null guards, `_aod`, the layout switch;
- loops: segments, scale ticks;
- runtime arithmetic: needle angles, hand rotation.

VERIFIED (counts).

### 2.4 Today's preview, recorded

A proxy around `Renderer.draw` and `Renderer.image` counted every Pillow
call each element makes. Across all 330 elements there are only eight:

| Call | Count |
|---|---:|
| `image.paste` (glyphs, icons, rings) | 412 |
| `draw.text` (system-font stand-ins) | 388 |
| `draw.line` | 367 |
| `draw.ellipse` | 121 |
| `draw.rectangle` | 103 |
| `draw.polygon` | 100 |
| `draw.arc` | 56 |
| `draw.rounded_rectangle` | 6 |

VERIFIED. **Consequence:** a concrete per-element display list for a
browser can be recorded from today's renderer with no A7. It would be a
list of coordinates and colours with no structure, though, so nothing in it
can be re-evaluated when a dragged value changes.

### 2.5 Spike: one program for `type: rectangle/circle/ellipse/line/arc/polygon`

`spike_shape.py` lowers a `shape` element, once, into a few ops:
- `SetColor(expression)`;
- `SetPen(n)`;
- a `Dc` primitive over numbers;
- `fillPolygon` of a `Layout` constant;
- `WfbArc.drawSpan`.

Each number is a `Layout` constant, a literal, or either one shifted by a
build-time integer. Two backends consume it:

- **a printer**, which writes Monkey C through the emitter's own `Writer`;
- **an evaluator**, which emulates `Dc` in Pillow, including
  `WfbArc.drawSpan`'s own rounding.

The spike covers the awake frame and the element's own `outline:` ring. AOD
variants and group ring passes are out of scope.

| Measure | Result |
|---|---|
| shape elements in the examples (without `aod:`) | 163: every primitive; filled, stroked and ringed |
| printed Monkey C byte-identical to `ShapeKind.emit_draw` | **163/163** |
| evaluated pixels identical to `draw_preview` at 1× / 2× | **158/163**, **157/163** |
| the elements that differ | all are filled circles, rectangles and rounded rectangles with an `outline:` (`features/profile`): 8–28 px at 1× |

VERIFIED. Two of the spike's own bugs showed up and were fixed in it:
- the ring's `setPenWidth` must come before its `setColor`;
- the `visible:` guard lives in the view's wrapper, not the kind.

Both are what a port would meet.

**The pixel differences are a real disagreement between the two halves
today.** For a filled circle or rectangle, the emitter draws the ring as
*one grown copy* (`fillCircle(r + w)`, research 19 §3.2). The preview draws
the *stamp*: the silhouette at the disc offsets. Those are different pixel
sets. In the spike, the evaluator ran what the emitter emits, so it shows
the grown copy. Which one matches the watch's rasteriser is UNVERIFIED (no
simulator, root `CLAUDE.md` §3). Either way, today's preview and today's
generated code describe different rings.

**A second disagreement, in arithmetic.**
- Today's `preview.arc_span` rounds the author's start angle (clockwise
  from 12).
- `WfbArc.drawSpan` rounds the *Garmin* start angle, `(90 − start) mod 360`.

At every half-degree start the two round in opposite directions, so the
preview draws the arc 1° away from the watch. That is 1080 of 2160 sampled
(start, sweep) pairs: every `.5` start, and none of the others. VERIFIED
(arithmetic). No example face has a half-degree start, but a
`pattern`/`progress` angle computed as `360 / n` can produce one.

Both differences are exactly the class of bug A7 removes by construction:
the evaluator runs the op the watch runs.

## 3. Proposal 1a: a geometry-only GUI

"Place elements by type, size and align them, generate the YAML, and the
author adds the rest by hand" comes in two forms.

| | One-way generator | Round-trip editor, geometry only |
|---|---|---|
| what it writes | a new file from a GUI model | span patches to the author's file (research 26 §3.3) |
| after a hand edit | cannot reopen the file without a YAML → model importer, which is the round-trip problem again | reopens it; unknown keys are text it never touches |
| features it must understand | none | none to *edit*; it must *draw* all of them, which the renderer does |
| new code | a model, a YAML writer, a canvas | the patch engine (research 26's slice 3) |
| precedent | research 06's sketch skill, built and deleted at the user's request | — |

**The round-trip form is the same size of work as the one-way form, plus
the patch engine**, and the patch engine is already measured (77/77 scalar
edits). The one-way form saves the patch engine but loses the editor after
the first save. Recommendation: the round-trip, geometry-only editor is the
right first GUI. Its edits are:
- `at:`, `size:`, `radius:`, `thickness:`, `start_angle:`/`sweep:`,
  `align:`;
- add an element of a chosen type with defaults;
- delete, duplicate, reorder.

Everything else stays in the text pane. This is the user's 1a, made
reversible.

## 4. Proposal 1b: revert features first

What each feature costs the GUI, and what it costs A7:

| Feature | Uses in the examples | GUI cost | A7 cost | Reverting it buys |
|---|---|---|---|---|
| `overrides:` | 0 faces | the patch target (research 26 §4.4). v1 can show "an override applies here" read-only | **none**: applied by `Resolver.for_device` before any kind resolves; drawing never sees it | nothing |
| `outline:` (own, group) | 41 elements, 3 faces; 3 group rings | a ring is part of its element's layer; a group ring is one extra layer before its first member | moderate: a ring is "the element's program at N offsets" or one grown op. The spike already prints both | it removes the preview's slowest path *and* the one measured preview/emit disagreement, i.e. the evidence that A7 is needed |
| slots (`complication_slot`, `slot:` on a gauge) | 12 elements, 5 faces | selection is per element; the slot is an inspector concern | the largest single kind: about 700 emitter lines (`emit/monkeyc/complication_slot.py`) | a smaller port, at the price of re-deriving research 24 and plan 25 |
| `graph` | 6 elements, 4 faces | none special | small: three `WfbSeries.draw*` ops | little |

Against reverting, beyond the table:

- **The oracle.** `tools/snapshot.py` records every generated file and
  every preview pixel for every example and fixture, on three device sets.
  It is how plan 19's A0–A6 were proven output-identical. A port of a
  feature that still exists can be proven the same way, kind by kind. A
  feature reverted and rewritten later has nothing to be compared against.
- **The work is not saved, only moved.** A reverted feature comes back as a
  lowering into the program, which is exactly what porting it would be.
  Porting also keeps its tests, research decisions and edge cases. A
  rewrite rediscovers them.
- **The sequencing benefit is available without deleting anything.** The
  kind registry (`wfb/kinds/`) lets A7 land one kind at a time (§5.5). A
  kind not yet ported keeps `emit_draw`/`draw_preview`. That is "a smaller
  base first" without removing a shipped feature.

Recommendation: **revert nothing**. If the base must be smaller to start,
the cut is in *what A7 ports first*, not in what the compiler supports.

## 5. A7, designed for the editor

### 5.1 What changes in the argument

Plan 19 weighed A7 against the cost of keeping two halves in step by hand,
and judged that parity tests could hold most of that risk. Three things are
new:

- **The preview becomes the primary view.** In research 26's editor the
  author looks at the preview, not the watch. Every rule the two halves
  implement differently, measured in §2.5, becomes a visible lie in the
  editor.
- **The editor needs layers *with structure*.** A recorded display list
  (§2.4) has coordinates. A program has `Layout` constants. During a drag
  the browser could re-evaluate one layer with the dragged constants
  changed, instead of waiting for a server round trip (§5.3).
- **The cost is now measurable.** The spike lowered the kind with the most
  elements, with both backends, in about 250 lines. It matched 163/163 on
  text. That retires plan 19's open risk that a generic printer could not
  reproduce the hand-tuned emitter. For `shape` it can, byte for byte,
  including the polygon ring copies baked into `Layout`, the grown copies,
  and a pen set once around a stamp.

### 5.2 Shape of the program

What the generated code already does (§2.3) sets the requirements:

- **Values:** `Layout` constants (per device), literals, palette and config
  references, readings (an `Expression`, already compiled and evaluated
  from one AST by `wfb/expr.py`), and locals.
- **Ops:** the `Dc` methods in use (24), and the barrel's drawing calls as
  ops (`WfbArc.drawSpan`, `WfbGeom.fillRotated`, …).
- **Structure:** `if` on a value (null guards, `_aod`, the layout switch),
  `for` over a range (segments, ticks), and local assignments (an angle, a
  lit count).
- **Annotations:** each op group carries its element id, and so its author
  span. A ring pass is a marked block. A group ring is its own block,
  addressed by the group id.

**What stays written twice:** each primitive and barrel op has a printer
(one Monkey C call) and an evaluator (one Python function). That is about
57 small functions with a contract each, unit-testable one at a time,
instead of today's rules spread across nine kinds' `emit_draw` and
`draw_preview`. The twin moves down from *element rules* to *primitives*.
Today's twins are already this shape: `arc_span` vs `WfbArc.drawSpan`,
`AodStyle` vs `Renderer.aod_*`. The spike's arc finding shows that even a
primitive twin drifts, so each one needs a property test (§7).

### 5.3 Three backends

| Backend | Consumes | Produces | Used by |
|---|---|---|---|
| Monkey C printer | the program | the view's `draw<Id>` bodies, unchanged in shape | `wfb build` |
| Python evaluator | the program + sample values + `Layout` values | Pillow drawing, the whole frame or one element on a transparent ground | `wfb preview`, lints that render (burn-in), the editor's authoritative layer PNGs |
| partial evaluator → browser | the program with readings folded to their sample values, `Layout` constants kept symbolic with their values | a JSON op list per layer | the editor while a gesture is live |

The browser backend rasterises about eight primitives and blits glyphs from
the same baked sheets. It holds **no rules**: every decision (which ring,
which guard, which colour, the AOD swap) was made in the lowering. It only
draws while the pointer moves. On release, the server's Python evaluator
sends the authoritative PNG. Research 26's constraint C4 ("exactly two
renderers") is then restated as **one lowering, rule-free backends**. That
keeps the guarantee C4 exists for (the editor shows what the watch draws)
while adding a third rasteriser. Canvas anti-aliasing differs from both
Pillow and the watch, so the live drag is approximate by design, and the
drop corrects it. UNVERIFIED, design only.

**What a live drag can re-evaluate in the browser.**
- **Translation:** exact by shifting the layer.
- **A handle that maps to one constant:** `_RADIUS`, `_WIDTH`/`_HEIGHT`,
  `_START`/`_SWEEP`, `_THICKNESS`. The layer can be redrawn from its ops
  with that constant changed, which is exact in structure.
- **Constants derived from layout** (a text box from font metrics, pattern
  copy positions, polygon ring copies): these are not recomputed in the
  browser. Such a layer translates live and is re-resolved on the server,
  throttled.

UNVERIFIED: how this feels at 60 Hz is the editor's first measurement.

### 5.4 Layers: one transparent image per element, stacked

**Yes: the Python evaluator renders each element alone onto a transparent
ground.** The editor stacks these layers in draw order, and drags one
without touching the others. An outlined group's ring is a layer of its
own, placed just before the group's first member. Everything that
belongs to the whole frame runs once, on the stack:
- the black `dc.clear`;
- palette quantising;
- the bezel mask;
- the AOD pixel mask;
- the skin.

**Why stacking can be exact.** The watch has no alpha blending
(constraint 10). No element reads the pixels under it, except where an
anti-aliased edge blends into them. Drawing in order onto one frame and
stacking per-element layers in order therefore agree, up to the rounding of
those blended edge pixels.

**Measured on today's renderer**
(`docs/research/probes/draw-program/layers.py`, `layers_results.txt`):
- each element, and each group ring, was rendered alone onto black and
  onto white;
- its colour and coverage were recovered from the pair (difference
  matting);
- the 29 faces were stacked over black and compared with `preview.render`
  at 2×.

| | Faces identical |
|---|---:|
| unquantised, unmasked | **28/29** |
| after quantise and the bezel mask, applied to the stack | **28/29** |

The one exception is `analog-custom`. It has two anti-aliased text
elements: `hour_ticks`' numerals and the data readouts. Its 2 938 differing
pixels (of 270 400) are **all off by exactly 1** in one channel: 8-bit
rounding on blended edges. After quantising, 24 of them land in a
different palette colour. VERIFIED.

So:
- **in the editor, layers are exact for every aliased element**, and
  within one level of rounding on anti-aliased edges;
- **the full-frame render stays authoritative** for `wfb preview`, the
  lints and the editor's "as on the watch" view;
- an evaluator that writes coverage straight into the layer's alpha
  channel avoids matting, but it does not remove the rounding difference
  in blending.

**A group ring is the one layer that depends on others.** Dragging a member
changes the ring's shape. In the program, the ring is the members' own ops
stamped at offsets. So the browser can redraw it during the drag from the
dragged constants, like any other layer (§5.3), and the server re-renders
it on release. VERIFIED that the ring stacks correctly as a separate layer
(`features/rings`, `features/profile` are among the 28). The live redraw is
UNVERIFIED.

**`static:` and `layouts:`** need nothing special. A `static:` subtree is
an offscreen buffer on the watch, but in the editor it is ordinary layers.
A Styles layout filters the layer list.

### 5.5 Landing it kind by kind

- `ElementKind` gains `lower()`. When a kind has it, the view's
  `draw<Id>` body is printed from the program and the preview evaluates
  it. When it does not, today's `emit_draw`/`draw_preview` run. The two
  coexist per kind.
- Each port is a commit proven by `tools/snapshot.py`: generated code
  byte-identical, and preview pixels identical, **except** where the old
  preview twin was wrong (the grown ring, the half-degree arc). Those land
  as separate, named commits with the expected preview diffs listed.
- Order by coverage and risk:
  1. `shape` (the spike, plus AOD variants and group ring passes);
  2. `text` (fonts, curves, rings by ring font);
  3. `icon`;
  4. `progress`;
  5. `pattern`;
  6. `hands`;
  7. `graph`;
  8. `complication_slot`.

  The first four are 85 % of the example elements.
- When the last kind is ported, the old halves and the `twin` comments go,
  and `preview.py` shrinks to options, the evaluator, quantise, mask and
  skin.

### 5.6 Risks

- **Generated-code quality and memory** (constraint 2: 49 152 B is the
  floor). The printer must keep emitting exactly what the hand-tuned
  emitter emits; the snapshot proves it per kind. A program that is
  *capable* of something less efficient is no regression while the
  snapshot holds.
- **Text is the hard kind.** Font kinds (baked, system, `.cft`, vector),
  `curve:`, ring fonts versus stamps, and placeholders all have to be
  expressed. `text.py` is the largest emit/preview pair after `pattern`. It
  is unspiked. UNVERIFIED.
- **`static:`** draws a subtree into a `BufferedBitmap` once. In the
  program that is a block printed into `renderStatic`. In the editor it is
  ordinary layers. UNVERIFIED in detail.
- **Effort.** It rewrites the drawing half of `wfb/kinds/` (about 1 260
  emit and 660 preview lines by a textual split) and the drawing parts of
  `emit/monkeyc/view.py` and `complication_slot.py`. The rest of the
  pipeline is untouched: schema, lower, desugar, IR, layout, lint, the
  app, delegate and settings menu. This is the largest refactor proposed so
  far, but it is incremental and proven at every step.

## 6. Sequencing options

| | Order | For | Against |
|---|---|---|---|
| **S1** | research 26 as written: GUI slices 1–3 on today's renderer, A7 before slice 4 | the editor sooner | the editor is built on a preview with known disagreements, and its layer protocol is designed twice |
| **S2** | A7 complete, then the GUI | one base, no interim | the longest time to anything visible; every kind must be done first |
| **S3** | A7 core + `shape`, then `text` → the GUI viewer drawing layers from the program (unported kinds as per-element PNGs from their old path) → port the rest while the GUI grows: text pane, geometry drag, layers, build | the user's base-first intent, with something runnable early; the viewer becomes the visual check on each port | two drawing paths coexist for a while (bounded: they are per kind and tested) |

**Recommendation: S3.** It is the user's proposal (A7 as the shared base,
GUI on top) without waiting for every kind, and without reverting anything.

## 7. Open questions and first measurements

Research 28 closes or classifies every item below.

- **The `text` port.** This is the next spike: whether the program can
  express every font route and `curve:` while printing byte-identical code.
- **Primitive twins need property tests.** Each evaluator op should be
  checked against its barrel function's arithmetic over a sweep, the way
  §2.5 B found the arc rounding. Without that, A7 moves the drift down a
  level instead of removing it.
- **Which ring is right on the watch**, stamp or grown (§2.5). This needs
  the user's host simulator or a sideload. Until then, the program makes
  the preview show what the code does, which is the honest default.
- **The live-drag protocol** (§5.3): whether a symbolic op list per layer
  re-evaluated in the browser feels direct at 60 Hz, compared with a
  shifted PNG plus a throttled server re-render.

## 8. Decisions for the user

| # | Decision | Options | Recommendation |
|---|---|---|---|
| E1 | Revert `overrides:`, `outline:`, slots or `graph` first | revert some · revert none | **none**: they cost the editor little, `overrides:` costs A7 nothing, and the shipped code is the oracle a port is proven against (§4) |
| E2 | Scope of the first GUI | one-way generator · round-trip geometry-only editor · research 26's full slices | **round-trip, geometry-only**: placement, size, align, add/delete/duplicate/reorder; everything else in the text pane (§3) |
| E3 | Build A7 | no (plan 19's advice) · yes, two backends · yes, three backends designed for the editor | **yes, three backends** (§5.3); this reverses plan 19's "don't" because the editor makes the preview primary |
| E4 | Order | S1 · S2 · S3 | **S3** (§6); supersedes research 26's D4/D5 |

**Decided by the user, 2026-10-01: all four as recommended.**
- E1: revert none.
- E2: a round-trip, geometry-only first GUI.
- E3: A7 with three backends.
- E4: order S3.

Research 26's D1–D3 were decided the same day: a local web app, Starlette
and uvicorn, and no front-end build step (research 26 §8, ADR 0002
amendment).

Since E3 is yes, A7 becomes a plan (`docs/plans/`), and its first slice is the
spike made real for `shape`, including AOD and group rings, proven by the
snapshot. The deliberate preview fixes land as their own commits.

---

## Sources

- Research 26 (the editor); research 19 §3.2 (grown versus stamped rings);
  research 06 §5–§9 (the sketch skill and its deletion); plan 19 §2 P2 and
  §3 A7 (`git show d325e77:docs/plans/19-architecture-refactor.md`).
- `wfb/kinds/__init__.py` (`ElementKind`: `draw_preview`, `emit_draw`,
  `layout_constants`), `wfb/kinds/shape.py`, `wfb/preview.py` (`Renderer`,
  `render_element`, `render_sequence`, `silhouette`, `dilate`, `arc_span`),
  `wfb/emit/monkeyc/common.py` (`AodStyle`, `RingPass`, `plus`),
  `wfb/emit/monkeyc/shapes.py`, `wfb/emit/writer.py`, `wfb/layout.py`
  (`garmin_arc`, `Resolver.for_device`), `runtime-lib/WfbArc.mc`
  (`drawSpan`, `roundAway`), `tools/snapshot.py`.
- Probes: `docs/research/probes/draw-program/` (`probe.py`,
  `results.txt`, `spike_shape.py`, `spike_results.txt`, `layers.py`,
  `layers_results.txt`).
