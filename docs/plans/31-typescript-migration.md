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
| T4 | Glyph-outline features (rotated and curved vector text, `outline:` rings) and anti-aliasing are the lowest priority: postponed, to be re-researched with TypeScript in mind. A 1-bit bake uses `opentype.js`, behind one module |
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

### Slice 3 — schema, lower, desugar, the IR, the catalogue and expressions

- `validate.ts`: Ajv (Draft 2020-12, `allErrors`), and `validate.py`'s
  error shaping, ported. That shaping covers the `oneOf` branch the author
  meant, required-one-of, exclusive keys and unexpected keys, rebuilt from
  Ajv's `schemaPath` instead of jsonschema's `context`.
- Also `lower.ts`, `desugar.ts`, `ir/*`, `catalog.ts`, `expr.ts`,
  `units.ts`, `palette.ts`, `availability.ts`, `complications.ts`,
  `formatting.ts`, `series.ts`, `vocab.ts`, `template.ts`, and each kind's
  lowering half (`kinds/*`).
- **Parity:** `diagnostics` (code, severity, message text, span) and
  `face`, over the corpus and over research 32's 1 230 mutated faces
  (`dump_schema.py`), whose messages must match too.
- The gate's tests (`test_edit.py`'s refusals) come over here.

### Slice 4 — per-device layout

- `layout.ts`, `visible_area.ts`, and font *metrics* only: `wfb/fonts/`
  system-font metrics, `cft.ts`'s header and metrics, and the registry.
  Baking waits for slice 5.
- **Parity:** `layout`, every constant and box, on every corpus face ×
  device. Text measurement uses the oracle's baked metrics until slice 5,
  so this slice is exact.

### Slice 5 — the font bake (recorded change)

- `ts/src/fonts/bake.ts`. The pipeline:
  1. `opentype.js` outlines at 16×;
  2. our own coverage rasteriser of a path (a scanline over
     the flattened outline, nonzero winding, exact area per pixel);
  3. crop to the ink, area-average down, and threshold at 128;
  4. pack the sheet and write the `.fnt`.
- Also: `dilate` for outline rings (postponed by T4, so ported as is,
  without new research), `.cft` glyph decoding, stand-ins, and the icon
  font (`icons.ts`, `icon_catalog.ts`).
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

### Slice 6 — draw program, preview and layers (Pillow baseline)

- `draw/*` (program, evaluator, printer, barrel, jsonform, layers,
  frames), `preview.ts`, `aod_mask.ts`, and the palette quantise, bezel
  mask and skin.
- Shapes are drawn by **`raster.js`, moved into `ts/src/raster/pillow.ts`**
  behind one interface, `Rasteriser`. That keeps today's goldens: the
  T2 baseline.
- The text runs paste the slice-5 sheets.
- **Vector text** (`face:` fonts, rotated or curved) is postponed by T4. It
  keeps a placeholder that draws the run's ink box and reports `vector text
  preview pending`. A face using it builds and lints as before, because
  only its preview is affected.
- **Parity:** `draw`, exact; `preview`, pixel for pixel except text from
  re-baked sheets.

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
- The Docker image drops Python except for `tools/research/`.

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
