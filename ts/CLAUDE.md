# ts/

Loaded automatically when working under `ts/`. The compiler is being
ported here from `wfb/`, one pipeline stage at a time. Python stays the
shipping compiler until the port is complete.

## Running it

```sh
npm test                    # node:test over test/**/*.test.ts
npm run typecheck           # tsc --noEmit, strict
npm run parity -- <stage>   # a ported stage against tools/oracle.py's dump
npm run bundle              # dist/wfb.js, the browser bundle (not committed)
```

Node runs the `.ts` sources directly (type stripping), so there is no build
step outside the browser bundle. That needs an official Node 22.18+ or 24;
`../tools/setup-env.sh` installs one when the `node` on `PATH` cannot.
`../tests/test_ts.py` runs the tests and the type check from the fast suite.

## Rules

- **Erasable syntax only** (`erasableSyntaxOnly`): no `enum`, `namespace`
  or parameter properties. Use a union of string literals for an enum, as
  the IR's `kind` fields already are.
- **Imports name the `.ts` file** (`./files.ts`), as Node's type stripping
  requires. Type-only imports use `import type`.
- **One package for the browser and Node.** Nothing reachable from
  `src/browser.ts` may import a `node:` module. Node-only code sits in its
  own module (`src/devices/node.ts`), which only Node entry points import.
- **A stage is done when parity says so.** Port a `wfb/` module into the
  matching `src/` path, register its stage in `tools/stages.ts`'s `PORTS`,
  and run `npm run parity -- <stage>`. Every difference is either fixed or
  recorded as a deliberate change, with its reason.
- **A deviation is recorded, never absorbed.** A difference the port keeps
  on purpose goes in `tools/stages.ts`'s `DEVIATIONS`, with its reason.
  Parity counts it separately.
- **Keep Python's names at the oracle boundary.** A stage's output uses the
  dump's field names (snake_case) and shapes (`tools/oracle.py`'s
  docstring lists them), so a comparison needs no mapping.
- **Never fix Python to suit the port.** A Python bug the port exposes is
  fixed in `wfb/` first, with a test, then the oracle is rerun.
- **Deterministic everywhere.** Nothing that ships or is compared may come
  from a canvas's pixels or a platform text engine: same input, same bytes,
  in every browser and in Node.
- **Comments say what the code does and why**, as in `wfb/`; which slice
  built it goes in the commit message.

## Layout

- `src/` mirrors `wfb/` module for module.
  - `src/devices/files.ts` is the `DeviceFiles` interface every stage reads
    devices through: synchronous, filled up front in the browser.
  - `src/devices/node.ts` is the same interface over the SDK's folders.
  - `src/devices/device.ts` is `Device` and `DeviceDatabase` over it; a
    database also holds the `FontFiles` its system-font metrics read.
  - `src/fonts/files.ts` is the `FontFiles` interface (the Garmin font
    root, then the registry's stand-ins), and `src/fonts/node.ts` the same
    over disk. `sfnt.ts`, `cft.ts` and `fallback.ts` read and measure the
    files; `bmfont.ts` is a baked font's data.
  - `src/layout.ts` is per-device layout; each kind's `resolve` is in
    `src/kinds/`. Trigonometry is `Math.sin`/`cos`/`atan2`, but `hypot` is
    `py.hypot`: `Math.hypot` is often a bit off Python's.
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
  - `src/ir/` is the IR. `model.ts` keeps the Python dataclasses' field
    names and order, so the oracle's dump compares field for field; a
    class is built with `Class.create({...})`. `builder/` is the semantic
    pass, one layer per module as in Python, and `src/kinds/` each kind's
    `build` half, registered by importing `kinds/index.ts`.
  - `src/jsonschema.ts` is python-jsonschema's Draft 2020-12 validator,
    ported, so `validate.ts` shapes the same error tree into the same
    messages.
  - `src/py.ts` holds Python's semantics where output depends on them:
    - truthiness, `repr`, `str`, `==` (`deepEqual`), `json.dumps` and
      `splitlines`;
    - `f"{x:.6f}"` and `round()`, half to even;
    - `PyError`, a crash Python would raise, named by type.
- `tools/` holds `parity.ts` (the runner), `compare.ts` (structural JSON
  diff), `stages.ts` (the stage table, each stage's port, and the recorded
  deviations) and `ports/` (each stage's port into the oracle's JSON form).
- `test/cases/` holds inputs the oracle dumps beside the example faces:
  `yaml/` has YAML edge cases the faces do not exercise.
- The oracle also dumps every design the fast test suite loads, captured
  by `../tools/capture_designs.py` into `../.cache/test-designs/` (load
  stages only): thousands of small faces, most written to hit one
  diagnostic. Rerun the capture when tests change, then the oracle.
- `test/` holds the `node:test` files.
