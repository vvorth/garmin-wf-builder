# 28 — A browser renderer for `wfb studio`

**Status: accepted (2026-10-03); B1–B5 decided as recommended the same
day; slices 0–2 done, 3 next. Building it was decided by the user on
2026-10-03 (research 29 §7, R1–R4 as recommended).** Delete this file once every slice has shipped (`docs/CLAUDE.md`).

Research:
- `docs/research/29-browser-renderer.md`: the three waits, the
  measurements, the options;
- `docs/research/27-draw-program.md` §5.3: the JSON form as a backend;
- `docs/research/28-editor-open-questions.md` §8: why the browser half
  was postponed.

In short:

* **The browser draws the layers itself**, from the JSON form
  (`wfb.draw.jsonform`) plus glyph tiles from the server. It no longer
  fetches one PNG per element. Hit-testing by alpha and a move's moving
  image are ready as soon as the frame arrives.
* **A resize or an angle drag draws the element itself**, not its
  outline: the element's ops are redrawn with the handle's `Layout`
  constants changed. Only a handle proven to predict the server exactly
  does this. The others keep the outline.
* **On release, the predicted picture stays** until the server's frame
  replaces it, as a move's already does.
* **The rasteriser is JavaScript reproducing Pillow's primitives** into a
  byte array (R1). Node holds it pixel-equal to `jsonform.rasterise`
  over the corpus, with no browser.
* **Text is placed by the server and blitted by the browser** (R2). Every
  glyph arrives as a tile with its offset from the text's anchor:
  - baked, system and `.cft` glyphs are exact;
  - a rotated or curved vector run arrives as one image, moved as a whole.
* **The frame stays the server's** (R3): palette, masks, skin and the
  authoritative picture are `wfb.preview.render`'s.
* **Nothing on the watch side changes**, and nothing in `wfb build`:
  `tools/snapshot.py` stays unchanged at every slice.
* **The release's own wait**, the server's parse plus schema of the
  edited text, is not addressed (R4). It is hidden, not removed.

## 1. Decisions

### Decided

- **R1–R4 (research 29 §7, user, 2026-10-03):** a JS software rasteriser
  of Pillow's primitives; server glyph tiles for text, and a vector run as
  one server image; layers plus live handles, the frame staying the
  server's; the load researched later.

- **B1–B5 accepted as recommended (2026-10-03).**
  - B1: the server lays out every text op (`run`).
  - B2: a layer with an op outside the proven set travels as a PNG.
  - B3: kinds declare handle coefficients; a corpus test proves them.
  - B4: the contract test fails without Node; `setup-env.sh` checks it.
  - B5: Pillow's licence ships beside the port.

  The options as they were weighed:

- **B1: where text is laid out.**
  - **A (recommended):** the server lays out every text op. The JSON's
    `text` op gains a `run`: the glyphs as tiles, each with its offset
    from the anchor at the frame's scale, computed by the renderer's own
    placement (`draw_text`, `_draw_system_line`, `_draw_bitmap_line`). The
    anchor stays a named constant, so a moved text is still exact, and the
    browser has no alignment rule.
  - **B:** port `draw_text`'s placement to JavaScript.

  A keeps the browser rule-free (research 27 §5.3), and a text has no
  handle that changes its layout.
- **B2: what happens to an op the browser cannot draw exactly.**
  - **A (recommended):** per layer. A layer whose ops are all in the
    browser's proven set travels as JSON; any other layer travels as its
    PNG, as today. The proven set is one list, shared by the server and a
    test.
  - **B:** per op, mixing drawn ops with server images inside one layer.

  A lets the slices land op by op, and never mixes two rasterisations in
  one element.
- **B3: which handles draw live.**
  - **A (recommended):** each kind declares, per handle key, the
    `Layout` constants the handle moves and by how much per dragged pixel
    (`{"CLOCK_WIDTH": 2, "CLOCK_X": -1}`), or that it sets an angle. A
    handle with a declaration is `live`. A corpus test then proves that
    every live handle predicts the server's JSON exactly after a real
    edit (research 29 table C, made a test).
  - **B:** guess from the constant's name in the browser.

  A turns research 29's 154/226 into a checked claim, and it can grow
  only with proof: an ellipse's `RX` at half the width is one more
  coefficient, not a rule.
- **B4: Node for the contract test.**
  - **A (recommended):** the rasteriser's contract test **fails** when
    Node is missing, naming how to install it, and `tools/setup-env.sh`
    checks for Node. It is the only guard on a third rasteriser, and a
    skip once turned the goldens off silently (`tests/CLAUDE.md`).
  - **B:** skip it, as `test_studio_frontend.py` does today.
- **B5: Pillow's licence.** The JavaScript follows Pillow's own drawing
  algorithms, which makes it a derived work.
  - **A (recommended):** Pillow's licence text (MIT-CMU) ships beside it
    in `wfb/studio/static/vendor/LICENSES-pillow`, and the module header
    names the Pillow version it follows.

## 2. Shape

- `wfb/studio/static/raster.js`: pure functions on
  `{width, height, data: Uint8ClampedArray}`, with no DOM, for Node:
  - `drawOps(im, ops, tiles, scale)`, one branch per op;
  - `drawSpan` twin;
  - Pillow's mask paste, with its integer rounding.
- `wfb/draw/jsonform.py`:
  - `text` and `glyph` ops gain `run` (B1); a rotated or curved vector
    run is one RGBA tile in it;
  - `rasterise` (the Python reference) pastes runs, so the contract
    covers what the browser reads;
  - `BROWSER_OPS`, the proven set (B2).
- `wfb/studio/document.py`:
  - the frame response carries each layer as JSON or as a PNG
    (fallback), plus the frame's **packed tiles** embedded
    (`Tiles.pack`: raw RGBA, zlib, with an index), cached per version,
    device, scale and frame switches;
  - `Document.layers` and its endpoint go.
- `wfb/kinds/*`: per handle key, the constant coefficients (B3).
  `wfb/studio/drag.py` puts them on the handle with `live: true`.
- `wfb/studio/static/canvas.js`: layers rasterised locally, hit-testing
  on them, live resize and turn, the prediction held through the
  release.

## 3. Slices

Each slice ships with:
- the fast suite and `mypy --strict` green;
- `tools/snapshot.py` unchanged;
- the slice's own measurement written down in this plan.

Every new guard is driven red.

### Slice 0 — Pillow's primitives in JavaScript: done

Built as below. `wfb/studio/static/raster.js` (550 lines) follows Pillow
12.3.0's `ImageDraw.py` and `src/libImaging/Draw.c`, which was fetched
from the release's tag (`raw.githubusercontent.com`, reachable from the
container), with the argument conversion of `src/_imaging.c`. Pillow's
licence is `vendor/LICENSES-pillow` (B5).

| Op (`ImageDraw`) | Pillow routines | `raster.js` |
|---|---|---|
| `rectangle` fill / outline | `ImagingDrawRectangle`, `hline32`, `line32` | bindings + 25 lines |
| `line`, width 1 / wider | `line32` + `ImagingDrawPoint` / `ImagingDrawWideLine` into `polygon_generic` | 40 + 15 |
| `polygon` fill | `ImagingDrawPolygon`, `add_edge`, `polygon_generic` (the scanline, with its corner fix) | 90 |
| `ellipse` fill / outline | `quarter_*`, `ellipse_*` (integer Bresenham on a step-2 grid), `ellipseNew` | 70 |
| `arc` | `normalize_angles`, `arc_init`, the clip tree, `clipEllipseNew` | 140 |
| `rounded_rectangle` | Python composition of filled pies (`pie_init`), arcs and rectangles | 65 |

What a faithful port has to keep, each found in the C and each mattering:
- `(int)` truncates toward zero;
- the scanline's and the angles' C `float`s round to 32 bits after
  every operation;
- `ROUND_UP`/`ROUND_DOWN` and `lround` round half away from zero, while
  Python's `round()` in `rounded_rectangle` rounds half to even;
- the binding hands arc angles over as `float`.

The integer ellipse's 64-bit products stay exact in a double while the
axes are under 2^13 (a 454 px screen at 3× is 2 724 on the step-2 grid).

**Measured:**
- **Every op is exact.** `tests/test_studio_raster.py` draws each op with
  Pillow and with `raster.js` on the same canvas and compares the RGB
  bytes:
  - a seeded sweep of 2 400 cases: sizes, widths 1–8, whole, half,
    fractional and off-canvas coordinates, every kind of angle;
  - every ellipse up to 31 × 31 filled and ringed, and 600 arcs at
    fractional angles;
  - 90 large shapes on a 1 362 px canvas (a 454 px screen at 3×).

  All equal. `BROWSER_OPS` therefore starts with every shape op; only
  `text` and `glyph` wait for slice 1.
- **The sweep catches a broken port.** Ten deliberate bugs were planted
  one at a time. Seven were caught:
  - `(int)` as floor: 313 cases;
  - Python's `round()` taken as half up: 63;
  - the polygon corner fix skipped: 32;
  - the scanline in doubles: 19;
  - its slope in doubles: 5;
  - the ellipse's tie-break: 14;
  - arc angles in doubles: 1.

  The three that changed no pixel replace `ROUND_UP` or `lround` with
  `Math.round`, or round the wide line's length to 32 bits. They differ
  only at exact negative halves (left of the canvas for the polygon, an
  exact half from a sine for the arc's clip), so they are drawn the same
  in practice.
- **On the corpus:** `docs/research/probes/browser-renderer/raster_speed.py`
  (results beside it) draws every shape-only layer of every example face
  on fr955 at 2× through `jsonform.rasterise`'s op mapping. **190 of 190
  equal `rasterise` byte for byte.** Node takes **1–10 ms a face** for all
  of them, and **at most 6.6 ms for one layer** (`features/progress`),
  inside the 16 ms target.

Node is checked by `tools/setup-env.sh`, and the test fails without it
(B4).

### Slice 1 — glyph tiles and placed text: done

Built as below:
- **The renderer records instead of painting** while `Renderer.stamps` is
  a list (`wfb.preview.Stamp`). Every place text or an icon reaches the
  canvas records what it would paste:
  - `paste_glyph`: a baked glyph's sheet crop, scaled as it is pasted;
  - `_draw_system_line`: per character, `ImageDraw.text`'s own steps
    (`getmask2` for the pen's fraction, placed at its integer part plus
    the mask's offset);
  - `_draw_bitmap_line`: a `.cft` cell;
  - `_paste_rotated_run`: an angled or radial vector run's RGBA image;
  - `_mark_extent`: the outline of text with no glyphs, as a `box`.

  With `stamps` unset, nothing paints differently.
- **`to_json`'s `text` and `glyph` ops carry a `run`** (B1): the stamps,
  each a tile id at a whole-pixel offset from the op's anchor,
  `(floor(x * scale), floor(y * scale))`, so a moved text is a moved
  anchor. They are recorded by drawing the op exactly as `rasterise` used
  to. A rotated vector run is a tile like any other, so no separate
  `image` op was needed.
- **`jsonform.Tiles`**: one store per frame (`wfb.draw.layers` shares it
  across the layers), each tile kept once.
- **A decision made in building it** (amending §2's "one PNG"): `pack()`
  writes the tiles as raw RGBA bytes, zlib-compressed, with an index, not
  as a PNG. A browser canvas premultiplies alpha, which would change a
  translucent RGBA tile's colour; the raw bytes inflate with the
  browser's own `DecompressionStream`.
- **`jsonform.rasterise(ops, tiles, renderer)`** pastes runs and lays out
  nothing. `BROWSER_OPS` lists every op.
- **`raster.js`** gains `paste` (Pillow's mask blend, `DIV255` and all),
  `unpackTiles`, and `drawOps`, the `rasterise` mapping. Its `OPS` must
  equal `BROWSER_OPS`.

Proven:
- **Nothing else moved:** `tools/snapshot.py` against a baseline saved
  from the slice's starting commit: 553 of 553 cases unchanged. The fast
  suite and `mypy --strict` are green.
- **The server's placement:** `tests/test_draw_layers.py`'s contract,
  run over every example face (awake and AOD), still holds with
  `rasterise` pasting runs: 72/72. Shifting every tile one pixel fails 26
  faces.
- **The browser equals the reference:** `tests/test_studio_raster.py`.
  For every lowered element of every example face on fenix8solar47mm and
  fr955, awake and AOD, over black and over white, `drawOps` equals
  `rasterise` byte for byte: 655 elements in the awake frames alone, with
  984 mask and 351 RGBA stamps. Every op the corpus emits is in
  `BROWSER_OPS`. A blend without its rounding term fails 26 faces.
- **What the corpus never shows**, in a synthetic run: tiles straddling
  every edge and corner, translucent RGBA tiles, and a `box`. Each of the
  four clip edges, moved one pixel, fails it; a first version without the
  edge tiles missed exactly that, by chance of its seed.

**Measured** (`docs/research/probes/browser-renderer/tiles.py`, results
beside it; fr955 at 2×):
- **329 of 330 layers travel as JSON.** The one that does not is
  `features/rings`' outlined group ring, which has no ops.
- **Tiles per face:** 0–64 distinct, 0–41 KB packed (base64), packed in
  under 15 ms. The largest is `features/vector-text`: 55 tiles, mostly
  rotated runs.
- **Payload:** the corpus's ops plus tiles come to 417 KB (ops 225 KB,
  tiles 192 KB) against 957 KB of the layer PNGs the editor fetches today.

### Slice 2 — layers from JSON in the canvas: done

Built as below:
- **The frame carries its layers.** `Document.frame` adds every layer in
  draw order: its JSON ops, or, for a layer with an op outside
  `BROWSER_OPS` (today only an outlined group's ring), its PNG cropped to
  its ink with its origin. The frame's packed tiles travel with it.
  - `wfb.draw.layers(..., paint_all=False)` paints only those fallback
    layers.
  - `Document.layers` and its endpoint are gone.
  - The tiles are embedded in the frame's JSON (base64) rather than
    fetched from a URL, so a frame and its tiles can never belong to
    different versions.
- **`raster.js`** adds:
  - `inflateTiles`, the platform's `DecompressionStream`, which Node has
    too;
  - `inkOf`: a layer drawn on black and on white, with ink where the
    difference's luma falls short of 255, the matte's own coverage rule;
  - `translateOps`, by the `Dc` call signatures;
  - `composite`, for a fallback PNG.
- **The canvas** prepares a frame's layers when it arrives: the tiles
  inflated, a fallback PNG decoded.
  - **Hit-testing reads ink.** A layer's ink is worked out the first time
    a press lands in its box.
  - **A move redraws the whole face** from the layers' ops, the moving
    ones translated, instead of compositing per-layer images (a decision
    made in building it, amending "one image per layer"). That draws the
    moved geometry as the server will, where shifting finished pixels
    only approximated it, and it needs no colour matte in the browser.
  - `app.js` no longer fetches layers.

Proven:
- **Ink equals the server's layer alpha.** `inkOf` equals the alpha of
  `wfb.draw.layers`' own matted image, pixel for pixel, for every JSON
  layer of every example face. A threshold off by one fails 26 faces. A
  per-channel rule fails none: the two agree in practice, and luma is the
  matte's own rule.
- **A move draws the server's move.** Across ten faces covering every
  kind, each element's ops translated by (+5, −3) were checked against the
  server's JSON after the real `wfb.edit.move`, landed. Every number is
  within one device pixel (a run's offsets within two frame pixels), and
  at least 85 % draw identically: over the whole corpus
  (`docs/research/probes/browser-renderer/translate.py`), 293 of 319.
  The rest are `%` and `%r` boxes the layout re-rounds where they land
  (an edge 1 px off, a size 1 px larger). Only the layout engine knows
  that rounding, and the release corrects it. Not shifting text, or
  shifting a circle's radius, fails the test.
- **Checked in a DOM** (jsdom against a live server, a fresh copy of the
  face per run):
  - on `features/shapes`, a point inside `outer_arc`'s box but outside
    its circle, where a pick by box answers the arc, selects the
    background;
  - a press on the arc's rim selects the arc;
  - a move redraws the 520 × 520 frame from ops while the pointer is
    down;
  - after the release, the same point again selects by ink;
  - on `features/rings`, the ring layer arrives as a PNG and a move
    composites it;
  - no page errors.

  With ink-picking switched off, the rim selects `accent_arc`. A first
  version of the check reused one face across runs, and the moves it made
  had taken the background away from the test point. The browser itself
  is checked by hand.
- The fast suite and `mypy --strict` are green.

**Measured** (`docs/research/probes/browser-renderer/frame_cost.py`,
results beside it; each face's first target at 2×):
- **The server's frame**, now carrying its layers: 12–307 ms, against
  78–661 ms for the frame plus the layers request before. The showcase
  is 40 ms against 261, `trail-utility` 43 against 333.
- **Bytes per frame:** 27–74 KB, against 43–101 KB before.
- **In the browser (Node):**
  - inflating the tiles: 18–33 ms, once per frame;
  - **drawing the whole face for a move: 3–5 ms**, so a pointer move
    redraws well inside a 60 Hz frame;
  - one layer's ink: at most 9.2 ms, worked out only for the layers a
    press lands in.

### Slice 3 — live handles

- Kinds declare handle coefficients (B3). `drag.handles` adds `consts`
  and `live`.
- The `drawSpan` twin in `raster.js`, swept in Node over every
  half-degree start against `barrel.draw_span`, the way
  `tests/test_draw_barrel.py` sweeps the Python one.
- **The corpus test** (research 29 table C, made a test). For every
  handle in the examples:
  - a live one's prediction must equal the server's JSON after the real
    edit;
  - the count of live handles is recorded.

  Target: at least research 29's 188/226.
- The canvas redraws the dragged layer from its ops with the constants
  moved during a live resize or turn, and keeps the prediction on screen
  through the release. A handle that is not live keeps the outline.
- **Checked in a DOM:** a width drag draws the box grown, and an arc's
  sweep drag draws the arc turned. Both are held until the frame comes.

### Slice 4 — close-out

- `docs/guide/studio.md`: a resize and an angle draw live; what still
  shows an outline.
- `docs/limitations.md` §2: the browser models Pillow, not the watch, as
  the preview does; vector runs move as images.
- `docs/lore/roadmap.md`, research 29's status, the root `CLAUDE.md` §6
  if it names the editor's drawing.
- Delete this plan; add its row to `docs/plans/README.md`.

## 4. Tests, beyond each slice's own

- **The contract** (slice 1 on): `raster.js` equals `jsonform.rasterise`
  for every element whose ops are in `BROWSER_OPS`, over the corpus, on
  two grounds. That makes it pixel-equal to the evaluator, which
  `tests/test_draw_layers.py` already holds.
- **`BROWSER_OPS` is honest:** a test feeds every op name in it to
  `raster.js`, and every op name `to_json` can emit is either in it or
  named as a fallback.
- **Live handles are honest** (slice 3): the corpus test above.
- **No build change:** `tools/snapshot.py` at every slice.

## 5. Risks

- **Pillow's algorithms may resist a faithful port.** Slice 0 measures
  this before anything depends on it. The per-layer fallback (B2) means
  a hard op costs coverage, never correctness.
- **A Pillow upgrade can change a primitive.** The contract test turns
  red, which is the intended failure. The module header names the version
  it follows.
- **Speed.** A software rasteriser at 2× on a 454 px screen covers up to
  about 0.8 M pixels a layer. Each layer is drawn only in its ink box, and
  slice 0 measures the time.
- **A third rasteriser to keep.** It reads only the JSON, holds no rule,
  and has one contract test over the whole corpus. When a new op enters
  the program, the honesty test names it as a fallback until
  `raster.js` learns it.
- **It models Pillow, not the watch** (`docs/limitations.md`), the choice
  the user made for the preview.
