# 26 — A visual editor: placing elements, a live layered preview, save and build

**Question (user, 2026-10-01).** What would a GUI for this builder take? It
should place items visually, show a live, layered preview, save the YAML,
build, and so on. A web interface is preferred, but other options are open.

**Short answer.** It is buildable now, and three findings decide its shape.
The recommendation is a local web app served by `wfb` itself (`wfb studio`):

1. **Edits must be text patches, never a re-dump.** A ruamel round trip
   (`load` → `dump`) reproduces **0 of 29** example faces byte for byte, even
   tuned the way `wfb migrate` tunes it. A patch that rewrites only one
   scalar's characters, located by the parser's own marks, changed exactly
   one line in **77 of 77** edits, and every edited element moved as
   expected on the device (§3.2, §3.3). VERIFIED.
2. **The preview is fast enough to be the live view.** A one-element edit
   re-runs the whole pipeline in **35–50 ms** for a typical face and about
   **1 s** for the 963-line showcase. Most of the showcase's second is font
   baking, which an editor session can cache (§3.1). VERIFIED (timing). The
   cache saving is UNVERIFIED.
3. **The browser never draws the face.** `wfb/preview.py` stays the only
   host renderer, which keeps ADR 0004's anti-drift guarantee. The browser
   draws only selection boxes, handles and guides, all taken from the
   compiler's resolved geometry (`Placed.box`/`center`). Research 06 §6
   argued this; nothing found here weakens it.

A drag must patch whichever geometry applies on the device being viewed,
which may be an `overrides:` entry rather than the element's own key
(§4.4). Five decisions are the user's (§8), one of them whether plan 19's
"single draw program" comes before the layered canvas. Nothing is built
yet.

---

## 1. What changed since research 06

Research 06 (2026-09-12) recommended deferring a GUI "until the schema stops
moving", on two measured costs:

- the **third-renderer problem**: a GUI drawing its own canvas breaks the
  guarantee that preview and device agree;
- **schema churn**: the element vocabulary was about to grow from 6 to 9
  kinds.

Since then:

| Then | Now |
|---|---|
| 6 element kinds, 3 more planned | 14 element `type:`s in format 2 (`arc`, `circle`, `data`, `ellipse`, `gauge`, `graph`, `group`, `hands`, `icon`, `line`, `pattern`, `polygon`, `rectangle`, `text`), each in its own `wfb/kinds/` module |
| format 1, migration pending | format 2 (2026-09-28): "one designed revision", with its reserved vocabulary already named (`docs/limitations.md` §2) |
| config axes, overrides and interactivity unbuilt | all four `config:` axes, Styles `layouts:`, `on_hold:`, `aod:`, screen shapes and geometry `overrides:` (per device id and per `shape:`) are built |
| preview fidelity was the weak link (system fonts drew as boxes) | fixed by plans 09, 12 and 17: real metrics, real or free stand-in glyphs, and a stand-in warning |
| no `--watch` | `wfb preview --watch` re-renders on save |
| the sketch skill was the next step | built, then deleted at the user's request (research 06 §9 note) |

ADR 0002's precondition ("once the schema has stabilised") is as close to
met as it will get. Format 2 was designed to be the stable revision. Its
open vocabulary is reserved by name, so an editor can treat a reserved key
like any other unknown key: preserve it, don't edit it. The schema-churn cost
is also mostly avoidable, because the inspector can be generated from the
schema (§4.6) rather than hand-built per property.

## 2. Requirements

What the user asked for:

| # | Requirement |
|---|---|
| R1 | place elements visually: select, drag, resize |
| R2 | a live preview that is **layered**: the element stack is visible, and each element can be shown, hidden and selected |
| R3 | save the YAML |
| R4 | build: the signed `.prg` and the measured memory figure |
| R5 | "etc." Read as the rest of today's CLI loop: diagnostics, device, style, time, AOD and skin |

Inherited constraints, none of them negotiable without an ADR amendment:

| # | Constraint | Source |
|---|---|---|
| C1 | YAML is canonical. The editor must round-trip losslessly (key order, comments, anchors, unknown keys) and be property-tested: a no-op save is byte-identical, and an edit changes only the edited region | ADR 0002 |
| C2 | whichever element spelling the file uses (the mapping form, or a list) is kept | ADR 0002 amendment |
| C3 | nothing is expressible only through the GUI | ADR 0002 |
| C4 | exactly two renderers: device Monkey C and `preview.py` | ADR 0004, research 06 §6 |
| C5 | a drag must not silently rewrite a proportional length as pixels | research 06 §4 |
| C6 | runs on a macOS host and in the Linux container (`docs/container.md`) | root `CLAUDE.md` §1 |
| C7 | the simulator cannot be driven (it segfaults when `monkeydo` pushes an app), so "run it" means build and sideload | root `CLAUDE.md` §3 |

C6 is the constraint that decides web over desktop (§5). The container has no
display, and a browser on the host can reach a port the container publishes.

---

## 3. Experiments

Run with `docs/research/probes/gui-editor/probe.py`. Raw output is in
`results.txt` beside it. Every example face is used except
`examples/dashboard` (the user's playground), which leaves 29.

### 3.1 Latency: can the real pipeline be the live view?

The full in-process pipeline was timed on `fenix8solar47mm` at 2×. Load
covers parse, schema, lower, desugar and IR; resolve covers font bake,
layout and lint. Warm runs only, in milliseconds:

| Face | Lines | load | resolve | render | **total** |
|---|---:|---:|---:|---:|---:|
| `features/progress` | 103 | 28–42 | 1 | 5 | **34–47** |
| `features/styles` | 196 | 38–43 | 1–2 | 5–6 | **44–50** |
| `features/vector-text` | 226 | 43–53 | 82–120 | 154–168 | **291–337** |
| `showcase` | 963 | 287–406 | 539–716 | 7–10 | **953–1026** |

Importing `wfb` costs about 2 s once, and a face's first resolve costs up to
about 0.4 s more than a warm one. A long-lived server pays both once per session.

**Where the showcase's second goes.** A cProfile run splits it into three
parts. `bake_fonts` takes about 0.59 s (14 TTF bakes, 122 glyph-run
rasterisations). The ruamel parse takes about 0.25–0.4 s, and jsonschema
validation about 0.4 s under the profiler. A drag changes none of the bake's
inputs (font source, size, glyph set, device), so a server can memoise
`bake_fonts` on those plus the font file's mtime. That should bring the
showcase under 0.5 s per edit. That figure is UNVERIFIED; it is the first
thing a prototype should measure. `vector-text` is dominated by drawing
vector text, which caching does not help.

**Consequence.** For typical faces the authoritative re-render is fast
enough to run on every keystroke (debounced) and on every drop. It is *not*
fast enough to follow the pointer at 60 Hz on large faces, so a drag needs
a client-side stand-in while the pointer moves (§4.3).

### 3.2 Round trip: can the editor load the file, change it and dump it?

No. A ruamel `load` → `dump`, which is what `yamlsrc` would naturally offer
an editor, reproduced **0/29** faces byte for byte with defaults. It still
reproduced **0/29** when tuned as `wfb migrate` tunes it: the file's own
sequence indent, `preserve_quotes`, and no line folding. What changes:

- flow-mapping spacing: `{ anchor: center }` → `{anchor: center}`, the
  spaced style the examples use throughout;
- comment alignment after flow sequences;
- in one case, a flow sequence's single-pair mapping re-spelt as a compact
  pair (`[{ dy: -7%r }]` → `[dy: -7%r]`). That is legal YAML, but it is not
  what the author wrote;
- the change count ranges from 6 lines (`features/sun`) to 364 (`showcase`).

`wfb migrate` already shows how much code it takes to push a re-dump back
toward the original layout (`_SpacedBraceEmitter`, `_match_layout`, the
comment-carrying helpers). Even that is good enough only for a one-off
migration, not for an editor that saves hundreds of times. **C1 cannot be met
by re-dumping.** VERIFIED.

### 3.3 Span patches: rewrite only the characters that changed

ruamel's composer (`YAML().compose`) returns a node tree where every scalar
carries `start_mark.index`/`end_mark.index`, its exact character range in
the file. The `lc` positions `yamlsrc` already uses for diagnostics give only
a start. The experiment did the following for up to three elements per face:

1. found the element's `at.dy` scalar node;
2. replaced exactly `text[start:end]` with the value + 10 **in the author's own
   unit**, keeping quotes if the author used them;
3. re-ran the full pipeline on the patched text and compared the element's
   resolved centre before and after.

| Measure | Result |
|---|---|
| edits (by unit: 41 `%`, 27 `%r`, 9 `px`) | 77 |
| diff is exactly one changed line | **77/77** |
| the element moved down on the device, x unchanged | **77/77** |

VERIFIED. This is the editing primitive. By construction it leaves every
byte outside the edited span alone, which is exactly ADR 0002's "differ only
in the edited region". It is also indifferent to the mapping or list form
(C2), because it never re-serialises structure.

**Edits a scalar patch does not cover**, and the primitive for each. All are
still text operations at element granularity, so comments travel with their
lines:

| Edit | Primitive | Status |
|---|---|---|
| change a value | scalar patch (above) | VERIFIED |
| add a key that is absent (`dx` where only `dy` is written) | insert `, dx: 3%r` before a flow mapping's closing `}`, or a new line at the block mapping's indent after its last key | UNVERIFIED, mechanical |
| remove a key | delete the key's span, including its separator or line | UNVERIFIED |
| add an element | insert a generated block, written in the file's own form and indent, at the end of `elements:`, or after the selection | UNVERIFIED |
| delete, duplicate, reorder an element | move, copy or delete the element's whole line range: leading comments, the key, and its body | UNVERIFIED |

Each must be gated by re-parsing the result before it is accepted. A patch
that fails to parse, or that changes the parsed data anywhere else, is
rejected, so a patch bug can only fail loudly. ADR 0002's property tests run
over the whole example corpus: a no-op is byte-identical, and every patch
equals the expected parsed change with nothing else differing.

---

## 4. Architecture

```
 browser (thin client)                     wfb studio (Python, in-process)
 ┌───────────────────────────┐   HTTP     ┌──────────────────────────────────┐
 │ text pane (CodeMirror,    │──patch────▶│ document: the file's TEXT + version│
 │  schema completion)       │◀─text/ver──│  span index (compose marks)       │
 │ canvas: <img> per layer   │            │ pipeline: load → resolve → lint   │
 │  + SVG overlay (handles)  │◀─PNG───────│ preview.render (the only renderer)│
 │ layers · inspector · lints│◀─geometry──│ Placed boxes, ids, order, hidden  │
 │ build panel               │◀─SSE log───│ build: `wfb build` subprocess     │
 └───────────────────────────┘            │ file watch: external edits        │
                                          └──────────────────────────────────┘
```

### 4.1 The server owns text, not a model

The source of truth in memory is **the file's text plus a version number**.
That is ADR 0002 taken literally. Every edit, whether from the canvas, the
inspector or the text pane, is a patch to that text. The server re-runs the
pipeline on the result. Three consequences follow:

- **External edits are first-class.** If the file changes on disk (the user
  in VS Code, Claude in a session, `git checkout`), the server reloads it and
  bumps the version. A patch sent against a stale version is rejected, and
  the client refreshes. The `--watch` polling loop in `wfb/cli.py` already
  does the watching part.
- **Undo is uniform.** Every change is a text transaction, so the text
  pane's own history is the undo stack. A canvas drag is undone with Ctrl-Z
  like typing.
- **Save is a file write of text the user can already see**, with nothing
  hidden in between.

### 4.2 What the server exposes

Everything below already exists as a Python function. The server is glue:

| Endpoint | Backed by | Notes |
|---|---|---|
| render a frame | `wfb.build.load`, `resolve_all`, `wfb.preview.render` | `PreviewOptions` already has every view switch: `scale`, `quantise`, `mask_shape`, `style`, `time`, `asleep`, `aod`, `skin`, `sample`, `fonts_root`. Also `render_all_styles` and `render_aod_heatmap` |
| geometry | `ResolvedFace.items` / `shown_items` / `hidden` | per element: id, kind, `box`, `center`, `depth`, draw order, `layout`, why it is hidden. Plus the element's author span, from the span index |
| diagnostics | `Bag` | every diagnostic already carries file/line/column (ADR 0002) and a fix. The text pane shows them in the gutter, the canvas outlines the element |
| devices | `DeviceDatabase`, `select_devices` | targets, plus any installed device to try |
| sources, icons, palette | `wfb.catalog`, `wfb/icon_catalog.py`, `wfb.palette` | pickers for `{source}` placeholders, `icon:` and colours (MIP-64 snap, research 06 §6) |
| build | `wfb build` as a **subprocess** | streams the log; returns the `.prg` paths and the measured memory per device. A subprocess keeps a `monkeyc` hang or crash out of the editor |
| events (SSE) | — | re-render finished, file changed on disk, build progress |

The Python standard library (`http.server.ThreadingHTTPServer`) is enough
for all of it. Server-sent events are plain HTTP. **A web framework is not
required**, and `requirements.txt` stays at its four packages. Starlette and
uvicorn would be the step up if WebSockets ever become necessary. Nothing
here needs them.

### 4.3 The live, layered preview (R2)

**Layers are the document's element tree**, in draw order: document order
and `z:`, `static:` first, groups as folders. A Styles `layouts:` entry
filters it the way `render` already does. The layer panel is therefore the
file's own structure, not a separate model.

Two ways to make the canvas layered:

| | (a) one composited frame + SVG overlay | (b) one transparent PNG per element |
|---|---|---|
| preview change | none | `render` grows an "only these elements, on a transparent ground" mode; quantise and mask still run on the composite |
| show/hide/solo a layer | re-render without it (35–50 ms on typical faces) | toggle an `<img>`, instantly |
| drag feedback | the selection box moves; the element's pixels stay put until the drop | the element's own pixels move with the pointer (a pure translation is exact until the drop's re-render) |
| hit-testing | `Placed.box`. Coarse: a ring's box is the whole dial, and a full-screen background swallows clicks | the layer's alpha: pick the topmost element with an opaque pixel under the pointer |
| caveats | — | **group `outline:`** stamps every member's ring before any member (research 19, `ring_groups`), so an outlined group must be one layer. Quantising per layer and then compositing differs from quantising the composite only where layers overlap with anti-aliasing |

**Recommendation: ship (a) first, then add (b).** (a) needs no change to
`preview.py` and is already a useful editor. (b) is what makes the preview
feel layered and makes dragging feel direct. It is a contained change to
`Renderer.render_sequence` (it already draws one element at a time), plus a
test that compositing the per-element layers equals the single-frame render
wherever no anti-aliased edges overlap. Whether that equality holds tightly
enough is UNVERIFIED, and it is (b)'s first measurement.

**Both keep C4.** The browser composites PNGs that `preview.py` drew. It
never rasterises a watch-face element itself.

### 4.4 Direct manipulation without breaking proportions (R1, C5)

Research 06 §4 named the hazard: a drag yields pixels, and the format's value
is proportional. The fix that §3.3 makes cheap is to **convert the pixel
delta into the field's own unit, on the device being viewed, and patch only
the number**. Every unit is linear in pixels (`wfb.units.Length.resolve`),
so the conversion is a division:

| Authored unit | Δvalue for a Δpx drag |
|---|---|
| `px` (or a bare number) | Δpx |
| `%` | Δpx ÷ parent extent on that axis × 100. The parent is the screen, or the enclosing group's box |
| `%r` | Δpx ÷ the screen's minor radius × 100 |
| `pt` | Δpx ÷ the element's font pixel height |
| polar `at: {angle, radius}` | the drag is re-expressed about the anchor: Δangle in degrees, Δradius in the radius's own unit |

The result is rounded to a precision that still resolves to the dragged
pixel on the viewed device: 0.1 for `%`/`%r`, 1 for `px`, 0.5° for angles.
`align:` and the anchor are never changed by a drag; they are inspector
choices. A field the author never wrote (dragging horizontally when only
`dy:` exists) is added in the unit its sibling uses, or `%r` on its own.
`%r` is the format's own advice for round designs (`docs/guide/placement.md`).

**A drag edits the geometry that applies on the viewed device.** An
element's `overrides:` maps a device id or `shape:<…>` to a patch of its
`at:`/`size:`/`radius:`/`align:`, deep-merged over the element's own keys,
a device id's patch over its shape's (`docs/guide/placement.md`). If the
viewed device's merged geometry takes the dragged field from an override,
patching the element's own key changes nothing on screen. The patch target
is therefore the most specific source of that field for the viewed device:
the device-id patch, else the shape patch, else the element's own key. The
inspector offers the choice explicitly, as "all targets" (the element's own
key; an override that shadows it is shown, not silently left winning) or
"this device" / "this shape" (adds or edits the override entry, a
structural patch, §3.3). The span index has to map each override field to
its author node as it does the element's own keys. The probe ran before
`overrides:` existed and no example face uses it, so this path is
UNVERIFIED.

**A drag is relative, and the editor shows that.** Because a `%r` value
lands at different pixels on the 47 mm and the 51 mm, the canvas can show
all the face's targets side by side, as small live thumbnails beside the
main view. The author then sees the cross-device consequence of every drop.
That makes research 06's "the format's hardest concept" something the user
can see instead of a hidden trap.

Resize handles apply the same rule to `size:`, `radius:` and `thickness:`.
Arcs get angle handles for `start_angle:`/`sweep:`, and hands and patterns
are edited in the inspector. Snapping targets are the screen centre, other
elements' centres and edges, a `%r` grid, and 6°/30° angles.

### 4.5 The text pane

The text pane is CodeMirror 6 with `codemirror-json-schema`'s YAML mode, or
Monaco with `monaco-yaml`. Either gives completion, hover docs and inline
validation from `schema/wfb-face-2.schema.json`, the same experience the
modeline gives in VS Code. The schema is JSON Schema 2020-12.
yaml-language-server, which `monaco-yaml` wraps, supports 2020-12 since
1.20.0. UNVERIFIED for `codemirror-json-schema`, whose README names Draft 04
and 07. If it rejects the dialect, Monaco is the fallback.

The schema pane only *assists*. `wfb`'s own diagnostics stay authoritative
and are shown as well, because they carry the platform facts the schema
cannot know (palette, memory, burn-in, per-device availability).

Text-pane edits are debounced (about 300 ms) and sent as a whole-text
replace. Canvas-originated patches come back as minimal changes, so the
cursor and the undo history survive.

### 4.6 The inspector, generated from the schema

The inspector lists the selected element's properties. **It is generated from
the element's schema branch** (`$defs/<kind>Element`, selected by `type:`),
not hand-built per property. That answers research 06's churn argument: a new
key in the schema appears in the inspector with no GUI change. Special
widgets, keyed on the schema's `$ref` names, cover the few types that
deserve them:

- `length` (number + unit, unit preserved);
- `angle`;
- `color`/`colorExpression` (palette or theme swatches, legal MIP-64 only,
  or a free expression);
- `expression` (a text field with source completion from `wfb.catalog`).
  A `text:` template may hold several placeholders, each its own reading,
  so completion works per placeholder, not per field;
- `font`;
- `align` (a 3×3 picker);
- icons (the Nerd Fonts catalogue).

Anything else is a plain text field whose value is written verbatim. The
inspector never rewrites a value the user did not touch.

### 4.7 Build (R4)

The build button runs `wfb.py build <file>` in a subprocess and streams its
log over SSE. When it finishes it shows each target's `.prg` (downloadable)
and measured memory against `Device.watchface_memory_limit`. The preview
cannot run the face on a simulator (C7). Sideloading stays manual: copy the
`.prg` to `GARMIN/APPS` on the watch. Automating that is `wfb install`,
which is separately unbuilt (`docs/limitations.md` §2).

### 4.8 Security and running it

- Bind `127.0.0.1` by default. In the container, bind `0.0.0.0` and publish
  only to the host's loopback: `docker run -p 127.0.0.1:8765:8765 …`.
- File access is limited to the opened design's directory, with no
  arbitrary path reads. The server runs `monkeyc` and writes files, so it
  must never be reachable from the network.
- No accounts and no persistence beyond the YAML file itself and the usual
  `build/` output.

---

## 5. UI technology: the options

| Option | Fits C4 (two renderers) | Fits C6 (container) | Direct drag quality | New dependencies | Verdict |
|---|---|---|---|---|---|
| **A. Local web app, custom**: stdlib server + a static, no-build-step front end | yes | yes (browser on the host) | best: drag runs in the browser, the server only on drop | none in Python; front-end files vendored | **recommended** |
| **B. NiceGUI** (Python-only UI; FastAPI + Vue underneath) | yes | yes | fair: `ui.interactive_image` gives an SVG overlay and mouse events, but each event goes to the server, so a smooth drag needs custom JS anyway | FastAPI, uvicorn, python-socketio and their dependencies | good for a throwaway prototype; ends up as A with more dependencies |
| **C. Streamlit / Gradio** | yes | yes | poor: Streamlit re-runs the whole script on each interaction, and neither has a native drag canvas | heavy | rejected |
| **D. Desktop Qt (PySide6)**: `QGraphicsView` is an excellent layered canvas | yes | **no**: the container has no display, so it would need X forwarding or VNC | best | PySide6, a few hundred MB | rejected as primary; fine later on the macOS host if wanted |
| **E. VS Code extension** (webview preview beside the editor's own YAML) | yes | yes (Remote/Dev Containers) | good | a TypeScript/Node toolchain; ties the tool to VS Code | a good second front end later: A's server and front end can be hosted in a webview unchanged |
| **F. Tauri/Electron wrapper** around A | yes | — | as A | Node or Rust toolchains | not needed: a browser tab already does it |

**Front-end tooling within A** (decision D3). The choice is between:

- **no build step**: vendored ES modules (Preact + `htm` for components, a
  prebuilt CodeMirror bundle, plain SVG). This adds no Node to the Docker
  image or `tools/setup-env.sh`, and works offline;
- **Vite + TypeScript**: better typing and refactoring for a front end that
  will reach a few thousand lines, but it adds Node to every contributor's
  setup and either a build step in CI-less development or a committed
  `dist/`.

Recommendation: no build step, with JSDoc types checked by `tsc --noEmit`
when Node happens to be present. That mirrors how `mypy` is opt-in today
(`pytest -m typecheck`).

---

## 6. Slices

Each slice is useful on its own and ends in something the user can run.

| Slice | Delivers | Main risk it retires |
|---|---|---|
| **1. Live viewer** | `wfb studio face.yaml`: canvas, device/style/time/AOD/skin switches, diagnostics list, live reload on file change, selection boxes from geometry, and click-to-reveal of the YAML line. Read-only | server, SSE and latency on real faces; font-bake memoisation measured (§3.1) |
| **2. Text pane + save** | CodeMirror/Monaco with schema completion, debounced re-render, save with version conflicts handled | the schema dialect in the browser editor (§4.5) |
| **3. Direct manipulation** | drag/resize/rotate via span patches in the authored unit, a multi-target thumbnail strip, snapping | patch engine + ADR 0002 property tests over the example corpus (§3.3) |
| *decision* | whether plan 19's A7, a single draw program, is built before slice 4 (§7, D5). If it is, it is its own plan, researched first | — |
| **4. Layers** | per-element transparent layers (preview change), layer panel with show/hide/solo, hit-testing by alpha, add/duplicate/delete/reorder elements, schema-generated inspector | layer compositing equals single-frame render (§4.3); structural patches |
| **5. Build** | build button, streamed log, memory against the limit, `.prg` download | none new |

Slices 1–2 are about the size of one `wfb` subcommand plus a static page.
Slice 3 is the heart: the patch engine and its tests, including patching
the override that applies on the viewed device (§4.4).

## 7. Risks and open questions

- **The span patch is proven for scalar edits only.** Adding, removing and
  moving keys and elements is mechanical but untested (§3.3). The re-parse
  gate means a bug fails loudly, not silently.
- **Element ↔ author-node mapping.** An element's id, the key it is written
  under, and the composed node's marks give its line range. A `group`'s
  children, `static:` and Styles `layouts:` all nest elements. Format 2
  lowering renames some keys (`yamlsrc.Origin`), so the editor must patch
  the author's spelling and never the lowered one. Geometry keys (`at`,
  `size`, `radius`, `thickness`, angles) appear unrenamed in every face
  §3.3 touched. A full check against `wfb/lower.py` is still owed.
- **Layer compositing fidelity** (§4.3 (b)) is unmeasured.
- **`overrides:` makes the patch target per device** (§4.4). Editing the
  shared design stays the default, but a drag on a device with an
  overriding entry must either edit that entry or say that the override
  wins. Slice 3 owns this; it is not a later refinement.
- **The single draw program (plan 19 A7) and the editor.** A7 lowers each
  element once into a display list of drawing steps that the preview
  evaluates and the emitter prints as Monkey C, removing the rules the two
  still implement twice (plan 19 §2 P2). Plan 19 advised against it unless
  many drawing features were coming. The editor shifts that weighing: the
  preview becomes the main view rather than a check, so every remaining
  preview/device disagreement becomes visible as "the editor was wrong".
  Ordering, as found here:
  - **Slices 1–3 do not depend on A7.** They consume only `preview.render`'s
    frame and the resolved geometry (`Placed`/`ResolvedFace`), and A7
    changes neither interface.
  - **Slice 4 does.** Per-element layers change `Renderer.render_sequence`.
    Under A7 they fall out of a per-element display list; without it, the
    layer mode is written against today's renderer and again if A7 is
    later built.
  - So A7 should be decided between slices 3 and 4, after a research pass
    that re-measures how much of the P2 list remains today (a grep for
    "matches codegen"-style comments finds few, which is not an audit) and
    weighs A7 against extending plan 19 A1's shared definitions with
    parity tests. UNVERIFIED either way.
- **The simulator stays out of reach** (C7). The editor's "run" is the
  preview plus a build. Glyph shapes and arc caps remain approximations, and
  the preview's own header and the stand-in warning already say so.
- **Large faces.** The showcase is about 1 s per edit until the bake is
  memoised. The ruamel parse plus schema validation (about 0.3–0.4 s each)
  is the next floor. Incremental validation, re-checking only the edited
  element's branch, is possible but not designed.

## 8. Decisions for the user

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | Platform | web app (A) · NiceGUI (B) · desktop Qt (D) · VS Code extension (E) | **A**, a local web app served by `wfb studio`, because it is the only option that works in the container and on the macOS host alike |
| D2 | Server dependencies | stdlib only · Starlette/uvicorn | **stdlib only**; revisit if WebSockets prove necessary |
| D3 | Front-end tooling | no build step (vendored ES modules) · Vite + TypeScript | **no build step** |
| D4 | First milestone | slice 1 alone · slices 1–3 · all five · A7 first | **slices 1–3**: a viewer, text pane and direct manipulation, with override-aware drags. They do not depend on A7. Layers (slice 4) follow once the patch engine is proven |
| D5 | Plan 19 A7 (single draw program) | before slice 4 · after slice 4 · never | **decide before slice 4**, after a short research pass on what P2 duplication remains (§7). Building A7 first would delay the editor behind the largest refactor on the table for no slices 1–3 benefit |

Research 27 revisits D4 and D5. The user decided (2026-10-01) on a
geometry-only first GUI, reverting no feature, and building plan 19's A7
first, kind by kind, with the editor as one of its backends.

**D1–D3 decided by the user, 2026-10-01** (recorded in the ADR 0002
amendment):
- D1: a local web app, as recommended.
- D2: **Starlette and uvicorn**, not stdlib only.
- D3: no build step, as recommended.

If the user picks a GUI at all, it amends ADR 0002 ("Open: whether the GUI
is a local web app … or native") with the chosen D1, and becomes a plan.

---

## Sources

- ADR 0002, ADR 0004; research 04 §2 and §4 (prior art: Facer, Watch Face
  Studio, `tobwil/garmincreator`); research 06 §4 and §6–§9; research 19
  (group rings); plan 19 §2 P2 and §3 A7
  (`git show d325e77:docs/plans/19-architecture-refactor.md`).
- `docs/guide/placement.md` (`overrides:`), `docs/guide/text.md`
  (several placeholders in one `text:`).
- `wfb/yamlsrc.py` (round-trip loader, `lc` spans, `Origin`),
  `wfb/migrate.py` (what a re-dump costs to tame), `wfb/build.py`
  (`load`/`select_devices`/`resolve_all`), `wfb/layout.py` (`Placed`,
  `ResolvedFace`), `wfb/preview.py` (`PreviewOptions`, `render`,
  `Renderer.render_sequence`), `wfb/units.py` (`Length.resolve`),
  `wfb/cli.py` (`preview --watch`).
- Probe: `docs/research/probes/gui-editor/` (`probe.py`, `results.txt`).
- NiceGUI `ui.interactive_image` (SVG overlay, mouse events):
  <https://nicegui.io/documentation/interactive_image>; `ui.codemirror`:
  <https://nicegui.io/documentation/codemirror>.
- `monaco-yaml` (yaml-language-server in a web worker, schema completion):
  <https://github.com/remcohaszing/monaco-yaml>; yaml-language-server's
  2019-09/2020-12 support:
  <https://github.com/redhat-developer/yaml-language-server>.
- `codemirror-json-schema` (JSON/JSON5/YAML modes):
  <https://www.npmjs.com/package/codemirror-json-schema>.
