# 31 — A standalone editor in the browser

**Question (user, 2026-10-05).** Can the editor run in the browser on
its own? It would write the YAML and the bundle `.zip`, and draw previews
live, all without the server. The server would keep only Monkey C codegen
and the `monkeyc` build. The browser fetches device definitions and fonts
at run time and caches them. What are the options, and what does each one
cost?

**Status (2026-10-05): C's gate passed (§3), and the user then rejected
C** as the easy route, because it keeps Pillow and FreeType as the model of
the watch. Option A is researched in research 32. The rest of this
document stands as the record of C. Decisions S2 and S3 (§6) carry over.

**Short answer.**

1. **Almost all of the compiler is the "client" half.** Everything up to
   the frame runs in the editor's loop: parse, schema, lower, desugar, IR,
   layout, lint, font baking, the draw program and the preview. That is
   about **34 000 of the 46 100 lines** in `wfb/`. The server half is
   codegen (6 400), `monkeyc` with its measurement (800), and the HTTP
   layer. So "keep Python on the server only" means re-creating most of the
   compiler in the browser (§1).
2. **The codegen needs the front half too.** `wfb/emit/` consumes the IR
   and the per-device layout, not the YAML. A Python build server re-runs
   the whole front half on whatever YAML it gets. Any option with a
   JavaScript client therefore has **two front halves**, and they must
   agree pixel for pixel and diagnostic for diagnostic (§2, option B).
3. **There is an option the question does not list: run the existing
   Python in the browser** with Pyodide (CPython compiled to WebAssembly),
   inside a Web Worker. Pyodide 314.0.7 ships every runtime dependency
   prebuilt: Pillow 12.2, ruamel.yaml, jsonschema with rpds-py, and
   fontTools. VERIFIED from its lock file. It costs about 13 MB of runtime
   to download once, a cold start of about 3 s, and roughly 2× slower
   Python (§3, measured).
4. **The gate passed.** Unchanged `wfb preview` under Pyodide renders
   every example face on every target **pixel-identical to native: 96 of
   96 images**, with identical exit codes and diagnostics. Pyodide's
   Pillow has FreeType. Overall it takes 1.34× native time, 1.7–2.1× on
   most faces (§3). VERIFIED.
5. **Chosen: C, Pyodide.** A, a full TypeScript migration, stays the
   fallback, and is the only other option with one implementation. **B,
   a JavaScript client with a Python server, was rejected.** It doubles
   the hardest code and makes the two copies agree only by testing.

---

## 1. What the browser would have to do

From `docs/development.md` "Pipeline", split by where the standalone
editor needs each stage:

| Stage | Module | Lines (approx.) | Needed in the browser? |
|---|---|---:|---|
| YAML with source spans, round-trip edits | `yamlsrc.py`, `wfb/edit/` | ~4 000 | **yes**: every edit is a patch that keeps comments |
| JSON Schema, reported on author lines | `validate.py` + `schema/` | ~950 | **yes**: the gate refuses a bad edit |
| lower, desugar, IR, catalog, expressions | `lower.py`, `desugar.py`, `wfb/ir/`, `catalog.py`, `expr.py` | ~6 500 | **yes** |
| per-device layout | `layout.py`, `devices.py`, `availability.py`, `units.py` | ~4 000 | **yes**, from device files |
| lint | `lint.py` | 2 570 | **yes**: the diagnostics panel |
| font baking, system/vector fonts | `wfb/fonts/`, `icons.py` | ~2 400 | **yes**: text is drawn from the baked sheets |
| draw program, evaluator, preview | `wfb/draw/`, `preview.py`, `aod_mask.py` | ~6 100 | **yes**: the live preview |
| element kinds (their lower *and* emit parts) | `wfb/kinds/` | 5 100 | mostly yes |
| editor state: history, snapshots, bundle | `wfb/studio/{document,store,bundle}.py` | ~2 000 | **yes** (moves to IndexedDB) |
| Monkey C, resources, manifest, jungle | `wfb/emit/` | 6 400 | no: server |
| `monkeyc`, signing, `--build-stats` | `build.py` | ~800 | no: server (Java + SDK) |

The browser half is about **34 000 lines of Python**, held by most of the
**53 000 lines of tests**. The editor's existing JavaScript (4 700 lines:
Preact, CodeMirror, `raster.js`, `hit.js`, `snap.js`) is UI. It already
calls the server for every frame, drag, edit, undo and inspection
(`wfb/studio/app.py`, 30 routes).

### What the browser fetches at run time

| Asset | Per device / total | Source | Notes |
|---|---|---|---|
| `compiler.json`, `simulator.json` | 7 KB + 109 KB (fr955) | `~/.Garmin/ConnectIQ/Devices/<id>/` | limits, shape, fonts, palette |
| `<id>.api.debug.xml` | 1.6 MB (fr955) | same | symbol availability (constraint 6). It can be reduced on the server to the symbols `availability.py` asks about |
| skin `<id>.png` | 88 KB (fr955) | same | the bezel |
| device reference | 5.3 MB for all 164 | `.cache/device-reference/` | can be served per device |
| system fonts (`.cft`/`.ttf`) | 547 MB in the store; a face needs a few | `~/.Garmin/ConnectIQ/Fonts/` | only the fonts a device's `simulator.json` names |
| Nerd Fonts icon font, free font stand-ins | small | `wfb/assets/icons/`, `registry.json` | free licences |

All of these are content-addressable, so the Cache API or IndexedDB can
keep them keyed by SDK version and hash. One device costs about 2 MB,
before fonts. VERIFIED (sizes measured on this machine).

**Licensing caveat.** The device definitions and Garmin's fonts are the
user's licensed SDK copy (`vendor/devices/` is gitignored for that
reason). If the user's own server sends them to the user's own browser,
that is the same personal use as today. **A public server that sends them
to anyone would be redistribution.** That would push toward a
bring-your-own-SDK upload in the browser, whatever architecture is chosen.

## 2. The options

### A. Everything in TypeScript: the browser holds the compiler, and the server is a thin `monkeyc` runner

- **What:** port the whole compiler to TypeScript, codegen included, and
  reverse ADR 0001. Then the browser can produce the complete Monkey C
  project, and the server only runs `monkeyc` on the project it receives,
  with no knowledge of faces. The server could even be optional: the user
  runs `monkeyc` locally.
- **Libraries:**
  - `yaml` (eemeli) has a CST with source ranges and preserves comments,
    so it can stand in for ruamel's round-trip;
  - `ajv` for the schema;
  - `fontkit` or `opentype.js` for fontTools;
  - Pillow has **no equivalent**. The preview's rasteriser (`raster.js`,
    plan 28, already a partial port) would have to cover every primitive,
    plus FreeType-style glyph rendering for baking, which means FreeType
    compiled to WebAssembly or a JS rasteriser. Baked sheets would no
    longer be Pillow's output, so `.prg` resources would change, and every
    golden file would be re-blessed.
- **Pros:** one language and one implementation, front to back. The
  browser is fast and native (no runtime to download), with the best
  debugging and tooling for the UI. The server becomes trivial and
  stateless.
- **Cons:**
  - The largest cost: about 40 000 lines plus about 53 000 lines of
    tests, rewritten.
  - The ported compiler must be proven equal to the Python one before the
    Python one is deleted. `tools/snapshot.py` can compare emitted
    projects, and `jsonform.rasterise` can compare pixels, but every
    "measured" claim in `docs/` would be re-measured.
  - The CLI (`wfb build`, `preview`, `simulate`) becomes Node.
  - The project would be frozen for the length of the migration.

### B. A JavaScript client half plus the Python server (the question's second option)

- **What:** port the browser half in §1 to JS, and keep Python for codegen
  and build. The server re-runs its own front half on the YAML it
  receives, as it must (finding 2).
- **Pros:** the backend and CLI stay as they are, and the browser is fast
  and native.
- **Cons:**
  - **Two implementations of the 34 000 lines that change most.** Every
    new feature, kind or lint is written twice.
  - Disagreement is silent. The preview could say one thing while the
    built `.prg` does another, which is exactly the class of bug the
    single draw program (plan 26) was built to remove.
  - Agreement needs a cross-language conformance suite over the corpus:
    layout constants, draw JSON, pixels and diagnostics. That is `raster.js`'s
    Node contract test, generalised to everything.
- **Variant B′, a thin client:** port only the drawing (the JSON
  rasteriser, already started) and keep parse, layout and lint on the
  server. This is today's editor plus plan 28. It is cheap, but **it does
  not meet the goal**, because every edit still needs the server.

### C. The same Python, run in the browser by Pyodide (recommended)

- **What:**
  - `wfb` runs unchanged in a Web Worker under Pyodide. The JS UI stays as
    it is, but it calls the worker instead of `fetch("/api/…")`.
    `document.py`'s operations (edit, drag, undo, frame, layers, inspect)
    become worker messages.
  - History and snapshots move from `store.py`'s directories to IndexedDB,
    behind the same journal format.
  - The bundle `.zip` is written by `bundle.py` with `zipfile`, in the
    worker.
  - The server keeps:
    - the static files;
    - `GET /devices/<id>` and `GET /fonts/<name>`, cacheable and immutable;
    - `POST /build`, which takes the bundle zip and returns the `.prg`
      files plus `--build-stats` diagnostics. It runs the same `wfb build`
      the CLI does.
- **Pros:**
  - **One codebase, no port**, and the preview is pixel-identical to the
    build server *by construction*, because it is the same code.
  - ADR 0001 and every test keep holding; the CLI is untouched.
  - The server shrinks to stateless endpoints. The sessions, claims,
    locks and event stream (`sessions.py`, `/api/events`) go away.
  - Plan 28's JS rasteriser keeps its job: drawing during a gesture with
    no round trip, now to a worker instead of the network.
- **Cons:**
  - **Download:** `pyodide.asm.wasm` 9.2 MB, `python_stdlib.zip` 2.5 MB
    and `pyodide.asm.mjs` 1.2 MB, uncompressed, plus the Pillow, rpds-py
    and pure-Python wheels and `wfb` itself. VERIFIED for the runtime
    files; package sizes UNVERIFIED. All of it is cached after the first
    visit, and a service worker can make it work offline.
  - **Cold start:** 2.8 s for `loadPyodide()` with no packages, in Node.
    Importing Pillow and `wfb` adds more (UNVERIFIED). A warm start from
    cache is smaller, and the UI can draw from the last frame while it
    loads.
  - **Speed:** ruamel's round-trip parse of the showcase takes **203 ms
    under Pyodide against 101 ms native**, so about 2×. Research 29
    table D puts the showcase's load at 227 ms native, so expect
    450–500 ms per release on the largest face. Small faces take tens of
    ms. Research 29 §6 (incremental validation, skipping a full reload
    for a scalar) becomes worth doing.
  - **Unverified risks:**
    - whether Pyodide's Pillow build includes FreeType
      (`ImageFont.truetype`, needed for baking and vector text);
    - Pillow 12.2 against the 12.3 that is pinned in practice, which a
      pixel test would catch;
    - memory use in the worker on the larger faces.
  - **Packaging:** Pyodide is vendored as prebuilt files, consistent with
    the editor's no-build-step rule (`wfb/studio/static/vendor/`). Upgrades
    are deliberate.
  - Python stack traces from inside WebAssembly are harder to debug than
    native ones.

### D. Rejected

- **Transpiling Python to JS** (Transcrypt, Brython): these tools cannot
  carry ruamel, Pillow, jsonschema or fontTools. Rejected.
- **A shared core in Rust**, compiled to WebAssembly for the browser and
  to PyO3 for the CLI: it gives one implementation, at a cost larger than
  A, in a language the project does not use. Rejected unless A's
  performance turns out insufficient, which nothing suggests.

## 3. Measured

Probe: `docs/research/probes/standalone-browser/`, with all numbers in
`results.txt`. `probe.mjs` times the parse. `parity.mjs` runs `wfb
preview` in Pyodide, and `native.py` runs it natively. `compare.py`
compares their PNGs pixel by pixel, along with exit codes and stderr.
Setup: a Linux container, Node 22, pyodide 314.0.7 (CPython 3.14.2,
Pillow 12.2.0), against native CPython 3.14.4 (Pillow 12.3.0). The
repository and `$HOME` are mounted at their own paths, so the compiler
reads the same device files, fonts and caches.

**Parity: 96 of 96 preview PNGs pixel-identical** (29 faces, every target,
`examples/dashboard` excluded). Exit codes and every diagnostic match too.
Pyodide's Pillow reports `freetype2: true`, so TTF baking and vector text
work. Pillow 12.2 against 12.3 made no difference on this corpus. VERIFIED.

| | Pyodide | native |
|---|---:|---:|
| `loadPyodide()`, cold | 2 890 ms | — |
| load the packages (cached / first fetch) | 497 / 1 436 ms | — |
| `import wfb.cli` | 1 658 ms | 1 385 ms |
| ruamel round-trip parse, showcase | 203 ms | 101 ms |
| `wfb preview`, all 29 faces | 15 586 ms | 11 643 ms (×1.34) |
| … a typical face (`features/gauge`) | 284 ms | 143 ms |
| … `showcase` (3 targets) | 2 127 ms | 2 525 ms |

- **Most faces run 1.7–2.1× slower.**
- **Faces heavy in vector text run at about native speed or faster**
  (`showcase`, `trail-utility`, `features/outline`: 0.8–0.9×). The cause
  is UNVERIFIED. Those faces spend their time in Pillow's C code
  (rotating and downsampling runs), which WebAssembly runs close to
  native.
- **A cold start costs about 5 s** (runtime, packages, then `wfb`),
  before the first frame.

**Payload over the wire, first visit (compressed):**
- `pyodide.asm.wasm`: 3.4 MB;
- the stdlib: 2.5 MB;
- Pillow: 1.0 MB;
- fontTools: 1.1 MB;
- the rest of the wheels: about 0.3 MB;
- `wfb` itself: 2.1 MB uncompressed.

That is **about 9–10 MB once**, cached afterwards. VERIFIED.

**Not covered by the probe:**
- a real browser: this was Node, the same WebAssembly engine as Chrome;
- memory in a worker;
- the editor's operations (edit, drag, undo) as opposed to `wfb preview`;
- fetching device files over HTTP rather than mounting them.

Slices 2–3 meet each of these.

## 4. Comparison

| | A. all TypeScript | B. JS client + Python server | C. Pyodide |
|---|---|---|---|
| implementations of the front half | 1 (TS) | **2** | 1 (Python) |
| preview equals build | by construction | by conformance tests only | by construction |
| port size | ~40 k lines + tests | ~34 k lines + a conformance suite | ~2 k (state to IndexedDB, routes to worker messages) |
| first load | small | small | ~13 MB+ once, then cached |
| edit latency on the showcase | fastest (native JS, UNVERIFIED) | fastest | ~2× today's server load, with no network |
| server | `monkeyc` runner, stateless | full Python compiler | full Python compiler, stateless |
| CLI | becomes Node | unchanged | unchanged |
| ADRs touched | 0001 reversed; 0003 restated | 0003 (two pipelines) | 0003 amended (where the pipeline runs) |
| risk | long freeze; re-measuring everything | silent drift | Pillow/FreeType under Pyodide; start-up and speed |

## 5. If C: slices

1. **Probe (the gate).**
   - Load `wfb` and its wheels in Pyodide.
   - Run `build.load` → layout → `preview.render` for every example face
     on the three verification devices, from device files fetched over
     HTTP.
   - Compare the pixels with native output, and record cold and warm
     start, payload and per-stage timings against research 29 table D.
   - If FreeType is missing, or the pixels differ in a way that cannot be
     fixed, stop and fall back to A.
2. **Worker and assets.**
   - The worker host, a device and font fetch API on the server, and a
     Cache API store keyed by SDK version.
   - `devices.py` and `wfb/fonts/` read from the worker's virtual
     filesystem, so no compiler change is expected.
3. **Documents client-side.** `document.py`'s operations become worker
   calls, `store.py`'s journal moves onto IndexedDB, and bundle
   upload and download happen in the browser.
4. **Server shrinks.**
   - Add `POST /build` (bundle in; `.prg` files and memory diagnostics
     out).
   - Remove sessions, claims, locks and the event stream.
   - `wfb studio` serves the static app plus these endpoints.
5. **Optional:** offline (a service worker) and bring-your-own-SDK (upload
   the device folder into the browser cache instead of fetching it from
   the server).

## 6. Decisions for the user

| # | Decision | Options | Recommendation |
|---|---|---|---|
| S1 | Architecture | A all TypeScript · B JS client + Python server · C Pyodide | **C**, gated on slice 1; **A** if the gate fails |
| S2 | Where documents live | browser only (IndexedDB) · browser plus optional server sync | **browser only** first, with the bundle `.zip` as the way to move a face between machines |
| S3 | Device and font delivery | the user's server sends them · the browser imports them from the user's SDK folder · both | **the server sends them** (personal use, as today), with import kept for any public deployment (§1 licensing) |
| S4 | Network approval for the probe | allow `cdn.jsdelivr.net` · vendor Pyodide's full release from GitHub | allow it for the probe; vendor the release for the build itself |

**Decided by the user, 2026-10-05:**
- S1: test C first, with A as the expected fallback. The gate passed (§3),
  but **C was then rejected** in favour of researching A (research 32).
- S2: browser only to start, with server storage and sync to be developed
  later. The journal format therefore stays one that a server can replay.
- S3: the server sends device files and fonts.
- S4: `cdn.jsdelivr.net` allowed.

## Sources

- `wfb/` line counts (`find wfb -name '*.py'`), `docs/development.md`
  "Pipeline", `wfb/studio/app.py` (routes), `wfb/studio/store.py`,
  `wfb/studio/bundle.py`.
- Research 29 (table D: the load by stage; §4: the Pyodide row; §6),
  research 27 §5.3, plan 26 (the single draw program), plan 28 (the JS
  rasteriser).
- `pyodide@314.0.7` from npm: `pyodide-lock.json` (package versions),
  file sizes; its packages from `cdn.jsdelivr.net/pyodide/v314.0.7/full/`.
- Device files: `~/.Garmin/ConnectIQ/Devices/fr955/`,
  `~/.Garmin/ConnectIQ/Fonts/`, `.cache/device-reference/`.
