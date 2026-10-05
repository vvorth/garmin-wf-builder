# 32 — The whole stack in TypeScript

**Question (user, 2026-10-05).** Research 31 recommended running the
existing Python in the browser (Pyodide), and its probe passed. The user
rejected that as the easy route: it keeps Pillow and FreeType as the model
of the watch. Research instead the whole stack in TypeScript/JavaScript,
with font rendering and vector drawing native rather than Pillow's.

**Status (2026-10-05): every decision taken (§7, §8); planned as plan 31
(`docs/plans/31-typescript-migration.md`).** The last Python-server state
is tagged `v0.3`.

**Short answer.**

1. **Every dependency has a TypeScript replacement, and each was measured
   against the one it replaces** (§2). VERIFIED.
   - **YAML:** the `yaml` package gives the same key and value start
     positions as ruamel on all 6 821 entries of the 31 example files, and
     the same data on all 31. It is 8× faster.
   - **Schema:** Ajv agrees with `jsonschema` on all 1 230 valid and
     mutated faces, with the same leaf errors on 1 229. It is 36× faster.
2. **Leaving Pillow makes shapes *more* like the watch, not less** (§3).
   The model is the shape's exact geometry, with Garmin's `(x, y)` taken as
   a pixel's centre, and ink on every pixel at least half covered. Against
   the simulator capture from the earlier ring-on-device probe, it differs
   by **24 px** drawn with Skia (Chrome's canvas engine) and **72 px** in
   pure JS, against **914 px for Pillow**. VERIFIED on one capture, so §3
   says how far that goes.
3. **Canvas anti-aliasing is the wrong model for the watch.** Drawn plainly,
   a canvas differs from the capture by 2 102–2 523 px, worse than Pillow.
   "Native" therefore means a native *coverage* computation followed by
   Garmin's rule, not the canvas's own soft edges (§3).
4. **Fonts can be baked without FreeType, but not to Pillow's exact bits**
   (§4):
   - line metrics match on all 18 bakes, and advances on 1 572 of 1 576
     glyphs;
   - a 1-bit glyph whose box agrees differs on **0.6 %** of its ink;
   - but **1 glyph in 10 lands a pixel apart**, from rounding of the ink
     box, and anti-aliased greys differ more.

   A port therefore changes every baked sheet once. There is no "right"
   answer to match: the watch draws whatever sheet was baked.
5. **What must be decided is less the language than three rules** (§6):
   - **determinism:** a sheet that ships in the `.prg` must bake the same
     in every browser and on the server, so canvas text and paths are not
     enough for anything that ships;
   - **the oracle during migration:** port with Python as the reference,
     stage by stage;
   - **the build step:** TypeScript needs one.
6. **Recommendation:**
   - TypeScript throughout, built with esbuild.
   - One package that runs in the browser and in Node.
   - Its own deterministic rasteriser for shapes and glyph outlines, held
     to the simulator rather than to Pillow.
   - Canvas only for the editor's chrome and for interactive drawing.
   - Ported **stage by stage, with Python as the oracle** (§6), so every
     step is a measured equality or a deliberate, recorded change.

Probe: `docs/research/probes/typescript-stack/` (five `.mjs` probes, their
Python dumpers, and `results.txt`). Everything ran in Node 22 in this
container. **No real browser ran:** Chromium could not be downloaded here,
so Skia, through `@napi-rs/canvas`, stands in for Chrome's canvas.
**Safari's CoreGraphics and Firefox were not measured.**

---

## 1. What moves, and what each part needs

`wfb/` is 46 100 lines of Python, held by 53 000 lines of tests. By what
it depends on:

| Part | Lines (approx.) | Depends on | TypeScript route |
|---|---:|---|---|
| YAML with spans, the patch engine (`yamlsrc.py`, `wfb/edit/`) | 4 000 | ruamel | `yaml` (§2.1) |
| schema reporting (`validate.py`) | 950 | jsonschema | Ajv (§2.2); the error shaping is ported, not replaced |
| lower, desugar, IR, catalog, expressions, units, palette, availability | 9 000 | none (pure logic) | a straight port |
| layout, lint | 4 400 | font metrics; device files | port; device XML read by `DOMParser`, or digested to JSON by the server |
| element kinds (lower *and* emit halves) | 5 100 | none | port |
| draw program, evaluator, `jsonform` | 2 700 | none (pure logic) | port |
| preview, layers, AOD mask, visible area, icons | 3 400 | **Pillow** | own rasteriser (§3) and image ops |
| font baking, `.cft` decoding, stand-ins | 1 800 | **Pillow, FreeType, fontTools** | `opentype.js`/`fontkit` outlines plus own rasteriser (§4); `.cft` is plain binary parsing |
| codegen: Monkey C, resources, manifest, jungle | 6 400 | none (strings) | port, held byte-identical (`tools/snapshot.py`) |
| `monkeyc`, `--build-stats`, simulate | 800 | **Java SDK** (subprocess) | Node `child_process`, server only |
| studio server (sessions, store, bundle) | 3 500 | Starlette | the browser's IndexedDB plus `fflate` for the `.zip`; a small Node server |
| CLI | 1 600 | argparse | Node CLI |

**What does not move:**
- `runtime-lib/` (1 400 lines of Monkey C, used as it is);
- the JSON Schema, which is already language-neutral and normative;
- the examples, docs, device files and the studio's existing JS (4 700
  lines, already in the browser);
- `tools/` (2 400 lines of Python), which can stay as research tooling.

## 2. Parsing and validation: measured equal

### 2.1 YAML: `yaml` 2.9.1 against ruamel

`yaml.mjs` on every example YAML file (31):

| Check | Result |
|---|---|
| lossless round trip through the CST | **31 / 31** byte-identical |
| `toString()` round trip | 4 / 31: it re-serialises, moving comments and blank lines. The patch engine never re-serialises; it rewrites spans, so this does not matter |
| data equal to ruamel's | **31 / 31** |
| key start offsets | **6 821 / 6 821** |
| value start offsets | **6 821 / 6 821** |
| value end, as `SpanIndex.value_end` derives it | 6 810 / 6 821 |
| showcase parse | **13.5 ms** against 104 ms |

VERIFIED.
- **The 11 ends that differ** are all block values followed by a comment
  block, where ruamel's end mark swallows the comments and `yaml`'s
  `valueEnd` stops at the last value character. Neither is wrong.
  `SpanIndex` already has a rule for which comments belong to an entry,
  and a port restates that rule against `yaml`'s nodes and tests it on
  this corpus.
- **The parse is 8× faster.** That removes research 29's largest cost,
  the release wait, which is mostly parsing.

### 2.2 Schema: Ajv 8.20 (Draft 2020-12) against jsonschema

The probe uses 1 230 cases: each example face, plus 40 seeded mutations of
each (a type changed, a key removed, an unknown key added, a string
misspelt). They run through the published schema unchanged:

| Check | Result |
|---|---|
| valid or invalid agrees | **1 230 / 1 230** |
| leaf errors (path, keyword) equal, through `oneOf` context | 1 229 / 1 230 |
| every jsonschema leaf also reported by Ajv | **1 230 / 1 230** |
| total time | **1.0 s** against 37.6 s (≈ 36×) |

VERIFIED.
- **What is ported rather than replaced** is `validate.py`'s error shaping:
  choosing the `oneOf` branch the author meant, merging required-one-of,
  and naming unexpected keys.
- Ajv reports a flat list, not jsonschema's `context` tree, but every leaf
  carries its `schemaPath` (`…/oneOf/3/…`). The tree can be rebuilt from
  it, which is what the leaf comparison above did.

## 3. Shapes: the canvas, Pillow and the watch

The question "native drawing" raises is *native to what*. The watch draws
with Garmin's own rasteriser. Its circles and rounded corners differ from
Pillow's (`docs/limitations.md`, "Garmin's circles and rounded corners are
not Pillow's"). The one ground truth on file is the simulator capture of
`docs/research/probes/ring-on-device/` (fenix8solar47mm):
- circles, rectangles, rounded rectangles, gauge bars and filled circle
  parts;
- 20 element windows of 38×36 px.

`shapes.mjs` draws the same draw-program ops several ways. Each count is
the number of pixels that differ from the capture:

| Model | circle | rectangle | rounded | bar | part | **total** |
|---|---:|---:|---:|---:|---:|---:|
| **Pillow** (today's preview and `raster.js`) | 388 | 4 | 52 | 82 | 388 | **914** |
| canvas anti-aliased, as drawn (best of 4 conventions) | 816 | 16 | 299 | 155 | 816 | 2 102 |
| Skia coverage ≥ 50 %, `(x, y)` = pixel corner | 328 | 0 | 2 | 82 | 328 | 740 |
| **Skia coverage ≥ 50 %, `(x, y)` = pixel centre** | **11** | **0** | **2** | **0** | **11** | **24** |
| **pure JS, 16×16 samples ≥ 50 %, pixel centre** | 32 | 0 | 0 | 8 | 32 | **72** |

VERIFIED for this capture.

**What it shows:**
- **Garmin fills a shape's true geometry with a centre-of-pixel convention,
  then a half-coverage rule**, much as a textbook scan converter does. It
  does not use Pillow's integer ellipse.
- **Every element of the capture is within a few pixels under that model.**
  The gauge bars, which Pillow misses by 82 px, match exactly.
- **The canvas's own anti-aliased output is the worst model of all.**
  Soft edges are not what a MIP watch draws without `setAntiAlias`.

**How far it goes:**
- **One capture, one device, 20 windows, and 4 conventions tried**, the
  best one reported. The convention is principled (pixel centres) and not
  a fitted constant, but it has not been tested on a second capture.
  - Not yet checked: arcs (`drawArc` with a pen width), lines, polygons, and
    `setAntiAlias(true)` drawing.
  - Each needs a probe face and a simulator capture on the host. The
    ring-on-device probe shows how.
- **Exact 50 % coverage is a tie.** Skia, CoreGraphics and a JS sampler
  break it differently, which is the 24 against 72. Anything that ships
  must break it the same way everywhere, so the rasteriser must be our own
  code (§6, F2). An exact-area (analytic) coverage computation is the
  candidate to close the 24-to-72 gap. UNVERIFIED.

**`antialias: true` is the one place a canvas-like model may fit.** On the
watch it is `Dc.setAntiAlias`. What Garmin's anti-aliased edge looks like
is unmeasured, since the preview never modelled it
(`docs/limitations.md`). A coverage rasteriser yields the grey level for
free, so this gap could close with one capture.

## 4. Fonts: baking without Pillow and FreeType

A baked font is part of the build. Its sheet ships in the `.prg`, and its
advances are layout constants in the generated code. Today `bmfont.bake`
works like this:
1. render each glyph with FreeType at 16× (`SUPERSAMPLE`);
2. crop to the ink;
3. box-average down;
4. threshold at 128 for 1-bit fonts.

`fonts.mjs` re-bakes 18 combinations of font, size and anti-aliasing:
- the fonts: ChivoMono Bold at 10/29/61/78 px, Questrial at 13/24 px,
  Dynalight (a script face) at 39 px, and 66 Nerd Fonts icons at 16/24 px;
- 1 576 glyphs in all;
- three ways, each against Pillow's sheets.

| Baker | aa | identical glyphs | same box and offsets | differing ink, all | … where the box agrees |
|---|---|---:|---:|---:|---:|
| outline (opentype.js) filled by Skia, Pillow's BOX transcribed | 1-bit | 390 / 788 | 713 | 2.00 % | **0.62 %** |
| outline, exact area average | 1-bit | 327 / 788 | 713 | 2.08 % | 0.72 % |
| **native `fillText`**, Pillow's BOX | 1-bit | 324 / 788 | 706 | 2.21 % | 0.73 % |
| outline, Pillow's BOX | AA | 288 / 788 | 713 | 9.76 % | 7.11 % |
| outline, area average | AA | 193 / 788 | 713 | 9.58 % | 6.90 % |
| native `fillText` | AA | 190 / 788 | 706 | 10.31 % | 7.47 % |

**Metrics:**
- line height and base are equal on **18 / 18** bakes (ceiled `hhea`
  ascender and descender, as FreeType rounds them);
- the advance, the linear advance rounded, is equal on **1 572 / 1 576**
  glyphs.

VERIFIED.

**What it shows:**
- **The bake is reproducible in JS to within edge pixels.** Where a glyph's
  box agrees, 1-bit shapes differ on 0.6 % of their ink.
- **The bigger difference is placement:** 75 of 788 glyphs (about 10 %) get
  a box or offset one pixel different. The ink box is found at 16× and
  rounded to pixels, so a 1/16 px difference in where the outline lands
  flips a rounding. Pillow's FreeType hints the outline even at 16× (the
  likely cause, UNVERIFIED), and an unhinted outline does not.
- **Anti-aliased sheets differ by more than 8 grey levels on about 7 % of
  ink** where the box agrees. That is the same edge effect seen in grey
  rather than in a threshold.
- **Native `fillText` gives the same answer as filling the outline
  ourselves**, within 0.1 %. The 16× supersample and box average erase most
  of what distinguishes one text engine from another. On macOS, CoreText
  hinting and dilation could matter more. UNVERIFIED.
- **Four advances differ.** These are FreeType's hinted advances against the
  linear ones. A design whose text crosses one of those glyphs gets a
  layout constant one pixel different after the port.

**Consequences:**
- **A port cannot keep today's sheets.** It changes every baked font once:
  about 10 % of glyphs move by a pixel, and edges change. That is a
  one-time, recorded golden change, not a regression. Nothing defines
  Pillow's sheet as correct; the watch shows what was baked.
- **What a port must keep is determinism.** The same face must give the
  same sheet in every browser and in Node, or a preview made in Safari and a
  build made on the server would ship different glyphs. That rules out
  `fillText` and canvas path fill **for baking**. They can still draw the
  editor's UI.
- **Speed:** the JS baker took 15 s for three full bakes of all 1 576
  glyphs, comparison included, against 16.4 s for Pillow's one. A face
  bakes only the glyphs it uses, tens of them, in well under a second.

**The other font paths:**
- **System fonts.** A `.cft` file is decoded by `wfb/fonts/cft.py` (416
  lines, struct parsing). A device `.ttf` scaled to the published metrics
  takes the same bake path as above. Both port directly.
- **Vector text (`face:`, rotated and curved).** Today it is rendered at 4×
  by Pillow, then rotated as an image and downsampled
  (`_paste_rotated_run`). With outlines in hand, the outline itself is
  rotated and then rasterised, which is exact. This is a fidelity gain,
  and the one place where leaving Pillow removes an approximation outright.

## 5. The server, the CLI and the editor

- **One package, two hosts.** The compiler is written once, as ES modules
  that run in the browser and in Node.
  - In the browser it runs inside a Web Worker. It uses `OffscreenCanvas`
    only where a canvas is used at all.
  - Node runs the CLI and the build server.
- **The server shrinks to:**
  - static files;
  - `GET /devices/<id>`: `compiler.json`, `simulator.json`, a digest of
    `api.debug.xml` with only the symbols `availability` asks about, and
    the skin;
  - `GET /fonts/<name>`;
  - `POST /build`. It takes the face bundle, runs the same compiler in
    Node, then `monkeyc`, and returns the `.prg` files and the
    `--build-stats` memory figures. Taking the face rather than generated
    Monkey C means the server compiles only code it generated itself.
- **The editor's state moves to the browser** (research 31's decision S2):
  - the journal and blobs live in IndexedDB;
  - the `.zip` is written with `fflate`;
  - sessions, claims, locks and the event stream go away.
- **The CLI becomes Node.** `wfb build`, `preview`, `simulate`, `fonts` and
  `doctor` keep their names. `tools/setup-env.sh` installs Node and the
  package in place of the venv.
- **The no-build-step rule** (research 26, decision D3) does not survive
  TypeScript, whose types must be stripped before a browser runs it. Either:
  - **TypeScript with esbuild**: one dev dependency, and a build in
    milliseconds. The editor's vendored modules stay as they are; or
  - **JavaScript with JSDoc types checked by `tsc --noEmit`**, which
    research 26 §8 already sketched. It keeps no build step, at the price of
    a noisier type syntax across about 40 000 lines.

## 6. Migrating

**The risk is not a library; it is the size.** About 40 000 lines and the
tests behind them, while the project keeps shipping features.

| Strategy | What it means | Pros | Cons |
|---|---|---|---|
| **M1. Rewrite, then switch** | build the TS compiler beside Python and switch when it is done | simple | the longest time with two compilers drifting; one big switch to trust |
| **M2. Stage by stage, Python as the oracle** (recommended) | port one pipeline stage at a time behind a JSON boundary, with a corpus test that compares its output with Python's, until the Python stage can be deleted | every step is measured; the project stays shippable; the stages already have JSON forms (the schema, `jsonform`, `tools/snapshot.py`) | a period with mixed stages; each boundary needs a serialised form |
| **M3. New features in TS only, old code left** | — | — | two compilers indefinitely: research 31's option B by another name |

**M2's order, each stage ending in a corpus equality or a recorded change:**
1. **Package skeleton.**
   - The TS package, esbuild, a test runner (`node:test` or Vitest).
   - Device loading from the server's digest.
   - A harness that runs Python and TS on the corpus and compares their
     JSON.
2. **Front end.** YAML spans, the patch engine, schema reporting, lower,
   desugar, IR, the catalogue and expressions.
   - Equality: the IR as JSON, the diagnostics' text and spans, and
     every patch's text.
3. **Layout.** Equality: every resolved constant per device (the
   `Layout` values), identical except where a baked font's advance changed
   (§4: 4 of 1 576).
4. **Fonts.** The deterministic outline rasteriser, the bake, `.cft`
   decoding and system-font stand-ins.
   - **Recorded change:** every sheet re-baselined once, with a pixel
     report per font.
5. **Draw and preview.**
   - The rasteriser for shapes, held to the simulator: the ring capture
     first, then new captures for arcs, lines, polygons and anti-aliasing.
   - The palette quantise, masks and skin, and `jsonform`.
   - **Recorded change:** every preview golden re-baselined against the new
     model, with the simulator-diff table as the evidence.
6. **Lint.** Equality: every diagnostic on the corpus. `aod-burn-in` and
   other measured lints change only where the preview's pixels did.
7. **Codegen.** Equality: **the generated project byte for byte**
   (`tools/snapshot.py`), except resources from step 4. This is the
   strongest guard, since it is what the watch runs.
8. **Server, CLI, editor.** `POST /build`, the Node CLI, and the editor
   calling the worker instead of the API.
9. **Delete Python.** Port or retire the tests, and update ADR 0001 (a
   dated amendment), `docs/development.md`, `docs/container.md` and the
   setup script.

**During M2:**
- **New compiler features wait, or are written TS-first** in a stage
  already ported.
- **The fast suite keeps both halves green until a stage is deleted.**
- **Re-baselines (steps 4–5) need the user's host:** simulator captures for
  each new shape model.

## 7. Decisions for the user

| # | Decision | Options | Recommendation |
|---|---|---|---|
| T1 | Go to TypeScript at all | yes · stay Python (research 31's C) | **yes**, if leaving Pillow is the goal: §3 shows that is a fidelity gain, not only a cost |
| T2 | The pixel model | reproduce Pillow (keep `raster.js`; FreeType has no faithful JS port) · model Garmin (coverage, pixel centre, half rule) | **model Garmin**, held to simulator captures |
| T3 | Rasteriser for anything that ships or is tested | the platform canvas (Skia, CoreGraphics) · our own TS rasteriser | **our own**: deterministic across browsers and Node. The canvas is for the editor's chrome and live drawing |
| T4 | Glyph outlines | `opentype.js` · `fontkit` · HarfBuzz (WebAssembly) for shaping | **`opentype.js` or `fontkit`** (no shaping is needed: one glyph per character, no kerning in BMFont output). Choose by `.otf`/CFF and variable-font coverage at step 4 |
| T5 | Language form | TypeScript + esbuild · JS + JSDoc + `tsc --noEmit` | **TypeScript + esbuild** (reverses D3; the editor's vendored modules are unaffected) |
| T6 | Migration | M1 rewrite · **M2 stage by stage, Python as oracle** · M3 new-only | **M2** |
| T7 | Before step 1 | start now · first more simulator captures (arcs, lines, polygons, `setAntiAlias`) | **captures first**: they decide T2 for the shapes not yet measured, and cost one host session |

**Decided by the user, 2026-10-05:**
- **T1:** yes, TypeScript.
- **T2:** yes, model Garmin. For early development, Pillow-based previews
  (today's goldens, and `raster.js`, which is already a Pillow-exact
  TypeScript-ready port of the shape primitives) are the initial baseline.
  The Garmin model replaces them as simulator captures arrive (§8).
- **T3:** yes, our own rasteriser.
- **T4:** first postponed outline work and anti-aliasing, then revised the
  same day. Nothing is postponed from the port, which keeps every corpus
  frame comparable:
  - `outline:` rings are ported exactly;
  - rotated and curved vector text rotates the glyph outlines and then
    rasterises them;
  - anti-aliasing has nothing to port, since the preview draws no
    anti-aliased primitive and anti-aliased sheets come with the bake.

  Only research into Garmin's own `setAntiAlias` and vector-text
  appearance waits for captures. Outlines come from `opentype.js`, behind
  one module.
- **T5:** option B, erasable-syntax TypeScript (§8.1).
- **T6:** yes, M2, stage by stage with Python as the oracle.
- **T7:** captures can come last (§8.2). Shapes are checked on the three
  verification devices **and `fenix847mm`**, the AMOLED fēnix 8 47/51 mm
  (one device definition, 454×454), whose resolution constrains a fit
  better. AMOLED is fitted on its own, not assumed to match MIP.

## 8. Follow-up: the build step, and what needs simulator captures

### 8.1 T5: why TypeScript needs a build step, and the three forms

A browser runs only JavaScript, so a `.ts` file's types must be removed
before it runs. Node 22.18+ and 24 remove them natively ("type stripping"),
but only for *erasable* syntax: interfaces, annotations and `type`
aliases, not `enum`, `namespace` or parameter properties. This container's
Node 22.22 is a distribution build compiled without that support
(`ERR_NO_TYPESCRIPT`, measured), so the container would install an
official Node.

| Form | Browser | Node (CLI, server) | Types | Cost |
|---|---|---|---|---|
| **A. TS + esbuild** | an esbuild bundle (milliseconds; a watch mode during `wfb studio` development) | the same bundle, or the sources under type stripping | full TS syntax; `tsc --noEmit` checks | one dev dependency; source maps for debugging; the "edit, refresh" loop gains a watcher |
| **B. TS, erasable syntax only** (`erasableSyntaxOnly`) | still an esbuild bundle, or a dev server stripping on the fly | the `.ts` sources run directly | everything but `enum`/`namespace` (a union of string literals instead) | as A in the browser, none in Node |
| **C. JS + JSDoc types** | runs as written: no build step | runs as written | `/** @type {…} */` comments, checked by `tsc --noEmit` | no tooling; a heavy syntax for the IR's 1 800 lines of tagged records |

Recommendation: **B**. The CLI, the server and the tests run the sources
with no build. The browser loads one esbuild bundle, which is rebuilt in
milliseconds. Types stay in real TypeScript syntax, and a string-literal
union replaces `enum`, which is how the IR's `kind` fields read already.
The editor's vendored modules (Preact, CodeMirror) are unaffected.

### 8.2 T7: what needs simulator captures, and what does not

**The watch never runs our rasteriser.** It draws the generated Monkey C
with Garmin's own. So our rasteriser decides only two things:
- what the preview and the editor show;
- the few lints that measure rendered pixels: `aod-burn-in`, the AOD
  heatmap, the AOD pixel-mask figures, and the safe-area crop against the
  skin.

Everything the `.prg` contains is decided without it: positions (the
`Layout` constants), code, resources and baked sheets.

| Work (M2 step) | Needs captures? | How it is checked |
|---|---|---|
| 1–2 package, YAML, patches, schema, lower, desugar, IR, expressions | no | equality with Python on the corpus |
| 3 layout | no | equality of every `Layout` constant (the 4 hinted advances aside) |
| 4 font bake (1-bit), `.cft` decoding, stand-ins | no: the sheet *is* what the watch draws | re-baselined once against Pillow's sheets; the per-glyph pixel report is the record |
| 5a draw program, preview, layers, quantise, masks, skin | no | `raster.js` already reproduces Pillow's primitives pixel for pixel in JS (`tests/test_studio_raster.py`), so the TS preview can start **equal to today's goldens** |
| 6 lint | no, apart from the pixel-measured ones, which follow 5a's numbers | equality of every diagnostic |
| 7 codegen | no | the generated project byte for byte (`tools/snapshot.py`) |
| 8 server, CLI, editor in the browser | no | the existing behaviour and tests, ported |
| **5b the Garmin pixel model** | **yes**, per primitive | simulator diff tables, as §3 |
| `outline:` rings; rotated and curved vector text (outlines rotated, then rasterised) | no | rings exact; vector runs a recorded change, by ink overlap with Pillow's image |
| Garmin's own look of `setAntiAlias`, vector text and system-font glyphs | yes | simulator captures |

**So all the migration's correctness work can be done without a capture.**
Only 5b, the step that makes the preview *more* like the watch than
Pillow, needs them. 5b is a swap behind one interface: the rasteriser the
preview calls. It can run last, primitive by primitive, as captures
arrive. In the code, the pixel-dependent part is small. `raster.js` is 810
lines, and `preview.py` plus the masks are about 3 000 of the 46 000.

**What only a capture can settle**, per primitive and device family:
- the convention: where `(x, y)` sits, how a radius is measured, and the
  50 % tie;
- **`drawArc` with a pen width**: every ring and arc gauge, and the most
  common shape after rectangles. Today's preview is known to differ in arc
  caps (`docs/limitations.md`);
- `drawLine` with a width: hands and ticks;
- `fillPolygon`: hands;
- `drawCircle` and `drawRoundedRectangle` with a pen width;
- `setAntiAlias(true)` for each of these;
- `drawText` of a baked sheet: where a justified run lands. This is
  already proven by the system-font calibration face, but should be
  re-checked once on the new bake;
- the 64-colour quantise and dither the simulator applies.

**What a capture session needs from the user:**
- one generated probe face per family, as `ring-on-device`'s
  `make_face.py` does: a grid of each primitive across radii, widths,
  angles and odd/even sizes;
- built on the three verification devices;
- run in the simulator on the host;
- one screen capture each, saved to the probe's folder.

A compare script fits and reports the convention, as `shapes.mjs` does
today. One host session can cover every primitive above. Doing it **early**
lets 5b land with 5a. Doing it **at the end** costs nothing in correctness,
because only the preview's look and the pixel lints wait on it.

---

## Sources

- Probes and results: `docs/research/probes/typescript-stack/`.
  - `yaml.mjs` with `dump_spans.py`;
  - `schema.mjs` with `dump_schema.py`;
  - `shapes.mjs` with `dump_ring_ops.py`;
  - `fonts.mjs` with `dump_bakes.py`;
  - `results.txt`.
- The simulator capture: `docs/research/probes/ring-on-device/capture.png`
  (research 28 §7).
- `wfb/edit/spans.py` (`SpanIndex`, `value_end`), `wfb/validate.py`,
  `wfb/fonts/bmfont.py` (`bake`, `_rasterise`, `SUPERSAMPLE`),
  `wfb/preview.py` (`_paste_rotated_run`), `wfb/studio/static/raster.js`,
  `docs/limitations.md` (Garmin's circles and corners; `antialias:` on
  primitives).
- Research 26 §8 and decision D3 (no build step), research 29 table D (the
  release wait), research 31 (Pyodide, rejected by the user).
- Packages: `yaml` 2.9.1, `ajv` 8.20.0, `opentype.js` 2.0.0,
  `@napi-rs/canvas` 1.0.10 (Skia), against ruamel.yaml, jsonschema 4.x and
  Pillow 12.3.0.
