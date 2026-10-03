# 29 — A browser renderer for the editor

**Question (user, 2026-10-03).** The editor shows a resize or an angle as
an outline until release, then waits for the server's frame. Can a
renderer in the browser make it snappier? Research 27 §5.3 designed one
and built only its server half, the JSON form (`wfb.draw.jsonform`).

**Status (2026-10-03): built as plan 28**
(`git show 2ab22c4:docs/plans/28-browser-renderer.md`). The decisions are
in §7. Where the build departed from this document:
- the tiles travel inside the frame, as raw RGBA, not as a PNG atlas;
- a move redraws the whole face from the layers' ops rather than shifting
  per-layer images;
- live handles cover 63 of 304, not 188 of 226 (the note under table C).
  Centred boxes and gauge arcs are plan 29.

**Short answer.** Yes, for two of the three waits the author feels, and
only partly for the third.

1. **There are three waits, and they have different causes** (§1):
   - **during a gesture:** a move is already exact (the layer image
     shifted), but a resize or an angle draws only an outline;
   - **release → new frame:** almost all of it is the server *loading*
     the edited text, parse plus schema (§2, table D: 214 of 227 ms on the
     showcase), not drawing;
   - **after the frame:** the layers request, 57–394 ms. Until it lands,
     the next drag shows only a box, and a click picks by box.
2. **A browser renderer removes the first and third waits outright.**
   - **During a gesture:** redrawing the dragged element from its JSON,
     with only the handle's own `Layout` constant changed, seemed to
     reproduce the server's edit for 154 of 226 handle drags (§3), 188
     with a `drawSpan` twin. **Building it found that figure optimistic**
     (§3, the note under table C). Proven exact are 63 of the corpus's
     304 size, radius and angle handles: every circle's and arc's, and a
     box's edge that is not centred. The rest fall back to the outline.
   - **After the frame:** the JSON is **214 KB against 957 KB** of layer
     PNGs over the corpus. Building it costs 1–23 ms per face, against the
     layers request's two full paints of every element.
3. **It hides the release wait but cannot remove it.** Every edit is
   still checked by the server's load, so drawing the predicted result at
   once only covers the wait. Making the load itself cheaper is a
   separate lever, recorded in §6.
4. **How to draw, recommended (§4):**
   - a **software rasteriser in JavaScript** that reproduces Pillow's
     primitives into an `ImageData`. It is pixel-testable in Node against
     `jsonform.rasterise`, with no browser, as the rest of the editor's
     front end already is;
   - **glyph tiles rendered by the server** for all text. Baked sheets
     already exist, and system-font text is drawn glyph by glyph at whole
     pixels, so tiles reproduce it exactly;
   - for **rotated or curved vector text**, the server's own image of the
     run, moved as a whole.

   The alternatives are Canvas 2D (approximate, and not testable without
   a browser) and Pyodide (exact by construction, but about 10 MB and
   seconds to start).

Probe: `docs/research/probes/browser-renderer/probe.py`, results in
`results.txt` beside it. Every example face is used except
`examples/dashboard`, on fr955 at the editor's 2×, except table B, which
uses each face's own first target. **No compiler code changed.**

---

## 1. What the author waits for

The canvas today (`wfb/studio/static/canvas.js`):

| Moment | What is drawn | Exact? | Cost |
|---|---|---|---|
| a move, in progress | every layer image, the dragged ones shifted | yes, a translation of the evaluator's pixels | none: local |
| a resize, a radius, an angle, a line's end, in progress | a dashed outline | no: shape only | none: local |
| release → new frame | the gesture's preview stays until the frame arrives | the frame is authoritative | the server's drag (load + patch + record) plus the frame (table B) |
| after the frame | the new frame; layers fetched next | — | the layers request (table B); until it lands a drag shows a box and a click picks by box |

So "snappier" means three different things. Only the second and third
are measured in milliseconds; the first is fidelity, not time.

## 2. Measured: where the time goes

**Table B** (`probe.py b`): a one-pixel move of each face's last drawn
element, in-process with the studio's own caches, warm, best of three, in
ms:

| face | drag total | of which load | of which resolve | commit + rest | frame | layers |
|---|---:|---:|---:|---:|---:|---:|
| `features/progress` | 27 | 25 | 0 | 2 | 11 | 57 |
| `showcase` | 235 | 228 | 3 | 4 | 34 | 294 |
| `features/vector-text` | 40 | 36 | 1 | 3 | 156 | 394 |

**Table D** (`probe.py d`): that load, by stage, warm, best of five, in ms:

| face | parse (ruamel) | schema (jsonschema) | lower + desugar | IR | total |
|---|---:|---:|---:|---:|---:|
| `features/progress` | 10 | 12 | 0 | 1 | 23 |
| `showcase` | 100 | 114 | 4 | 8 | 227 |
| `features/vector-text` | 16 | 16 | 1 | 2 | 35 |

VERIFIED. A release is almost entirely the load. Resolving and recording
cost a few ms, and drawing the frame is the larger part only for vector
text. The layers request is the slowest single step on every face,
because `wfb.draw.layers` paints each element twice (on black and on
white, for the matte).

## 3. Measured: how far a rule-free redraw gets

**Table A** (`probe.py a`): what the browser would have to draw. Over the
29 faces there are **1 804 ops of 14 kinds**:
- `color`: 512;
- `drawLine`: 375;
- `text`: 223;
- `pen`: 210;
- `fillPolygon`: 164;
- `fillCircle`: 103;
- `fillRectangle`: 102;
- `arc`: 60;
- `glyph`: 28;
- `drawCircle`: 15;
- `fillRoundedRectangle`: 6;
- `fillEllipse`: 3;
- `drawRoundedRectangle`, `drawRectangle`, `drawEllipse`: 1 each.

The 223 text ops split three ways:
- baked fonts: 50;
- system fonts: 89;
- vector fonts: 84, all in three faces (`features/outline`,
  `features/vector-text`, `trail-utility`).

The JSON is **214 KB** against **957 KB** for the layer PNGs the editor
fetches today. Building it costs **1–23 ms** per face, a small share of
the layers request. VERIFIED.

**Table C** (`probe.py c`): for every size, radius and angle handle in the
corpus, the probe does three things:
1. takes the element's JSON before;
2. runs the real edit through `wfb.edit` (`resize` by 6 px, or `turn` by
   12°) and places the result;
3. compares the JSON after with the JSON before, number by number.

A drag is **predictable** when the op list keeps its shape and the only
numbers that change are:
- the handle's own `Layout` constant (`_WIDTH`, `_HEIGHT`, `_RADIUS`,
  `_START`, `_SWEEP`);
- for a centred or right-aligned box, its `_X`/`_Y`, shifted by the gain
  the handle already reports.

| Handle | Predictable | Not, and why |
|---|---:|---|
| `size.width` | 55 | 12 values computed from the width (a graph's series re-sampled, a bar's fill); 5 other constants (an ellipse's `RX`, a polar element's `CX`) |
| `size.height` | 61 | 6 computed; 5 other constants |
| `radius` | 38 | 5 other constants (`CX`/`CY` of an element placed by its edge) |
| `start_angle` | 0 | 17: the arc's `drawArc` call is computed from the angle by `WfbArc.drawSpan`'s rounding |
| `sweep` | 0 | 17: the same |
| **total** | **154 / 226** | 72 |

**Corrected in building it (plan 28 slice 3).** This table counted a
centred box as predictable whenever only its own size and its `_X`/`_Y`
changed, without checking by how much `_X`/`_Y` moved. A box's edges are
rounded one by one, half to even, about a centre that is usually
fractional (`Box.rounded`). So a centred box's new `_X` depends on that
fraction, which the JSON does not carry, and a drag by an odd number of
pixels moves it unpredictably. A test that compares the drawn result,
not the constants' names, proves 63 of 304 handles exact
(`tests/test_studio_raster.py`). Declaring centred boxes live as well
(183 handles) fails it on odd drags.

VERIFIED, with that correction. Two findings follow:
- **The arc misses are one function.** `barrel.draw_span` is already
  transcribed and sweep-tested in Python (`tests/test_draw_barrel.py`).
  A JavaScript twin held to the same sweep makes all 34 predictable:
  **188/226**. That is a barrel twin, not a rule, the same standing the
  evaluator's own transcriptions have.
- **The rest are derived geometry:** alignment of a polar or
  edge-anchored element, an ellipse's half-axes, a series sampled to its
  width. Recomputing them in the browser would be the second layout
  engine research 27 §5.3 set out to avoid. They keep today's outline,
  and the release corrects them.

**The browser must also know which constant a handle changes.** Today it
would have to guess from the element id and the key's suffix. The server
knows the name, so each handle should carry it (`"const": "CLOCK_WIDTH"`).

## 4. How the browser draws: the options

The contract already exists. `jsonform.rasterise` paints the JSON with
plain Pillow calls, and `tests/test_draw_layers.py` holds it pixel-equal
to the evaluator for every lowered element. A browser renderer is a fourth
reader of the same JSON.

| | **A. Canvas 2D** | **B. JS software rasteriser** | **C. Pyodide** |
|---|---|---|---|
| what | `ctx.arc`, `fill`, `drawImage` | Pillow's `ImageDraw` primitives reimplemented into an `ImageData` | CPython + Pillow in WebAssembly, running `wfb.draw` itself |
| pixels | anti-aliased paths; no switch turns that off for shapes. Approximate | identical to `jsonform.rasterise` by construction of the test | identical by construction |
| testable without a browser | no (Node has no canvas) | **yes**: pure functions on byte arrays, run in Node against the Python reference over the corpus, like `hit.js`/`snap.js` today | partly |
| size, start-up | none | small (14 ops) | about 10 MB vendored, seconds to start (UNVERIFIED for this Pillow and Python) |
| new upkeep | small, drifts silently | a third rasteriser, held by a test | a second runtime and its packaging; fits the no-build-step rule only as prebuilt files |

**Recommendation: B for shapes, server tiles for text.**
- **Text:**
  - A baked font is already a sheet: the browser blits its tiles, which
    is exact (`paste_glyph` is a tinted paste).
  - A system font is drawn glyph by glyph at whole-pixel pen positions
    (`Renderer._draw_system_line`), so a tile of each glyph, rendered once
    by the server, reproduces it exactly.
  - A rotated or curved vector run is rendered large, rotated and
    downsampled (`_paste_rotated_run`), which only Pillow reproduces. Its
    tile is the server's image of the run: exact while it moves, and
    redrawn on release when its radius or angle changes.
- **Pillow's algorithms are the work.** The primitives that matter are:
  - the ellipse (filled, and outlined with a width);
  - polygon fill;
  - a wide line;
  - an arc with a width;
  - the rounded rectangle.

  How much of Pillow's `_imaging` drawing code that is, and how faithfully
  it can be followed, is UNVERIFIED. It is the first measurement of a
  slice, done against the Node contract test, op by op. The project pins
  `pillow>=10` and runs 12.3.0, so a Pillow upgrade that changes a
  primitive turns that test red. That is the right failure.
- **It models Pillow, not the watch.** Garmin's own circles and rounded
  corners differ from Pillow's (`docs/limitations.md`). The browser renderer
  inherits the preview's model, which the user chose to keep.

## 5. What it would change in the editor

1. **Layers come as JSON plus tiles, rasterised in the browser.** The
   layers request stops painting every element twice, and hit-testing by
   alpha works the moment the frame arrives. An element no lowering covers
   (none today) or a vector run keeps a server image.
2. **A resize or angle draws the element itself**, not its outline, for
   the 83 % of handles §3 predicts. The others keep the outline.
3. **On release, the predicted result stays on screen** until the frame
   replaces it, as a move's does today. The wait is still the load
   (table D), but the author no longer watches an outline jump.
4. **The frame stays the server's.** The whole-frame steps (palette
   quantising, the bezel and AOD masks, the skin) and the authoritative
   picture remain `wfb.preview.render`. The browser composes only while
   the server's answer is on its way.

Slices, each proven before the next:
1. the JS rasteriser and its Node contract test over every lowered element
   in the corpus, with tiles for text;
2. layers from JSON in the canvas, with the PNG layers kept for vector
   runs;
3. handles carrying their constant, the `drawSpan` twin, live resize and
   turn, and predicted results held through the release.

## 6. Not this renderer: making the load cheaper

The release's own cost is parse plus schema: 214 of 227 ms on the
showcase. The browser renderer only hides it. Reducing it is a separate
investigation:
- validating only the edited element's schema branch, which research 26
  §7 named and did not design;
- a faster YAML parse for the gate's check;
- skipping a full reload when a patch changes one scalar.

Each touches the gate's guarantee that a refused edit never lands, so each
needs its own evidence. None is proposed here.

## 7. Decisions for the user

| # | Decision | Options | Recommendation |
|---|---|---|---|
| R1 | How the browser draws shapes | A Canvas 2D · B JS software rasteriser · C Pyodide | **B**: pixel-tested in Node against the existing contract; small; no new runtime |
| R2 | Text | browser fonts · server glyph tiles | **server tiles** (exact for baked and system fonts); a vector run as one server image |
| R3 | Scope | layers only · layers + live handles · also the whole frame | **layers + live handles** (§5's three slices); the frame stays the server's |
| R4 | The load (§6) | research it now · later · never | **later**: the renderer hides it; measure again once the editor draws locally |

**Decided by the user, 2026-10-03: R1–R4 as recommended.**
- R1: a JavaScript software rasteriser of Pillow's primitives.
- R2: server glyph tiles for text, and a vector run as one server image.
- R3: layers plus live handles; the frame stays the server's.
- R4: the load is researched later.

Being decided, this became plan 28 (`docs/plans/28-browser-renderer.md`), with §5's three slices after a first one that measures the Pillow port.

---

## Sources

- Research 27 §5.3–§5.4 (the three backends, layers), research 28 §4, §8
  (the release round trip, the postponed redraw), research 26 §7
  (incremental validation).
- `wfb/draw/jsonform.py` (`to_json`, `rasterise`), `wfb/draw/layers.py`
  (`layers`, the two-ground matte), `wfb/draw/barrel.py` (`draw_span`),
  `wfb/preview.py` (`Renderer.draw_text`, `_draw_system_line`,
  `paste_glyph`, `draw_vector_text`, `_paste_rotated_run`),
  `wfb/studio/drag.py` (`handles`, `gain`), `wfb/studio/document.py`
  (`frame`, `layers`, `drag`), `wfb/studio/static/canvas.js`,
  `wfb/build.py` (`load`: parse, schema, lower, desugar, IR),
  `tests/test_draw_layers.py`, `tests/test_draw_barrel.py`.
- Probe: `docs/research/probes/browser-renderer/` (`probe.py`,
  `results.txt`).
