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
- `tools/` holds `parity.ts` (the runner), `compare.ts` (structural JSON
  diff) and `stages.ts` (the stage table and each stage's port).
- `test/` holds the `node:test` files.
