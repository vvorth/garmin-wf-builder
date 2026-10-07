# ts/

Loaded automatically when working under `ts/`. The compiler, its CLI and
the editor, in TypeScript on Node; `../wfb` runs `src/cli.ts`.

## Running it

```sh
npm test                    # node:test over test/**/*.test.ts
npm run typecheck           # tsc --noEmit, strict
npm run test:slow           # builds every slow-test design, example and fixture with monkeyc
npm run bundle              # dist/wfb.js and dist/worker.js, the browser bundles (not committed)
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
  `repr`, string formatting; the IR's snake_case field names). Keep them:
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
    (Monkey C's arithmetic: a number keeps Python's int/float split, an
    integral float being a `PyFloat`), `jsonform.ts` and `layers.ts`.
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
    requests through `router.ts`, over `document.ts`, `store.ts`
    (IndexedDB, or memory in tests), `bundle.ts`, `inspect.ts` and
    `drag.ts`; `server.ts` (Node) sends the app, the devices' digest, a
    device's skin and font files, and builds. `app/` is the page, plain ES
    modules served as they are; `test/studio-client.ts` runs the worker's
    router in Node for the studio tests.
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
    through `build.ts`'s `load`.
  - `src/ir/` is the IR. `model.ts` keeps snake_case field names, as the
    goldens spell them; a class is built with `Class.create({...})`.
    `builder/` is the semantic pass, one layer per module, and `src/kinds/` each kind's
    `build` half, registered by importing `kinds/index.ts`.
  - `src/jsonschema.ts` is the schema validator (Draft 2020-12, no
    dependency), whose error tree, python-jsonschema's shape,
    `validate.ts` turns into diagnostics.
  - `src/py.ts` holds Python's semantics where output depends on them:
    - truthiness, `repr`, `str`, `==` (`deepEqual`), `json.dumps` and
      `splitlines`;
    - `f"{x:.6f}"` and `round()`, half to even;
    - `PyError`, a crash Python would raise, named by type.
- `src/data/` holds the tables the browser needs without a file system.
  `catalog.json`, `complications.json`, `icons.json` and
  `font-registry.json` are the source themselves; `runtime-lib.json`,
  `templates.json` and `hand-sets.json` copy `../runtime-lib/` and
  `templates/`, regenerated by `tools/export-data.ts` (`test/data.test.ts`
  fails when they are stale).
- `templates/` holds the starters `wfb new` and the editor's New offer
  (`blurbs.json` their one-line descriptions) and the hand presets.
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
  `monkeyc` suite.
