# 31 — The compiler, the editor and the server in TypeScript

**Status: proposed (2026-10-05). Every decision is taken (§1); nothing is
built.** Delete this file once every slice has shipped (`docs/CLAUDE.md`).
Work happens on the `typescript` branch. The last all-Python state is the
tag `v0.3`: the Python server, with a heavily server-dependent GUI.

Records this builds on:
- `docs/research/32-typescript-stack.md`: the measured replacements for
  ruamel, jsonschema, Pillow and FreeType; the Garmin shape model against
  the simulator; the migration strategies; and every decision below.
- `docs/research/31-standalone-browser-editor.md`: what the browser
  editor must do on its own (§1), and decisions S2 and S3, which carry over.
- ADR 0001 (Python), amended by this decision.

In short:

* **One TypeScript package, `ts/`.** It runs unchanged in the browser (in a
  Web Worker) and in Node (the CLI, the build server and the tests).
  - It is written in erasable TypeScript, so Node runs the `.ts` sources
    directly.
  - The browser loads one esbuild bundle.
* **Ported stage by stage, with Python as the oracle.**
  - A tool dumps every stage's output for the example corpus as JSON.
  - The TypeScript stage must reproduce it, or the difference is a
    recorded, deliberate change.
  - Python stays the shipping compiler until the last slice.
* **Deliberate changes:**
  - every baked font sheet, re-baselined once (slice 5);
  - later, the preview's shapes, moved from Pillow's model to Garmin's
    (slice 10).
* **The pixel model.**
  - The TypeScript preview starts **equal to today's Pillow goldens**,
    through `raster.js`.
  - It moves to the Garmin model (true geometry, a pixel-centre convention
    and a half-coverage rule) primitive by primitive, as simulator captures
    arrive.
  - Captures are taken on the three verification devices **and the
    AMOLED fēnix 8** (`fenix847mm`, 454×454), whose resolution constrains
    the fit better.
* **The end state.**
  - The editor runs entirely in the browser: the compiler, previews,
    history (IndexedDB) and the bundle `.zip`.
  - A small Node server serves the app, device digests and fonts, and
    builds `.prg` files with `monkeyc`.
  - The CLI is Node.
  - Python is deleted.
* **Nothing about the format or the watch changes.** The YAML, the schema,
  `runtime-lib/` and the generated Monkey C stay the same. Codegen is held
  byte for byte against Python's output, except resources from the font
  re-baseline.

## 1. Decisions

All taken by the user on 2026-10-05, in `docs/research/32-typescript-stack.md`
§7 and §8.

| # | Decision |
|---|---|
| T1 | The whole stack moves to TypeScript |
| T2 | The preview models Garmin's rasteriser, held to simulator captures. Pillow-based previews are the baseline for early development |
| T3 | Our own deterministic rasteriser for anything that ships or is tested. The platform canvas is for the editor's chrome and live drawing only |
| T4 | Nothing is postponed from the port. **`outline:` rings** are ported exactly (sheet dilation, grown copies and stamps). **Rotated and curved vector text** rotates the glyph *outlines*, then rasterises them: a recorded change against Pillow's rotated image. **Anti-aliasing** has nothing to port: the preview draws no anti-aliased primitive, and anti-aliased sheets come with the bake. Only research into Garmin's own `setAntiAlias` and vector-text appearance waits, for slice 10's captures. Glyph outlines come from `opentype.js`, behind one module |
| T5 | Option B: erasable-syntax TypeScript (`erasableSyntaxOnly`). Node runs sources directly; the browser gets an esbuild bundle |
| T6 | Stage by stage with Python as the oracle (research 32 §6, M2) |
| T7 | Simulator captures can come last. Only the pixel model needs them (research 32 §8.2) |
| T8 | Shapes are checked against `fenix8solar47mm`, `fenix8solar51mm`, `fr955` and `fenix847mm`. The fēnix 8 AMOLED 47 mm and 51 mm are one device definition (454×454) |
| S2 | Documents live in the browser first. Server storage and sync come later (research 31) |
| S3 | The server sends device files and fonts (research 31) |

**Defaults this plan takes; say so to change them:**
- **D1.** The package lives at `ts/`, with `ts/src/` mirroring `wfb/`
  module for module, so the oracle pairs are obvious.
- **D2.** Node 24 LTS (an official build: type stripping on by default).
  This container's distribution Node 22.22 lacks it, so slice 1 installs
  Node through `tools/setup-env.sh` and the Dockerfile.
- **D3.** Tests use `node:test`, with no test-framework dependency. Their
  runtime dependencies are `yaml`, `ajv`, `opentype.js` and `fflate`, plus
  `typescript` and `esbuild` for development. `package-lock.json` is
  committed. The browser bundle is built, not committed.
- **D4.** The JSON at each oracle boundary keeps Python's field names
  (snake_case), so a dump compares with no mapping. The TypeScript types
  use the same names.

## 2. Rules for every slice

- **The fast suite stays green on both halves.** `pytest -m "not slow"`
  and `npm test` in `ts/`. A TypeScript test that fails without Node
  fails; it is never skipped.
- **Oracle equality is the acceptance test.** A slice ships when
  `npm run parity -- <stage>` reports zero differences on the corpus, or
  when every difference is listed in that slice's "recorded changes" with
  a reason.
  - The corpus is every `examples/**/face.yaml` and `tests/fixtures/**`.
  - The devices are the three verification devices plus `fenix847mm`, and
    the snapshot tool's mixed sets.
- **`tsc --noEmit` is clean** (strict, `erasableSyntaxOnly`), and stays
  clean, as `mypy --strict` is for `wfb/`.
- **The Python compiler is not changed to suit the port.** The exception is
  a bug the port exposes: fix it in Python first, with a test, so the
  oracle stays right.
- **New compiler features during the migration:** written in TypeScript
  if every stage they touch is ported, otherwise in Python first and ported
  with their stage. Nothing lands in one language only once both exist for
  a stage.
- **A comment says what the code does.** Which slice built it goes in the
  commit message (root `CLAUDE.md` §7).

## 3. Slices

### Slice 1 — the package, the toolchain and the oracle

**Built 2026-10-05.**
- The oracle dumps all 12 stages for 40 designs: 168 device cases, in
  about 30 s.
- `npm run parity` reports every stage missing, as it should with nothing
  ported yet.
- The fast suite runs `ts/`'s tests and type check (`tests/test_ts.py`).

**Departures from the plan:**
- `diagnostics-lint` is per device set. The AMOLED `fenix847mm` resolves on
  its own, not together with the targets. Resolving it with the targets made
  three designs fail to build (no subscreen on `fenix847mm`; no partial
  update on AMOLED), which would have left them without a `project`.
- **The Docker image change is unverified:** Docker Hub was unreachable from
  the sandbox. What was checked: official Node 24 runs inside the existing
  runtime image (`python:3.13-slim-trixie`) and passes `ts/`'s tests there.

- **Toolchain.**
  - `ts/package.json`, `tsconfig.json` (strict, `erasableSyntaxOnly`,
    `noEmit`, ES2023, `module: nodenext`), and esbuild.
  - `npm test` (`node --test`), `npm run typecheck`, and
    `npm run bundle`, which writes `ts/dist/wfb.js` for the browser.
- **Node 24.** `tools/setup-env.sh` and the Dockerfile install it, and
  `wfb doctor` reports its version.
- **`tools/oracle.py`** writes `.cache/oracle/<design>/<device>/<stage>.json`
  for each stage boundary:
  - `spans`: every entry's key, value and end offsets (as
    `docs/research/probes/typescript-stack/dump_spans.py`);
  - `data`: the parsed data;
  - `diagnostics`: code, severity, message and span;
  - `face`: the IR after lower, desugar and the semantic pass, by a generic
    dataclass-to-JSON walk, with enums as their values and tuples as lists;
  - `layout`: every `Layout` constant and `Placed` box per device;
  - `fonts`: each baked font's metrics, glyph boxes and sheet as
    base64;
  - `draw`: `jsonform` ops per element;
  - `preview`: PNG frames, as `tools/snapshot.py`'s preview cases;
  - `project`: the generated project's files.

  Stages are dumped lazily, so `--stage spans` costs only a parse.
- **`npm run parity -- <stage>`** reads the same corpus, runs the
  TypeScript stage, and diffs JSON (or pixels) against the oracle. It
  prints a per-stage table like research 32's probes.
- **Device access.** `ts/src/devices.ts` reads the same files
  `wfb/devices.py` reads (`compiler.json`, `simulator.json`,
  `api.debug.xml`, the device reference) through one interface: the
  filesystem in Node, and the server's digest in the browser (slice 9).
- **Docs.**
  - Root `CLAUDE.md` §1 gains `ts/` in "where things live", and §2 gains
    Node.
  - `docs/development.md` gains the TypeScript layout and the parity
    workflow.
  - `tests/CLAUDE.md` gains `npm test`.
- **Done when:** `npm test`, the typecheck and `parity -- spans` (an empty
  TypeScript stage reporting every case missing) run on a fresh
  `setup-env.sh`.

### Slice 2 — YAML spans, the patch engine and the gate

- **`ts/src/yamlsrc.ts` and `ts/src/edit/*`** over `yaml`'s CST and
  nodes. This covers spans (`SpanIndex`, with `value_end` restated so the
  11 comment-block cases of research 32 §2.1 match ruamel's result), the
  patch engine, and `structure`, `geometry`, `colors`, `schemes`,
  `slots` and `hands`.
- **Parity:**
  - `spans` and `data`;
  - every patch `tests/test_edit.py` makes over the corpus, compared as
    resulting text: the same text, byte for byte;
  - `yaml`'s CST round trip as a guard.
- **The gate** (`wfb/edit/gate.py`) waits for slice 3's diagnostics. Its
  tests come over then.

**Built 2026-10-05.** Parity is exact on four stages:

| Stage | Equal | Notes |
|---|---|---|
| `nodes` (new) | 50 of 51 | ruamel's whole composed tree |
| `spans` | 50 of 51 | |
| `data` | 48 of 48 | |
| `patches` (new) | 51 of 51 | 37 442 replayed edit operations |

- **The one deviation** in `nodes` and `spans` is recorded in
  `ts/tools/stages.ts`: an invalid text's error message is the `yaml`
  package's, not ruamel's.
- **The corpus** now includes `ts/test/cases/yaml/`, edge cases the faces
  do not exercise.
- **`nodes` stage.** The composer rebuilds ruamel's node tree (marks,
  tags, values) from the `yaml` package's AST. That turned out simpler than
  restating `value_end`, and it leaves `SpanIndex` a line-for-line port.
- **`patches` stage.** It replaces "every patch `tests/test_edit.py`
  makes" with a generated battery (`tools/oracle_patches.py`):
  - every operation of `patch`, `structure`, `colors`, `schemes` and
    `hands`, on every entry and element of every design;
  - each outcome recorded as a splice of the text, the description, a
    hash of the intended data, a refusal or a crash.

**Departures:**
- **`slots`** moves to slice 3: it reads `complications.py`.
- **`geometry`** (pixel drags) moves to slice 4: it reads devices, the IR
  and layout.
- **Also ported:** `palette.ts` (whole), and `series.ts` (its tables; its
  difflib suggestions come with the catalogue).
- **`ts/src/py.ts`** holds the Python semantics the port reproduces:
  - truthiness, `repr`, `json.dumps` and `splitlines`;
  - `f"{x:.6f}"` and `round()`, half to even;
  - `float.hex()`, and `PyError` for crashes.

### Slice 3 — schema, lower, desugar, the IR, the catalogue and expressions

- `validate.ts`: Ajv (Draft 2020-12, `allErrors`), and `validate.py`'s
  error shaping, ported. That shaping covers the `oneOf` branch the author
  meant, required-one-of, exclusive keys and unexpected keys, rebuilt from
  Ajv's `schemaPath` instead of jsonschema's `context`.
- Also `lower.ts`, `desugar.ts`, `ir/*`, `catalog.ts`, `expr.ts`,
  `units.ts`, `availability.ts`, `complications.ts`, `edit/slots.ts`,
  `formatting.ts`, `series.ts`, `vocab.ts`, `template.ts`, and each kind's
  lowering half (`kinds/*`).
- **Parity:** `diagnostics` (code, severity, message text, span) and
  `face`, over the corpus and over research 32's 1 230 mutated faces
  (`dump_schema.py`), whose messages must match too.
- The gate's tests (`test_edit.py`'s refusals) come over here.

**Built 2026-10-05.** Parity over 2 872 designs: the 51 of the corpus and
2 820 captured from the fast test suite.

| Stage | Equal | Notes |
|---|---|---|
| `face` (the IR) | 2 386 of 2 386 | every design that loads |
| `diagnostics-load` | 2 867 of 2 872 | 5 deviated: an invalid text's message |
| `load-validate`, `-lower`, `-desugar`, `-ir` | 52 of 52 each | 1 971 seeded broken variants, each pass |
| `data`, `lowered`, `desugared` | all | |
| `nodes`, `spans` | 2 867 of 2 872 | 5 deviated, as in slice 2 |

- **`validate.ts` runs on `jsonschema.ts`, not Ajv.** A port of
  python-jsonschema's Draft 2020-12 validator gives the same error tree,
  so `validate.py`'s shaping ports line for line and its messages match;
  rebuilding them from Ajv's `schemaPath` could not. Ajv is no longer a
  dependency.
- **The captured corpus.** `tools/capture_designs.py` runs the fast suite
  with `wfb.build.load` wrapped, keeping every design it loads (thousands of
  small faces, most written to hit one diagnostic) in
  `.cache/test-designs/`. The oracle dumps their load stages. It stands in
  for research 32's 1 230 mutated faces, which only reached the schema.
- **The oracle loads by repository-relative path**, so a diagnostic that
  quotes a path is the same on every machine (format 5).
- **Merge keys (`<<`).** Slice 2's YAML layer refused them, and no face
  used one. The captured corpus did. Both of ruamel's constructors are now
  matched: the safe one (span index, `parse`) puts the merged pairs first;
  the round-trip one (the loader) appends the keys a mapping lacks, and
  `CommentedMap.insert` (desugar's injected `id`) keeps them in place. An
  anchored node starts at its anchor.
- **Also ported:** `conversion.ts`, `build.ts` (`load`), `ir/rings.ts`,
  `edit/gate.ts` with its tests, `edit/slots.ts`, `src/node.ts` (the
  schema, the icon font's character map and font files, read from disk).

**Departures:**
- **`availability.ts`** moves to slice 4: it reads devices, and only
  layout and lint ask it anything.

### Slice 4 — per-device layout

- `layout.ts`, `visible_area.ts`, `edit/geometry.ts` (pixel drags in the
  author's units), and font *metrics* only: `wfb/fonts/`
  system-font metrics, `cft.ts`'s header and metrics, and the registry.
  Baking waits for slice 5.
- **Parity:** `layout`, every constant and box, on every corpus face ×
  device. Text measurement uses the oracle's baked metrics until slice 5,
  so this slice is exact.

**Built 2026-10-06.** `layout` is equal on 167 of 168 face × device cases,
1 deviated (below). Also ported: `devices/device.ts` (`Device`,
`FontMetric`, `DeviceDatabase`, with the symbol queries
`hasSymbol`/`hasModule`/`hasField`), `visible_area.ts` over a small PNG
decoder (`png.ts`), and `edit/geometry.ts` with its tests.

- **Font files.** `fonts/files.ts` is the locator (the Garmin font root,
  then the registry's pinned stand-ins) behind a `FontFiles` interface:
  Node reads disk (`fonts/node.ts`), and the browser will get files from
  the server. `fonts/sfnt.ts` reads `head`/`hhea`/`hmtx`/`cmap` directly,
  and `fonts/cft.ts` decodes Garmin's bitmap container. Both agree with
  fontTools and `cft.py` on all 567 installed font files: every metric,
  cmap entry, advance and decoded glyph.
- **The skin masks** agree with Python on all 33 installed skins (two are
  16-bit RGBA, whose high byte Pillow keeps).
- **Trigonometry.** `Math.hypot` differs from Python's in the last bit on
  a third of inputs, so `py.hypot` computes it exactly (equal on 200 000
  pairs). `Math.sin`/`cos`/`atan2` differ from glibc's on 2-18% of inputs,
  but never at a pixel in the corpus; per the user (2026-10-06) they stay
  as they are, to tune later if a case needs it. Matching glibc would mean
  porting its FMA build of `s_sin.c`.
- **Pillow's default face**, which measures a font with no file at all
  (here, a vector font with no face on the device, so the text is hidden
  there): its size metrics are matched exactly, its advances are the
  embedded Aileron's own, where Pillow's are FreeType's hinted ones. The
  one case this reaches is a recorded deviation, one pixel of width.
- **Not covered by parity:** the captured test designs have no device
  stages yet; layout parity is the 40 corpus faces on their devices.

**Departures:** `availability.ts` (the build-wide guards and the
per-element checks) moves again, to slice 7: its callers are lint and
codegen, and layout asks it nothing.

### Slice 5 — the font bake (recorded change)

- `ts/src/fonts/bake.ts`. The pipeline:
  1. `opentype.js` outlines at 16×;
  2. our own coverage rasteriser of a path (a scanline over
     the flattened outline, nonzero winding, exact area per pixel);
  3. crop to the ink, area-average down, and threshold at 128;
  4. pack the sheet and write the `.fnt`.
- Also: anti-aliased sheets (the same bake without the threshold), `dilate`
  for `outline:` rings (exact: a pixel operation on the sheet), `.cft`
  glyph decoding, system-font stand-ins drawn glyph by glyph through the
  same rasteriser, and the icon font (`icons.ts`, `icon_catalog.ts`).
- **The PNG writer** is our own, uncompressed or through `fflate`
  (`zlib`), so the output is deterministic everywhere.
- **Parity:** `fonts`, as research 32's `fonts.mjs` tables, per font and
  size.
- **Recorded changes:**
  - every baked sheet;
  - any `layout` constant that moves with a hinted advance (research 32
    §4: 4 of 1 576);
  - the per-glyph pixel report kept in `docs/research/probes/typescript-stack/`.
- `tests/golden/` resources are regenerated in this slice, with the report
  as the explanation (`tests/CLAUDE.md`: explain, do not just regenerate).

**Built 2026-10-06.** `fonts` is equal on 97 of 168 face × device cases
and within the two recorded deviations on the other 71. `layout` still
places with the oracle's fonts, so its parity stays the layout's own.

- **Metrics and advances are exact.** FreeType computes them in 16.16 and
  26.6 fixed point, and the bake does too (`FT_DivFix`/`FT_MulFix`): equal
  to Pillow on every size from 4 to 139 for every corpus font, and on 18 000
  sampled advances. Rounding the exact values instead missed 9 line heights
  and 84 advances.
- **The rasteriser** (`fonts/raster.ts`) is the signed-area accumulation
  of font-rs and stb_truetype over flattened outlines, with Pillow's BOX
  resample transcribed. Against FreeType, where a glyph's box agrees, under
  1 % of 1-bit ink differs (`docs/research/probes/typescript-stack/
  bake-report.txt`): a recorded deviation on sheets, tile boxes and offsets.
- **Icon sizing is a deviation of its own.** `bake_size` searches the
  nominal size whose ink height matches `size:`, and Python measures
  FreeType's *hinted* box, which at icon sizes moves points per glyph. The
  closest unhinted rule (the outline's own pixel bounds) picks the same size
  in 345 of 660 sampled searches; per the user (2026-10-06) this is left to
  tune later. A choice to make then: match Python, or size by the TS bake's
  own ink, which would be right for the sheets TS ships.
- **Also built:** `emit/resources.ts`'s bake half (`glyphSet`,
  `iconFontSpecs`, `bakeFonts`), every kind's `textRuns`, ring fonts, and a
  deterministic PNG writer (`png.ts`).

**Departures:**
- `tests/golden/` stays Python's: the goldens are the shipping compiler's
  output, and its codegen is still Python's until slice 8.
- System-font stand-ins drawn glyph by glyph move to slice 6, with the
  preview that draws them.

### Slice 6 — draw program, preview and layers (Pillow baseline)

- `draw/*` (program, evaluator, printer, barrel, jsonform, layers,
  frames), `preview.ts`, `aod_mask.ts`, and the palette quantise, bezel
  mask and skin.
- Shapes are drawn by **`raster.js`, moved into `ts/src/raster/pillow.ts`**
  behind one interface, `Rasteriser`. That keeps today's goldens: the
  T2 baseline.
- The text runs paste the slice-5 sheets.
- **`outline:` rings** on shapes, groups, hands and text: the grown copy,
  the shifted polygon and the stamp, as the draw program has them. They
  are exact, since they are geometry over the same primitives.
- **Vector text** (`face:` fonts, upright, rotated or curved). Each glyph's
  outline is placed, rotated about the run's pen path (`layout`'s curve
  angles and radial bands), and rasterised by slice 5's coverage
  rasteriser. This replaces Pillow's render-at-4×, rotate (bicubic) and
  downsample (Lanczos) path (`preview.py` `draw_vector_text`,
  `_draw_radial_vector_text`, `_paste_rotated_run`). The geometry is exact,
  so the stairs Pillow's image rotation leaves are gone.
- **Parity:**
  - `draw`, exact;
  - `preview`, pixel for pixel, except text from re-baked sheets and
    vector runs.
- **Recorded changes:** vector-text pixels on `features/outline`,
  `features/vector-text` and `generated_by_skill/trail-utility` (84 runs).
  For each run, measure ink overlap with Pillow's image (intersection over
  union) and the bounding-box offset, so the change is a figure and not a
  judgement.

**Built 2026-10-06.** On the 168 face × device cases, `draw` is equal on 38
and within its two recorded deviations on 130; `preview` is equal on 37 and
on the other 131 differs only inside system-font and vector-font runs. Like
`layout`, both start from the oracle's baked fonts, so a difference is the
draw program's or the renderer's, not the bake's.

- **Shapes are pixel-exact on every frame.** `raster/pillow.ts` is
  `raster.js` typed, and a test draws a sweep of every primitive with both
  and requires the same bytes (and the same refusals).
- **Face-drawn text is the recorded change.** System and vector faces are
  rasterised from their outlines (`opentype.js` paths, the slice-5
  rasteriser); a turned run turns its outlines first. Measured per run on
  every frame (`docs/research/probes/typescript-stack/text-report.txt`,
  `ts/tools/text-report.ts`): median ink IoU 0.84 for upright system text,
  0.86 angled and 0.77 radial vector text, with the ink's box moving under
  half a device pixel on average. Upright text differs mostly by FreeType's
  hinting; turned text also loses Pillow's rotation blur and halo.
- **A third deviation:** a turned part's coordinates come from `Math.sin`
  and `Math.cos`, a last bit off glibc's now and then, so `draw` compares
  numbers to 10 significant digits. No pixel moved.
- **Pulled forward from slice 8:** every kind's `layoutConstants` (lowering
  names its `Layout` constants), the shared constant blocks, `ReadPlan`'s
  analysis, guards and declarations, `AodStyle`, `RingPass`, the view's
  `negated`, and the printer's value spellings (`numCode`, `colorCode`,
  ...), which lowering compares colours by. `Guards` is a three-field
  interface until `availability` is ported in slice 7.

**Departures:**
- **Printing the ops** (`print_ops`, `emit_body`) moves to slice 8 with the
  view that prints them; parity checks it there, through `project`.
- **The skin, `--all-styles`, `--heatmap` and the stand-in warning** move to
  slice 9 with the CLI that offers them. The skin needs Pillow's Lanczos
  resample, which nothing else uses.
- **`Rasteriser` is the module, not a class:** functions over an RGBA
  `Image`. `wfb/studio/static/raster.js` stays until the editor's front end
  switches to the bundle in slice 9.

### Slice 7 — lint

- `lint.ts`, every check. The pixel-measured ones (`aod-burn-in`, the
  heatmap, safe area) read slice 6's frames.
- **Parity:** `diagnostics` after lint, on the corpus × devices.

### Slice 8 — codegen and the build

- `emit/*` (Monkey C, resources, manifest, jungle, writer), each kind's
  emit half, and `mcsource.ts`.
- `build.ts` runs `monkeyc` through `child_process`, with
  `--build-stats` measurement, in Node only.
- **Parity:** `project`, **byte for byte** (`tools/snapshot.py`'s build
  cases), except slice 5's resources. A slow test builds the three
  verification devices plus `fenix847mm` warning-free with the
  TypeScript-generated projects.

### Slice 9 — the Node server, the CLI and the browser editor

- **CLI.** `ts/src/cli.ts`: `build`, `validate`, `preview`, `simulate`,
  `fonts`, `devices`, `doctor`, `studio`, with the same flags and exit
  codes. `tools/snapshot.py`'s CLI cases are the parity check.
- **The server** (`wfb studio`, Node), with these routes:
  - the static app;
  - `GET /api/devices/<id>`: `compiler.json`, `simulator.json`, the
    device reference, the skin, and a digest of `api.debug.xml` holding
    only what `availability` reads (1.6 MB down to the symbols asked
    for);
  - `GET /api/fonts/<name>`;
  - `POST /api/build`: the bundle in, the `.prg` files and the build-stats
    diagnostics out.
- **The editor.**
  - The compiler runs in a Web Worker from `ts/dist/wfb.js`.
  - Each of `document.py`'s operations becomes a worker message: frame,
    layers, drag, edit, structure, undo, redo, history, inspect, snapshot
    and thumbnail.
  - `store.py`'s journal and blobs move to IndexedDB, in a format a
    server can replay later (S2).
  - Upload and download go through `bundle.ts` with `fflate`.
  - Device files and fonts are cached with the Cache API, keyed by SDK
    version and hash.
  - The front end's existing modules switch from `api.js`'s `fetch` to the
    worker, keeping their calls.
- **Removed:** sessions, claims, locks, the event stream and the `Host`
  allowlist. With no shared server state, they guard nothing. That is
  revisited with server sync.
- **Parity:**
  - the studio tests (`test_studio*.py`), ported to run against the worker
    under Node;
  - `test_studio_frontend.py` and `test_studio_panels.py` unchanged in
    spirit.

### Slice 10 — the Garmin pixel model (needs captures; can run last)

- **Probe faces** from one generator,
  `docs/research/probes/garmin-raster/make_faces.py`, one per primitive
  family:
  - `fillCircle` and `drawCircle` with a pen;
  - `drawArc` with a pen, across start angles and sweeps;
  - `drawLine` with a width, across angles;
  - `fillPolygon`;
  - `fillRoundedRectangle` and `drawRoundedRectangle`;
  - `drawRectangle` with a pen;
  - a run of `drawText` from a baked sheet;
  - a swatch strip for the simulator's quantise and dither.

  Each comes in a grid of sizes, odd and even, built for **`fenix8solar47mm`,
  `fenix8solar51mm`, `fr955` and `fenix847mm`**.
- **The user's host session:** run each face in the simulator and save one
  screen capture per face and device into the probe folder.
- **`ts/src/raster/garmin.ts`**, the second `Rasteriser`: exact-area
  coverage of the true geometry, a pixel-centre convention and the
  half-coverage rule, with the tie broken one way everywhere. A compare
  script fits each primitive's convention per device family and writes
  the diff tables, as research 32 §3.
- **AMOLED is checked, not assumed.** `fenix847mm` may draw differently
  from MIP. The model is fitted per family and only shared when the tables
  agree.
- **The switch:** the preview and the pixel lints use `garmin.ts`.
  `pillow.ts` is deleted once no test needs it.
- **Recorded changes:**
  - every preview golden and every pixel-measured lint figure that moves;
  - the diff tables as the evidence;
  - `docs/limitations.md`'s "Garmin's circles and rounded corners are not
    Pillow's" rewritten to state what the model now matches.

### Slice 11 — delete Python

- **Port or retire every remaining test.** The pure-logic ones should
  already be ported with their stages.
- **Delete** `wfb/`, `wfb.py`, `requirements*.txt`, `mypy.ini` and
  `tests/*.py`. Retire `tools/oracle.py`; keep `tools/research/` as
  research tooling, with its own small requirements.
- **ADRs:**
  - ADR 0001: a dated amendment saying the migration is complete;
  - ADR 0003's "small hand-written barrel" note and ADR 0008's measurement
    claims re-checked.
- **Docs, same commit:**
  - root `CLAUDE.md` (language, setup, build commands, the fast suite);
  - `docs/development.md`, `docs/container.md`;
  - `tests/CLAUDE.md`, `wfb/CLAUDE.md` → `ts/CLAUDE.md`;
  - `docs/lore/toolchain.md`, `docs/lore/codegen.md`;
  - the guide's CLI chapter (`docs/guide/preview-and-cli.md`).
- **The Docker image.**
  - It drops Python except for `tools/research/`.
  - It is brought up to date with the TypeScript stack here, once, and the
    user tests it.
  - Until then, no slice builds or tests the image (user decision,
    2026-10-05). Slice 1's Node stage stays as written.

### Close-out

- Delete this plan, and add its row to `docs/plans/README.md`.
- `docs/lore/roadmap.md` records the migration as shipped.
- Tag the first all-TypeScript release.

## 4. Order and parallelism

Slices 1 → 9 are sequential: each consumes the previous stage's TypeScript
output.

Slice 10 depends only on slice 6's `Rasteriser` interface:
- its probe faces and capture session can happen any time after slice 1;
- its fitting any time after slice 6;
- it can also run last (T7).

Slice 11 follows everything.

Until slice 9, the shipping tools are Python's; the user's workflow does not
change.

## 5. Risks

- **Size and drift.** About 40 000 lines move while features continue.
  Mitigations:
  - the oracle;
  - the rule that nothing lands in one language once both exist for a
    stage;
  - slices small enough to finish.
- **The 11 comment-block ends** (slice 2) decide what a delete or a move
  takes with it. A mismatch would silently change edits. The patch-text
  parity over the corpus is the guard.
- **Error-message parity** (slice 3) is the most code to port for the least
  visible gain. If shaping from `schemaPath` turns out not to reproduce
  jsonschema's `context` choices, the fallback is a recorded change per
  message, reviewed by the user.
- **The font re-baseline** (slice 5) changes every face's glyphs slightly,
  and a few layout constants by a pixel. It is reviewed once, with the
  report.
- **Determinism across browsers** depends on never using canvas pixels for
  anything that ships or is compared. A test in slice 6 asserts the bundle
  draws through `Rasteriser` only.
- **Node in the container.** Slice 1 replaces the distribution Node with an
  official build. `test_studio_frontend.py`'s existing Node use moves with
  it.
- **Captures** (slice 10) need the user's host. Until then the preview is
  exactly as faithful as today: no worse at any point.
