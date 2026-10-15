# ts/

Loaded automatically when working under `ts/`. The compiler, its CLI and
the editor, in TypeScript on Node; `../wfb` runs `src/cli.ts`.

## Running it

```sh
npm test                    # node:test over test/**/*.test.ts
npm run typecheck           # tsc --noEmit, strict; then app/ (tsconfig.app.json, strict)
npm run test:slow           # builds every slow-test design, example and fixture with monkeyc
npm run test:browser        # drives wfb studio in headless Chromium (browser/, Playwright; test/CLAUDE.md)
npm run bundle              # dist/wfb.js, dist/worker.js and dist/app.js, the browser bundles (not committed)
```

Node runs the `.ts` sources directly (type stripping), so there is no build
step outside the browser bundle. That needs an official Node 22.18+ or 24;
`../tools/setup-env.sh` installs one when the `node` on `PATH` cannot.
How the tests are organised, and the rules they keep, is `test/CLAUDE.md`.

## Rules

- **Erasable syntax only** (`erasableSyntaxOnly`): no `enum`, `namespace`
  or parameter properties. Use a union of string literals for an enum, as
  the IR's `kind` fields already are.
- **Imports name the `.ts` file** (`./files.ts`), as Node's type stripping
  requires. Type-only imports use `import type`.
- **One package for the browser and Node.** Nothing reachable from
  `src/browser.ts` may import a `node:` module. Node-only code sits in its
  own module (`src/devices/node.ts`), which only Node entry points import.
- **The compiler began as a port of a Python one**, and keeps Python's
  semantics wherever output depends on them (`src/py.ts`: rounding,
  `quoted` values, string formatting; the IR's snake_case field names). Keep them:
  the goldens hold every output to what that port produced.
- **Deterministic everywhere.** Nothing that ships or is compared may come
  from a canvas's pixels or a platform text engine: same input, same bytes,
  in every browser and in Node.
- **Comments say what the code does and why**; which slice built it goes
  in the commit message.

## Layout

- `src/` is the compiler, one module per pipeline stage
  (`docs/development.md`, "Pipeline"); `src/CLAUDE.md` loads its lore.
  - `src/devices/files.ts` is the `DeviceFiles` interface every stage reads
    devices through: synchronous, filled up front in the browser.
  - `src/devices/node.ts` is the same interface over the SDK's folders.
  - `src/devices/device.ts` is `Device` and `DeviceDatabase` over it; a
    database also holds the `FontFiles` its system-font metrics read.
  - `src/fonts/files.ts` is the `FontFiles` interface (the Garmin font
    root, then the registry's stand-ins), and `src/fonts/node.ts` the same
    over disk. `sfnt.ts`, `cft.ts` and `fallback.ts` read and measure the
    files; `bmfont.ts` is a baked font's data, and `bake.ts` bakes one:
    opentype.js outlines (used nowhere else), our rasteriser (`raster.ts`)
    and FreeType's fixed-point metrics. `src/emit/resources.ts` bakes a
    face's fonts for a device.
  - `src/layout.ts` is per-device layout; each kind's `resolve` is in
    `src/kinds/`. Trigonometry is `Math.sin`/`cos`/`atan2`, but `hypot` is
    `py.hypot`: `Math.hypot` is often a bit off Python's.
  - `src/draw/` is the draw program: `program.ts` its values and ops
    (plain objects tagged `t`, built by functions named as Python's
    classes), each kind's `lower` and `layoutConstants`, `evaluator.ts`
    (Monkey C's arithmetic: a number keeps the Number/Float split, a whole
    float being a `WholeFloat`), `jsonform.ts` and `layers.ts`.
    `src/emit/monkeyc/` holds the codegen pieces lowering reads:
    `ReadPlan`, `AodStyle`, the constant blocks.
  - `src/preview.ts` renders a frame: shapes through `src/raster/garmin.ts`
    (Garmin's own rules, fitted to simulator captures) and
    `src/raster/pillow.ts` (Pillow's primitives, byte for byte, for the rest), baked text from its sheets, and
    system and vector faces from their outlines through `fonts/raster.ts`,
    a turned run turning its outlines. `src/sample.ts` is the sample
    readings.
  - `src/emit/` is codegen: `monkeyc/` the Monkey C sources (the view, the
    delegate, `Layout.mc` and the rest), `resources.ts`, `manifest.ts`,
    `jungle.ts` and `project.ts`, which assembles them in memory. The
    support barrel comes from `src/data/runtime-lib.json`. Writing and
    compiling a project is `src/node_build.ts` (Node only), which
    `tools/build.ts` drives.
  - `src/lint.ts` is every lint check; `src/availability.ts` what each
    target lacks; `src/build.ts` loads a design, selects its devices and
    resolves and lints each (`resolveAll`, the bake passed in).
  - `src/cli.ts` is `wfb` (`node src/cli.ts …`): each command's options
    are a table over `node:util`'s `parseArgs`, which also renders its
    help; `term.ts` styles the output.
  - `src/studio/` is the editor's back end: `worker.ts` (the browser's
    Web Worker, which the server bundles when it starts) answers the page's
    requests (an operation and its arguments, `app/api.ts`'s `api(op,
    args)`; no URLs) through `router.ts`, over `document.ts`, `store.ts`
    (IndexedDB, or memory in tests), `bundle.ts`, `inspect.ts` (the
    field tree from the schema, with each key's effective value and
    provenance for the editing context: frame and style, the `aod:`
    cascade included) and `drag.ts`, with `parts.ts` locating a hand's,
    pattern's or needle's parts for the tree, the entered frame and a drag;
    `document.ts`'s `EDITS` table holds
    every edit op, each one gated patch (an element key in a scope, `aod`
    among them; `move_key`, `rename_layout` and `delete_layout` beside the
    colour, scheme, slot and hand-set ops; composition is a page-side `batch`);
    `server.ts` (Node) sends the app, the devices' digest, a
    device's skin and font files, the docs for Help (`/help/`), and builds.
    `protocol.ts` is the one place the page/worker contract lives: every
    request's arguments and every answer, event and refusal as TypeScript
    interfaces, which the worker's builders return and the page imports.
    `app/` is the page: TypeScript (`main.ts` the entry, rendering `App`
    into `#app`), with Preact and htm from npm (`html` tagged
    templates, never JSX, so Node runs the sources as they are) and
    CodeMirror and marked vendored in `app/vendor/`. The server bundles
    `app/main.ts` with esbuild when it starts and serves it as
    `/dist/app.js` (`/dist/raster.js` stays a separate module the page
    imports); `/static/` serves `index.html`, `studio.css` and `vendor/`
    as files. Every module in `app/` is TypeScript, strict.
    `app/store.ts` is the editor's state: one `EditorStore` (the face,
    the selection, the editing `context`, the per-browser `view` and `ui`
    preferences it persists, the outbox's queue, the YAML tab's text and
    the frame) with the actions that change it, which `App` creates once
    and provides; a component reads the slice it needs through
    `useStore(selector)` and is rendered again only when that slice
    changes. `app/panels.ts` is the Inspector and the Face tab's shell,
    and `app/face-sections.ts` the sections over the face as a whole
    (Face, Target devices, Defaults, Layouts, the Styles matrix) with the
    `Reorder` control (↑ ↓) every ordered list of the tab shares. The outbox's order, the frame's "newest wins" and the YAML
    tab's debounced save are the store's own logic over the pure rules in
    `outbox.ts` and `textsync.ts`; the store also asks the worker for the
    selection's field tree (`inspect`) for the context and asks again when
    it changes; `hooks.ts` keeps only the hooks on the
    browser (keys, clipboard, pan and zoom). `form.ts` is the generic form
    the Inspector renders over that tree (a field by its kind: scalar,
    object, list, choice), deciding from the context where each edit lands
    (the `aod` scope in the AOD frame, Edit for's override scope for a
    geometry key), with the small controls the Face panel shares;
    `template-editor.ts` (a `text:` template as chips) and
    `condition-editor.ts` (a value that follows data as rows) are the two
    editors it hands those keys to.
    The leaf panels (`Layers`,
    `FacePanel`, `Inspector`, `Canvas`, `Strip`, `Diagnostics`) still
    take props, so a test renders one alone. `main.ts` sets `globalThis.wfbStudio =
    {api, call}`: a test hook for browser tests that drive the worker
    from the page, not an API. The page tests (`test/page-*.test.ts`,
    `test/page-harness.ts`) run the page's modules in Node by file URL
    over a minimal DOM, Preact resolved through `import.meta.resolve` so a
    test shares the page's instance, and the store alone against the
    harness's stand-in worker (`test/page-store.test.ts`);
    `test/studio-client.ts` runs the worker's router in Node for the
    studio tests.
  - `src/node.ts` hands Node's copies of what the browser hands in itself:
    the schema, the icon font's character map, and whether a font
    `source:` exists (`installAssets`, `repoFileExists`). A Node entry point
    calls `installAssets()` before it loads a design.
  - `src/edit/yaml.ts` rebuilds ruamel's composed node tree (marks, tags,
    scalar values) from the `yaml` package, and constructs the data as
    ruamel's safe loader does.
    - A mapping is a `Map`, which keeps key order where an object would
      reorder integer-like keys.
    - Offsets are UTF-16, as JavaScript slices; lines and columns count
      code points, as ruamel's do.
  - `src/edit/` is the patch engine: `spans`, `patch`, `structure`,
    `colors`, `schemes`, `hands`, `slots`, `geometry` (pixel drags, with
    the font baker passed in), and `gate`, which loads each patched text
    through `build.ts`'s `load`; `studio/document.ts` then resolves and
    lints the gated text too (`admit`), so a resolve-time error (a `pt`
    with no font in scope, a target a font has no face on) is refused as
    well, and a text that has one still reads: the resolve's throw is a
    diagnostic, never a thrown request.
  - `src/ir/` is the IR. `model.ts` keeps snake_case field names, as the
    goldens spell them; a class is built with `Class.create({...})`.
    `builder/` is the semantic pass, one layer per module, and `src/kinds/` each kind's
    `build` half, registered by importing `kinds/index.ts`.
  - `src/jsonschema.ts` is the schema validator (Draft 2020-12, no
    dependency), whose error tree, python-jsonschema's shape,
    `validate.ts` turns into diagnostics.
  - `src/py.ts` holds Python's semantics where output depends on them:
    - truthiness, `quoted` (a value as a message shows it), `str`, `==` (`deepEqual`), `json.dumps` and
      `splitlines`;
    - `f"{x:.6f}"` and `round()`, half to even, for font metrics; screen
      pixels snap half up (`roundPx` in `units.ts`), as the watch rounds;
- `src/data/` holds the tables the browser needs without a file system.
  `catalog.json`, `complications.json`, `icons.json` and
  `font-registry.json` are the source themselves; `runtime-lib.json`,
  `templates.json` and `hand-sets.json` copy `../runtime-lib/` and
  `templates/`, regenerated by `tools/export-data.ts` (`test/data.test.ts`
  fails when they are stale).
- `templates/` holds the starters `wfb new` and the editor's New offer
  (`blurbs.json` their one-line descriptions), a template's own font
  assets when it needs any (`assets/<name>/`, copied into the new face's
  own `assets/` by `wfb new` and the editor alike), and the hand presets.
- `assets/` holds the downloaded fonts, not committed: the icon font
  (`tools/fetch-icon-font.ts`) and the system-font stand-ins
  (`tools/fetch-system-fonts.ts`).
- `tools/` holds the Node tools: the three `setup-env.sh` runs
  (`extract-device-reference.ts`, `fetch-icon-font.ts`,
  `fetch-system-fonts.ts`), `fetch-sdk.ts` (the Docker image's SDK),
  `build.ts`, `goldens.ts`, `export-data.ts`, `docs-shots.ts` (the
  screenshots in `../docs/screenshots/`), `gen-profile-face.ts` and
  `summary.ts` (the page tests' face summaries).
- `test/` holds the `node:test` files (`test/CLAUDE.md`); `slow/` the
  `monkeyc` suite; `browser/` the Playwright suite over the editor's pages
  (`harness.ts` starts the server and the browser).
