# 27 — `wfb studio`: the visual editor

**Status: proposed (2026-10-02). Building it was decided by the user on
2026-10-01 (research 26 §8 D1–D3, research 27 §8 E1–E4). G4 was decided
on 2026-10-02; G1–G3, G5 and G6 in §1 are open.** Delete this file once every slice has shipped
(`docs/CLAUDE.md`).

Research:
- `docs/research/26-gui-editor.md`: requirements, the text-canonical
  server, span patches, unit-preserving drags, the options;
- `docs/research/27-draw-program.md`: the draw program, layers, the live
  drag;
- `docs/research/28-editor-open-questions.md`: what was closed by
  measurement.

Plan 26 (the single draw program) is the base. Its slices 0–3 are built:
per-element layers, single-sourced frame membership, and the JSON form with
its reference rasteriser.

In short:

* `wfb studio face.yaml` serves a local web app on `127.0.0.1`. The author
  opens it in a browser on the host. In the container, the port is
  published to the host's loopback only (`docs/container.md`).
* **The server holds the file's text and a version number, not a model.**
  Every edit, from the canvas, the inspector or the text pane, is a text
  patch. A patch is accepted only if the patched text:
  - re-parses to exactly the intended data;
  - loads with no new error.

  **Edits go to a working copy, never to the design itself (G4).** The
  design file is written only when the author saves, after seeing the
  diff and approving it. An edit made outside the editor (VS Code, a
  `git checkout`, Claude) reloads the session when there is nothing
  unsaved, and is shown as a conflict when there is.
* **The first editor edits geometry only** (research 27 E2): select,
  move, resize, align, rotate arcs; add an element by type; delete,
  duplicate, reorder. Everything else is edited as text in the same
  window, with schema completion.
* **The canvas is the layer stack** (`wfb.draw.layers`). One transparent
  image per element, plus one per outlined group's ring. Show, hide and
  solo per layer. Dragging moves one layer:
  - every layer shifts its image during the gesture;
  - a lowered element's layer can instead be redrawn in the browser from
    its JSON with the dragged `Layout` constant changed (slice 4);
  - on release, the server patches the text and re-renders, and its
    images are authoritative.
* **A drag writes the author's own unit** (research 26 §4.4): a `%r`
  stays `%r`, rounded to what still lands on the dragged pixel. It writes
  the most specific source of the value on the viewed device: a device-id
  override, then a `shape:` override, then the element's own key
  (research 28 §3, 18/18).
* Nothing on the watch side changes. The editor is host-only.

## 1. Decisions

### Decided

- **D1–D3 (ADR 0002 amendment, 2026-10-01):** a local web app; Starlette
  and uvicorn; a front end of vendored ES modules with no build step.
- **E2 (research 27, 2026-10-01):** a round-trip, geometry-only first
  editor.
- **E4 (research 27, 2026-10-01):** the editor starts after plan 26 slice
  3 (done), while plan 26 ports the remaining kinds.
- **G4: edits go to a working copy; the design is written only on an
  approved save (user, 2026-10-02).** This replaces the proposal to write
  every accepted patch at once. How it works is in "The working copy",
  below.
- **The text pane is CodeMirror 6 with `codemirror-json-schema`**
  (research 28 §5): no false errors on valid faces. It does not enforce
  `dependentRequired`, so `wfb`'s own diagnostics, shown in the same
  gutter, cover that.

### Open

- **G1: where the code lives.**
  - **A (recommended):**
    - `wfb/edit/` holds the patch engine: the span index, scalar and
      structural patches, unit conversion and the override target. It is
      pure text in, text out, with no server.
    - `wfb/studio/` holds the server and the session.
    - `wfb/studio/static/` holds the front end and its vendored libraries.
  - **B:** all of it in `wfb/studio/`.

  A lets the patch engine be tested over the whole corpus with no web
  stack, and lets a future VS Code front end (research 26 §5 E) reuse it.
- **G2: dependencies.**
  - **A (recommended):** `starlette` and `uvicorn` in `requirements.txt`;
    `httpx` (Starlette's test client) in `requirements-dev.txt`. The
    fast suite then tests the server like everything else.
  - **B:** an optional extra, with `wfb studio` explaining what to install,
    and server tests skipped when it is missing.

  B means a test that can silently stop running, which `tests/CLAUDE.md`
  warns against.
- **G3: the transport.**
  - **A (recommended):** plain HTTP for requests (a patch, a render, a
    layer), plus server-sent events for what the server announces: the file
    changed on disk, a re-render finished, build progress. Every message is
    inspectable with `curl`.
  - **B:** one WebSocket, which Starlette supports.

  Nothing measured needs a server round trip per pointer move (research 27
  §5.3), so the WebSocket's only gain is one connection instead of two.
- **G5: vendored front-end files.** Preact and `htm` are single ES
  modules and are vendored as they ship. CodeMirror 6 and
  `codemirror-json-schema` are many npm packages.
  - **A (recommended):** a maintainer script
    (`tools/vendor-studio-frontend.sh`) builds them once with Node into one
    ES module bundle, committed with its versions and licences.
    Contributors and users never need Node.
  - **B:** load them from a CDN. That fails offline and in a locked-down
    container.

### Where edits happen

**The server applies every edit; the browser previews and asks.** The
patch needs:
- the YAML composer's marks, to know which characters to rewrite;
- the device's resolved geometry, to turn a pixel drag into the author's
  unit;
- the override rule;
- the full load as its gate.

All of that is the Python compiler, so doing it in the browser would
mean a second copy in JavaScript: the duplicated-logic problem plan 26
removes between the preview and the watch.

| Step | Where |
|---|---|
| The pointer moves: the layer's image shifts, or a lowered layer is redrawn from its JSON (slice 4) | browser, preview only |
| Release: an intent such as "move `clock` by (+6, −3) px on fenix8solar47mm", or "set `radius` of `ring` to 44%r for all targets" | browser → server |
| Unit conversion, override target, text patch, gate, working-copy write (G4), re-render | server (`wfb/edit/`, the pipeline) |
| New text, version and layers | server → browser |
| Typing in the text pane | browser (CodeMirror), sent as the whole text against its version; the server gates it the same way |
| Undo and redo | server: its history of accepted patches |

The cost is one round trip per release. On loopback that is about the
pipeline's own time with font baking memoised: 28–40 ms for a typical
face and 250 ms for the showcase (research 28 §4).

**What plan 26 does and does not move into the browser.** Plan 26 makes
the last stage, *drawing*, executable by a browser: the program as JSON
plus a rasteriser with a tested contract (`wfb.draw.jsonform`). That
removes the largest single reason a browser preview would drift from the
watch. Every other stage stays Python, and a browser that edited and
previewed on its own would need all of it:

| Stage | Lines today | What a browser would need it for |
|---|---:|---|
| loading: YAML spans, schema, format 2 lowering, desugaring | ~2 400 | finding what to patch; refusing a bad file |
| IR builder and model | ~6 000 | every semantic check, expressions bound to sources |
| layout and units | ~2 250 | author units to `Layout` pixels, per device, overrides included |
| expressions, formats, the catalogue | ~2 550 | readings and strings at sample values |
| fonts (baking, metrics, stand-ins) | ~1 800 | text measurement, which moves a text's box |
| lint | ~2 550 | the diagnostics beside the canvas |
| drawing: the per-kind draw code and `preview.py` | ~1 300 in `wfb/draw/` once ported | **provided by plan 26** as the JSON and its contract |

### The working copy (G4)

- **Where it lives.** It sits beside the design, as
  `.<name>.studio.yaml` in the design's own directory, so relative paths
  resolve exactly as they do for the design: `fonts:` sources, assets.
  The working copy name is gitignored. Every render, lint and build in the
  session reads the working copy.
- **What the author sees.** The design file's name, never the working
  copy's. Diagnostics are reported against the design's path: the session
  loads the working copy with the design's name as its display path, so a
  message reads `face.yaml:12:5`, not `.face.studio.yaml:12:5`.
- **The session.** It records the design's text and modification time
  when it started or last saved. "Unsaved" means the working copy differs
  from that recorded text. The editor shows an unsaved marker and the
  number of changed lines.
- **Save, approved.** Save shows the diff from the design to the working
  copy and waits for the author's approval. On approval, the server:
  1. gates the working copy once more;
  2. checks the design has not changed on disk since the session recorded
     it;
  3. writes the design atomically (a temporary file in the same
     directory, then a rename).

  If the design changed meanwhile, the save is refused, and the author
  chooses between overwriting it (shown its diff first) and reloading it
  (discarding the unsaved edits).
- **Discard** deletes the working copy and reloads the design.
- **An external edit to the design.** With nothing unsaved, the session
  reloads it. With unsaved edits, it is a conflict: keep editing (the
  later save will be refused until resolved), or reload and discard.
- **Resume.** A working copy left from an earlier session, after a crash
  or a closed tab, is offered on the next `wfb studio` for the same
  design: resume it, or discard it.
- **Undo and redo** step through the session's accepted patches, applied
  to the working copy. A save is not undone; it just records a new base.
- **Build** (slice 6) builds the working copy and says so in its log and
  in `build-info.json`, so a `.prg` from unsaved edits is never mistaken
  for one from the design.
- **What the rest of the tooling sees.** `git diff`, the CLI and Claude
  see only the design, and so only saved work. That is the intent of G4.

### Open: G6, a browser-side preview of geometry edits

There is a middle way that needs none of the Python above in the
browser. Every unit is linear in pixels (`wfb.units.Length.resolve`,
research 26 §4.4). So the server could send, per element and per
editable geometry scalar:
- its text range and unit;
- how each of the element's `Layout` constants moves per unit of that
  scalar on the viewed device: one number per pair, a linear coefficient
  plus the rounding rule.

The browser could then:
1. turn a drag into the new author value;
2. patch the scalar's characters in its own copy of the text;
3. move the constants;
4. redraw the layer from its JSON.

That is a complete optimistic edit and preview with no round trip. The
server stays the authority: it gates the same patch on release and
answers with the real render, which replaces the optimistic one.

What the linear model does not cover:
- rounding to whole pixels (`round_half_away`);
- `min_1px` clamps;
- a text's box, which depends on its measured width (its anchor does
  not);
- an `align:` change (discrete);
- a structural edit.

Those stay server round trips. Whether the linear model matches the
server's render exactly, apart from the rounding rule, is UNVERIFIED, and
would be measured over the corpus the way research 28 measured patches.

- **A (recommended for now):** server-applied edits only (above). Slice 4
  already gives a live redraw during a gesture, and the release is one
  round trip.
- **B:** add the linear geometry model and optimistic browser patches as
  a slice after slice 4, if slice 3's measurement shows the release round
  trip feels slow.

## 2. What the editor shows and does

| Area | Content | Source |
|---|---|---|
| Canvas | the layer stack at 2× or 3×, the bezel mask, selection boxes, handles, snapping guides | `wfb.draw.layers`, `Placed.box`/`center` |
| Device strip | one small live frame per target, with the main view on one; switches for style, time, asleep, AOD and skin | `wfb.preview.PreviewOptions` |
| Layers | the element tree in draw order, groups as folders, `static:` and layout content marked; show, hide and solo; drag to reorder | the face, `frame_members` |
| Inspector | the selected element's geometry keys, in the author's units, with "all targets / this device / this shape" for an override | the schema branch for its `type:`, `wfb/edit/` |
| Text pane | the file, with schema completion and `wfb` diagnostics; the selection follows the canvas, and back | CodeMirror, `Element.span` |
| Diagnostics | every diagnostic, clickable to its line and element | `wfb.diagnostics.Bag` |
| Build | build, the streamed log, each target's `.prg` and its measured memory against its limit | `wfb build` as a subprocess |

## 3. Slices

Each slice ships with:
- the fast suite and `mypy --strict` green;
- `tools/snapshot.py` unchanged (the editor never changes a build);
- the slice's own measurement written down in this plan.

Every new refusal (a patch that would not round-trip, a stale version)
is driven red.

### Slice 0 — the patch engine, without a UI

`wfb/edit/` (G1 A):

- **The span index:** the composed tree's marks. Each element is found by
  its `span` (452/452, research 28 §1), and each key's text range taken
  from it.
- **Scalar patches:** a value rewritten in place, in the author's unit
  and quoting (77/77, research 26 §3.3).
- **Structural patches:**
  - add an absent key, in flow or block style;
  - remove a key;
  - delete, duplicate or reorder an element;
  - add an element of a type, with defaults and a colour the face
    already uses.

  The three rules research 28 §2 found are built in: a block ends at the
  next token; deleting a block's last entry removes its key; a duplicate
  renames every id inside it.
- **Unit conversion** for a pixel delta on a device (research 26 §4.4):
  `px`, `%` (of the parent's extent), `%r`, `pt`, and polar
  angle/radius. Each is rounded to the coarsest step that still lands on
  the dragged pixel on that device.
- **The override target** for a key on a device (research 28 §3).
- **The gate** wraps every patch: the result must parse to the intended
  data and load with no new error. Otherwise it is refused with the
  reason.

Tests:
- the research probes become the suite: every example, every edit kind;
- a no-op patch is byte-identical;
- a patched file differs only in the edited lines;
- a conversion lands on the dragged pixel on all three verification
  devices.

### Slice 1 — the server and a read-only viewer

- `wfb studio <face.yaml> [--port N] [--host 127.0.0.1]`: Starlette, run
  by uvicorn. A `--host` other than loopback prints a warning, because the
  server runs `monkeyc` and writes files (research 26 §4.8).
- **The session:** the design's recorded text and time, the working
  copy's text and version (G4); a file watcher on the design (the
  `preview --watch` polling, shared); one resolve per change across the
  targets; font baking memoised (research 28 §4: showcase 893 → 250 ms).
- **The working copy:** created on the first accepted edit, reported
  under the design's name, offered for resume on the next start, and
  gitignored (`.*.studio.yaml`). Save with an approved diff, discard,
  and the external-edit conflict are in this slice. Even a read-only
  viewer must never touch the design.
- **Endpoints (G3 A):**
  - the document (working text, version, unsaved or not, the diff to the
    design);
  - save (with the version the author approved) and discard;
  - the frame and its layers (PNG per layer, JSON ops for lowered kinds,
    boxes, ids, spans);
  - the diagnostics;
  - the devices and styles;
  - an event stream: changed, rendered, error.
- **Front end:** the canvas from layers, selection by click (the topmost
  layer whose alpha is opaque under the pointer), boxes, the device
  strip and switches, the diagnostics list, and "reveal in text" (a line
  number for now).
- **Measured:** time from a file save to an updated canvas, on
  `features/progress`, `showcase` and `vector-text`.

### Slice 2 — the text pane

- CodeMirror 6 with the face schema (G5's bundle). `wfb` diagnostics in
  the gutter.
- A typed edit is sent, debounced at about 300 ms, as a whole-text
  replace against the version it started from. A stale version is refused
  and the pane reloads.
- **Selection both ways:** a click on the canvas selects the element's
  text range (`Element.span` to the composed node), and the cursor in the
  text selects the element on the canvas.
- Typed edits go to the working copy too (G4), and count as unsaved like
  any other edit.

### Slice 3 — direct manipulation

- Handles per kind:
  - position for everything;
  - size for boxed kinds;
  - radius for circles and arcs;
  - `start_angle`/`sweep` for arcs;
  - the two ends of a line.
- **During a gesture the layer's image shifts** (exact for a move).
  Resize shows the box until release.
- **On release**, one patch through `wfb/edit/` (unit and override
  target), the re-render, and the new layers replace the old. A refused
  patch snaps back and shows why.
- **Snapping:** the screen centre, other elements' centres and edges, a
  `%r` grid, and 6°/30° angles.
- The device strip shows the edit's effect on every target as it lands,
  so a `%r` drag's cross-device consequence is visible (research 26 §4.4).
- **Measured:** the drag-to-final-frame time, and whether shifting the
  image feels direct. This is research 28 §8's first measurement.

### Slice 4 — live redraw from the JSON

- A JavaScript rasteriser of `wfb.draw.jsonform`'s ops covers the `Dc`
  primitives and the `drawArc` call. Text uses glyph images the server
  renders per font id and string, or the sheet's own tiles for a baked
  font.
- During a resize, radius or angle gesture on a lowered element's layer,
  the dragged `Layout` constant changes and the layer is redrawn in the
  browser.
- **The contract:** JSON fixtures exported from every example's lowered
  elements, rasterised in Node when present (opt-in, like
  `pytest -m typecheck`). They must equal `jsonform.rasterise`'s pixels,
  allowing for Canvas anti-aliasing on edges only. The tolerance is
  measured, not assumed.
- A kind not yet lowered keeps slice 3's image shift.

### Slice 5 — layers, structure and the inspector

- **The layer panel:** show, hide and solo, editor-only; reorder by drag
  (a structural patch); groups as folders.
- **Add an element** by type from a palette (slice 0's add); delete and
  duplicate.
- **The inspector**, generated from the element's schema branch
  (research 26 §4.6). Geometry keys are editable, with their special
  widgets: length with its unit, angle, the 3×3 align picker. Every other
  key is shown read-only, with a jump to its line in the text pane.
- The override chooser: "all targets", "this device", "this shape".

### Slice 6 — build

- A build button runs `wfb build` on the working copy as a subprocess (a
  hung `monkeyc` cannot take the editor down) and streams its log over the
  event stream. A build with unsaved edits says so in its log and in
  `build-info.json`.
- It shows each target's `.prg` (a download) and its measured memory
  against `Device.watchface_memory_limit`.
- Sideloading stays manual (`wfb install` is unbuilt, `docs/limitations.md`
  §2).

### Slice 7 — close-out

- `docs/guide/studio.md`: a guide chapter, linked from the hub.
- `docs/container.md`: running it in the container with the port
  published to loopback.
- `docs/limitations.md` §2: what the editor does not edit (non-geometry
  keys, beyond the text pane).
- `docs/lore/roadmap.md`: the editor is built.
- The root `CLAUDE.md` §6.
- Delete this plan, and add its row to `docs/plans/README.md`.

## 4. Tests, beyond each slice's own

- **The patch engine over the corpus** (slice 0 on): every example face,
  every edit kind, a no-op byte-identical, nothing outside the edited
  lines changed.
- **The server** through Starlette's test client (G2 A):
  - document versions, and a stale patch refused;
  - the design byte-identical after any number of edits and a discard,
    and changed only by an approved save;
  - a save refused when the design changed on disk after the session
    recorded it;
  - an external edit reloaded with nothing unsaved, and a conflict with
    something unsaved;
  - a left-over working copy offered for resume;
  - diagnostics naming the design, never the working copy.
- **No build changes:** `tools/snapshot.py` at every slice.
- **The front end:** the pure functions (unit conversion display,
  snapping, hit-testing by alpha, the JSON rasteriser) as ES modules,
  checked in Node when it is present. The UI itself is checked by hand.
  There is no headless browser in the container, and the plan says so
  rather than claiming coverage.

## 5. Risks

- **A large face's re-render on release** (showcase, 250 ms memoised)
  could feel slow. The image shift hides it during the gesture, and the
  drop is one render.
- **Unported kinds** (`icon`, gauges, `pattern`, `hands`, `graph`,
  complication slots until plan 26's slices 4–9) get only the image shift
  during a gesture. Correctness is the same, because the server renders
  every release.
- **CodeMirror bundle upkeep (G5):** one script with pinned versions,
  rerun deliberately.
- **A forgotten working copy.** Unsaved work sits in a hidden file beside
  the design. The editor's unsaved marker, the resume offer, and
  `wfb studio`'s exit message naming it keep it visible, and the file is
  gitignored so it is never committed by accident.
- **Security:** the server writes the working copy, writes the design
  only on an approved save, and runs `monkeyc`.
  Loopback by default, file access limited to the design's own directory,
  no arbitrary path reads.
