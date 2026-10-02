# 27 — `wfb studio`: the visual editor

**Status: accepted (2026-10-02), re-scoped by the user the same day (S1–S7
below); slices 0 and 1 done, 2–7 to go.** Building it was decided by the user on
2026-10-01 (research 26 §8 D1–D3, research 27 §8 E1–E4). Delete this file
once every slice has shipped (`docs/CLAUDE.md`).

Research:
- `docs/research/26-gui-editor.md`: requirements, the text-canonical
  server, span patches, unit-preserving drags, the options;
- `docs/research/27-draw-program.md`: the draw program, layers, the live
  drag;
- `docs/research/28-editor-open-questions.md`: what was closed by
  measurement.

Plan 26 (the single draw program) is the base, and is built: every
element is one program, its guards included, with per-element layers,
single-sourced frame membership, and the JSON form with its reference
rasteriser.

In short:

* **A client-driven web app.** `wfb studio` serves a local web app on
  `127.0.0.1`, with no file named. The author opens it in a browser on the
  host and, from there, **creates a new face or opens one**, edits it, and
  downloads it. Several faces can be open at once, one per tab. In the
  container, the port is published to the host's loopback only
  (`docs/container.md`).
* **A face travels as a bundle.** It is opened by upload and saved by
  download: a `.zip` holding `face.yaml` and an `assets/` directory, or a
  plain `.yaml` when the face references no file. The server never reads
  or writes a host path the author did not hand it.
* **Each open face is a document**: a throwaway temporary directory the
  compiler reads (so relative font paths resolve), backed by a durable
  **history store** that records every accepted change. Undo and redo
  survive a closed tab and a server restart, and a **snapshot** is taken
  every few minutes, so there is always a point in time to go back to.
* **The server holds each document's text and a version, not a model.**
  Every edit, from the canvas, the inspector, the layer tree or the YAML
  tab, is a text patch. A patch is accepted only if the patched text:
  - re-parses to exactly the intended data;
  - loads with no new error.

  So the author's comments, key order and formatting survive every edit,
  and the downloaded file stays a hand-editable design.
* **The editor edits the whole face**, not just geometry:
  - **left:** the layer tree (static content, dynamic elements, each
    layout's own two, groups as folders) and the face's global blocks
    (colours, styles);
  - **centre:** the live preview, one transparent image per layer
    (`wfb.draw.layers`), with move and resize handles;
  - **right:** the properties of the selected item, every key, with a
    widget per kind of value;
  - **a YAML tab**, secondary, for what no widget expresses yet.
* **A drag writes the author's own unit** (research 26 §4.4): a `%r`
  stays `%r`, rounded to what still lands on the dragged pixel. It writes
  the most specific source of the value on the viewed device: a device-id
  override, then a `shape:` override, then the element's own key
  (research 28 §3, 18/18).
* **Building is postponed.** A downloaded bundle builds with `wfb build`
  once unpacked; a build button comes later.
* Nothing on the watch side changes. The editor is host-only.

## 1. Decisions

### The re-scope (user, 2026-10-02)

The first version of this plan served one design file named on the
command line, wrote edits to a hidden working copy beside it (G4) and
edited geometry only (E2). The user re-scoped it the same day:

- **S1: client-driven.** `wfb studio` starts with no face. The browser
  chooses: new, open, or a recent document. The server is the compiler
  the browser talks to, not a view of one file.
- **S2: documents are volatile temporary directories.** No workspace
  directory, no working copy beside a design. **This supersedes G4.**
- **S3: open by upload, save by download, only.** The format is a `.zip`
  with `face.yaml` and `assets/`, or a plain `.yaml` when the face uses no
  asset file. No File System Access API (save in place), no server-side
  host paths.
- **S4: a persistent history.** Every accepted change is recorded so undo
  and redo survive; a snapshot is written every predefined number of
  minutes to a store it can be restored from.
- **S5: edit every property.** The layer hierarchy (static and dynamic,
  layouts, groups), the global colours and styles, and a properties
  inspector over every key. **This supersedes E2** (geometry only).
- **S6: the YAML text pane stays, as a secondary tab.**
- **S7: postponed:** the build button (old slice 6) and the in-browser
  live redraw from JSON (old slice 4). Both stay possible later; neither
  is in this plan's slices.

### Kept from the first version

- **D1–D3 (ADR 0002 amendment, 2026-10-01):** a local web app; Starlette
  and uvicorn; a front end of vendored ES modules with no build step.
- **E4 (research 27, 2026-10-01):** the editor starts after plan 26 slice
  3 (done).
- **G1:** the patch engine in `wfb/edit/` (pure text in, text out,
  testable over the corpus with no web stack); the server, documents and
  history store in `wfb/studio/`; the front end and its vendored libraries
  in `wfb/studio/static/`.
- **G2:** `starlette` and `uvicorn` in `requirements.txt`, `httpx`
  (Starlette's test client) in `requirements-dev.txt`, so the fast suite
  tests the server like everything else. An optional extra would make a
  test that can silently stop running (`tests/CLAUDE.md`).
- **G3:** plain HTTP for requests (an edit, a render, an upload, a
  download), plus server-sent events for what the server announces (a
  render finished, a snapshot taken, an error). Every message is
  inspectable with `curl`. Nothing measured needs a server round trip per
  pointer move (research 27 §5.3).
- **G5:** CodeMirror 6 and `codemirror-json-schema` vendored as one
  prebuilt ES module bundle by a maintainer script
  (`tools/vendor-studio-frontend.sh`), committed with its versions and
  licences. Preact and `htm` are vendored as they ship. Contributors and
  users never need Node. A CDN fails offline and in a locked-down
  container.
- **G6:** server-applied edits only (below). A browser-side linear
  geometry model is reconsidered only if slice 4 shows the release round
  trip feels slow.
- **The text pane is CodeMirror 6 with `codemirror-json-schema`**
  (research 28 §5): no false errors on valid faces. It does not enforce
  `dependentRequired`, so `wfb`'s own diagnostics, shown in the same
  gutter, cover that.

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
| The pointer moves: the layer's image shifts | browser, preview only |
| Release, or a value set in the inspector: an intent such as "move `clock` by (+6, −3) px on fenix8solar47mm", or "set `radius` of `ring` to 44%r for all targets" | browser → server |
| Unit conversion, override target, text patch, gate, history record, re-render | server (`wfb/edit/`, `wfb/studio/`, the pipeline) |
| New text, version and layers | server → browser |
| Typing in the YAML tab | browser (CodeMirror), sent as the whole text against its version; the server gates it the same way |
| Undo and redo | server: the document's history |

The cost is one round trip per release. On loopback that is about the
pipeline's own time with font baking memoised: 28–40 ms for a typical
face and 250 ms for the showcase (research 28 §4).

**What plan 26 does and does not move into the browser.** Plan 26 makes
the last stage, *drawing*, executable by a browser: the program as JSON
plus a rasteriser with a tested contract (`wfb.draw.jsonform`). Every
other stage stays Python, and a browser that edited and previewed on its
own would need all of it:

| Stage | Lines today | What a browser would need it for |
|---|---:|---|
| loading: YAML spans, schema, format 2 lowering, desugaring | ~2 400 | finding what to patch; refusing a bad file |
| IR builder and model | ~6 000 | every semantic check, expressions bound to sources |
| layout and units | ~2 250 | author units to `Layout` pixels, per device, overrides included |
| expressions, formats, the catalogue | ~2 550 | readings and strings at sample values |
| fonts (baking, metrics, stand-ins) | ~1 800 | text measurement, which moves a text's box |
| lint | ~2 550 | the diagnostics beside the canvas |
| drawing: the per-kind draw code and `preview.py` | ~1 300 in `wfb/draw/` | **provided by plan 26** as the JSON and its contract |

### Documents and the bundle (S2, S3)

- **A document** is one open face: an id, a display name, its text and
  version, its asset files, and its history. Its **temporary directory**
  (`tempfile.mkdtemp`) holds `face.yaml` and the asset files at their
  relative paths, materialised from the history store, so the compiler
  loads it exactly as it would a face on disk. The directory is
  disposable: it is rebuilt from the store whenever it is missing (after a
  server restart, say).
- **Diagnostics name `face.yaml`**, never the temporary path. A span
  carries the path the text was loaded under (the temporary one, so fonts
  resolve), so the server reports each span relative to the document's
  directory.
- **New.** From one of `wfb new`'s templates (`wfb/templates/`, with their
  blurbs), with a name and the targets (default: the three verification
  devices; any installed watch-face-capable device may be added). It
  mints a fresh UUID exactly as `wfb new` does, through one shared
  function, so the CLI and the editor cannot drift.
- **Open (upload).**
  - A `.yaml`/`.yml`: becomes `face.yaml`; its file name becomes the
    display name.
  - A `.zip`: exactly one `*.yaml` at the bundle root (`face.yaml`, or a
    single other name, which is taken as the face), plus files beneath
    it, by convention under `assets/`. Other files are kept and travel
    back out unchanged (a README, say).
  - **Refused, with the reason:** an entry with an absolute path, a `..`
    component or a link; no face or more than one at the root; a bundle
    over a size or entry-count limit, checked against the uncompressed
    sizes before extracting (zip bombs); a file that is not UTF-8 YAML.
- **Missing assets.** A face whose references (a `fonts:` `source:`)
  point at a file the bundle does not hold (a bare `.yaml` that used
  fonts, or a reference outside the face's directory, such as
  `features/profile`'s `../outline/assets/...`) opens anyway. The editor
  lists each missing file; the author uploads it, it is stored under
  `assets/`, and the reference is patched to `assets/<file>` as an
  ordinary, undoable change.
- **Download (save).** The face plus every file under its directory:
  - a `.zip` (`face.yaml` and `assets/`) when the face references any
    file;
  - a plain `.yaml` when it references none.

  Either can be asked for explicitly; a plain `.yaml` of a face with
  assets says, before downloading, that it will not build on its own.
  The file is named after the face (`wfb.build.slug`). Every download takes
  a snapshot.
- **`wfb studio <face.yaml|bundle.zip>`** survives as a shortcut that
  opens one document exactly as an upload would, with the face's
  referenced files gathered the same way (a file outside the face's
  directory is copied under `assets/` and its reference patched, as the
  document's first recorded change). It never writes back to that path.

### The history store (S4)

- **Where.** `--state-dir`, defaulting to `$XDG_STATE_HOME/wfb/studio`
  (`~/.local/state/wfb/studio`). In the container it is a named volume,
  as the key store is (`-v wfb-studio:/state`, `docs/container.md`);
  without one, history ends with the container.
- **What it holds, per document** (`<state-dir>/<document id>/`):
  - `blobs/<sha256>`: every text version and every asset file, content
    addressed, so a thousand edits to a 10 KB face cost little and an
    asset is stored once;
  - `journal.jsonl`: one line per change, appended and flushed before the
    change is acknowledged: sequence number, time, a label in the author's
    terms ("move `clock` by +6, −3 px on fr955", "set `color.bg`",
    "typed in YAML", "undo"), the resulting text's hash and the asset
    manifest (path → hash);
  - `snapshots/`: one small JSON file per snapshot, naming a journal
    position, with its time and why it was taken.
- **Undo and redo** are a cursor over the journal. Undo and redo are
  themselves journal lines, so the cursor survives a restart. A new change
  after an undo drops the redo branch, as every editor does (its blobs stay
  until pruned, so a snapshot inside it still restores).
- **Snapshots** are taken:
  - every `--snapshot-minutes` (default **5**), when the document changed
    since the last one;
  - on every download;
  - on "snapshot now".

  **Restore** a snapshot into its own document, as one recorded change, so
  a restore is itself undoable; or open it as a new document.
- **Recent.** The home screen lists the documents in the store (name, last
  change, snapshot count), and reopens any of them. Discarding a document
  deletes its directory in the store, after a confirmation.
- **Pruning,** on start: documents untouched for `--keep-days` (default
  30) are removed, and a document keeps its last 50 snapshots. Both are
  flags; the prune is logged.
- **Volatile, by design:** the temporary directories. **Durable:** the
  store. The browser holds nothing that the store does not.

### Editing the whole face (S5)

| Area | Content | Source |
|---|---|---|
| Layer tree | the face in draw order: `static:` and `elements:`, each `layouts:` entry with its own two, groups as folders; show, hide and solo (editor-only); drag to reorder, into or out of a group, or between static and dynamic | the face, `frame_members`, `wfb/edit/` |
| Global | the face's colours (`color.` names, `palette:`, `theme: schemes:`), and `config:` style entries with their layouts; fonts in use | the face |
| Canvas | the layer stack at 2× or 3×, the bezel mask, selection boxes, handles, snapping guides; switches for device, style, time, asleep, AOD and skin | `wfb.draw.layers`, `Placed.box`/`center`, `wfb.preview.PreviewOptions` |
| Properties | every key of the selected element, from the schema branch for its `type:`, in the author's units, with "all targets / this device / this shape" for an override | the schema, `wfb/edit/` |
| YAML tab | the file, with schema completion and `wfb` diagnostics; the selection follows the canvas, and back | CodeMirror, `Element.span` |
| Diagnostics | every diagnostic, clickable to its element and line | `wfb.diagnostics.Bag` |
| History | undo, redo, the journal's labels, snapshots and restore | the history store |

**Widgets** (research 26 §4.6), chosen by the schema node:
- a length with its unit; an angle; a number; a boolean; an enum;
- the 3×3 align picker;
- a colour: a `color.` name from the face, or a literal shown against
  the 64-colour MIP palette (constraint 13);
- a font: the face's `fonts:` names and the system fonts;
- an icon: the named icons, searchable;
- a data binding: a picker over the catalogue's sources that inserts a
  placeholder into a `text:` template, or sets a gauge's value;
- anything else (an expression, a nested structure no widget covers):
  shown as its text, with "edit in YAML" jumping to its line.

**Static and dynamic.** "Make static" and "make dynamic" move an element
between a block's `static:` and `elements:` (creating the block if
absent, removing it when emptied); the same move works across layouts.
Each is one structural patch, gated like every other: a move the
compiler refuses (a `data` element into a layout, say) is refused with
its reason.

## 2. Slices

Each slice ships with:
- the fast suite and `mypy --strict` green;
- `tools/snapshot.py` unchanged (the editor never changes a build);
- the slice's own measurement written down in this plan.

Every new refusal (a patch that would not round-trip, a stale version, a
bad bundle) is driven red.

### Slice 0 — the patch engine, without a UI: done

Built as below, in `wfb/edit/`:
- `spans`: `SpanIndex` (the composed tree, every entry by author path,
  each element by its `span`, `entry_range`/`value_end`);
- `patch`: `set_value` (a scalar in place in its own quoting, or the
  missing keys as a nested flow value), `remove`, `delete_element`,
  `duplicate_element`, `move_element` (to any sibling position),
  `add_element` (shapes and `text`; any other type is refused with "write
  it in the text");
- `gate`: `Gate.check` and `load_text`. `wfb.build.load` and
  `wfb.yamlsrc.load` take the text in place of the file, so a text loads
  under the design's own path: fonts resolve and diagnostics name the
  design. Slice 1's documents use the same entry point.
- `geometry`: `target` (the override rule, with "all", "device" and
  "shape" scopes that create the override), `View` (one text placed on
  one device), `move` and `resize`.

**Landing is checked, not assumed.** A drag's candidate values run
coarsest first. Each is placed through the real load and layout on the
viewed device, with that device's baked fonts reused (re-baked for an
icon's `size:`), and the first that lands is written.

Measured, over the 29 example faces (`examples/dashboard` excluded):

| Measure | Result |
|---|---|
| elements found by their span | **452/452** |
| delete / duplicate the first three elements of each face | **86/86**, **86/86** |
| move up / move down | **50/50**, **73/73** |
| add an absent `at.dx` / remove `at.dy` | **69/69**, **30/30** |
| add an element of each of the 7 types, per face with `elements:` | **182/182** |
| moves on `features/shapes`, `align` and `rings`, 3 drags × 3 devices | **360/360** landed on the dragged pixel |
| resizes (`size`, `radius`, `thickness`) on the same | **141/141** landed |

The fast suite (`tests/test_edit.py`) runs a subset of these per face.
Two refusals by design, each with its reason: a polygon's move (its
`points:` are edited in the text), and a position written in `pt`
(`pt` has no pixel size outside a font). The synthetic `static` group and
a layout's block are refused too: they are blocks, not elements. Each
guard was seen red: the duplicate's renaming, the block rule, the override
order, the gate's data check and the landing check.

What was asked of it:

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

### Slice 1 — the service, documents and a read-only viewer: done

Built as below, in `wfb/studio/`:
- `bundle`: upload (`.yaml`, or a `.zip` with one face at its root or in
  one wrapping folder; desktop litter skipped) and every refusal: `..`,
  absolute paths, links, no face, two faces without a `face.yaml`, the
  size and entry limits checked before unpacking, non-UTF-8 text. A face
  is named by its own `face: name:`. `from_path` reads a design on disk
  for `wfb studio face.yaml`, gathering a font outside its directory
  under `assets/`; the reference is patched as the document's second
  recorded change. `to_zip` writes `face.yaml` plus the files.
- `store`: one directory per document: `meta.json`, content-addressed
  `blobs/`, and `journal.jsonl`, appended and fsynced before a change is
  acknowledged. A line cut short by a crash is not the head.
- `document`: a document's temporary directory, synced to the head file
  by file (an untouched font keeps its mtime, which keys the bake memo;
  rewriting it re-baked every font on every change: showcase 1369 ms per
  change instead of 255); the pipeline once per version
  (`load_text`, `select_devices`, `resolve_all` with a shared
  `wfb.emit.resources.BakeMemo`); frames per device, style, time,
  asleep, AOD and zoom, cached per version; the layer tree from the
  author's text; diagnostics with the temporary directory taken out of
  every path they quote. A version check refuses a change against an old
  version (409).
- `app`: the endpoints (home, new, upload, document, delete, frame, add a
  missing font, download as `.zip`/`.yaml`/auto) and the event stream
  (`changed`, `rendered`). Every endpoint's work runs in the thread pool
  under one lock; an upload is the raw body with its name in the query.
- `static/`: the home screen (new from a template, open by upload or
  drop, recent faces with delete), and the editor: the layer tree, the
  canvas with selection by alpha (`hit.js`), the device and style
  switches, time, asleep, AOD and zoom, the selected element's id, type,
  block, line and box, the diagnostics (a click selects the element at
  that line), the missing-font banner, and download. Preact and `htm`
  are vendored by `tools/vendor-studio-frontend.sh`.
- `wfb studio [design] [--host] [--port] [--state-dir]`; the container
  entrypoint adds `--host 0.0.0.0` and uses a `/state` volume.

Two changes outside `wfb/studio/`:
- `wfb new` and New share `wfb.starters.instantiate`.
- **The gate accepts a patch to a text that did not load**, as long as it
  adds no error. Adding the first of two missing fonts leaves the face
  still not loading, and was refused as "no longer loads".
  `tests/test_edit.py` holds the new contrast.

Added beyond the plan's list: a missing font added in place (it was
listed for slice 1 but its upload was not), and deleting a document.

Measured, in-process on fr955 at 2×, best of three changes with a warm
font memo:

| Face | open → first frame (cold bake) | change → frame | of which: commit + pipeline, frame | frame JSON |
|---|---:|---:|---|---:|
| `features/progress` | 459 ms | 136 ms | 39 ms, 98 ms | 41 KB |
| `showcase` | 2 352 ms | 523 ms | 249 ms, 274 ms | 58 KB |
| `features/vector-text` | 673 ms | 442 ms | 42 ms, 400 ms | 110 KB |

The frame is now the larger half: `wfb.draw.layers` paints each element
twice (on black and on white), and vector text is slow to draw. Each
layer travels as a PNG cropped to its ink, with its origin: full-frame,
mostly clear layers took the showcase's 28 encodings to 192–347 ms. Slice
4's release round trip pays the frame once per drop. The UI was checked
only as far as the page being served and its modules parsing
(`node --check`); there is no browser in the container.

`tools/snapshot.py`: 547 of 551 cases unchanged; `wfb --help` lists
`studio` (and `wfb help studio` is two new cases); `wfb doctor`'s python
path differs only because the baseline ran from a worktree whose `.venv`
was a link.

Tests: `tests/test_studio.py` (bundles and every refusal, the store across
a new server, the directory sync, versions, never writing to an opened
design, diagnostics naming `face.yaml`, the tree, frames, every endpoint,
events) and `tests/test_studio_frontend.py` (`hit.js` in Node). Each
guard was seen red.

### Slice 2 — history: undo, redo, snapshots, restore

- The journal's undo and redo cursor; snapshots on the timer, on
  download and on demand; restore into the document (undoable) or as a
  new one; pruning on start.
- The history panel: the journal's labels, the snapshots, restore.
- A change arriving while the store cannot be written is refused, never
  applied unrecorded.
- **Measured:** the cost of a journal append per change, and the store's
  size after the slice 0 corpus edits.

### Slice 3 — the properties inspector and the global panel

- The inspector generated from the selected element's schema branch,
  every key, with the widgets above and the override chooser ("all
  targets", "this device", "this shape").
- New in `wfb/edit/`: setting a sequence or a mapping value, not only a
  scalar; a key's removal back to its default; a colour name's add,
  rename (every use patched, gated) and value change; a style entry's add
  and remove.
- The global panel: colours and their swatches against the MIP palette,
  styles and layouts, fonts in use with upload of a font file.

### Slice 4 — direct manipulation on the canvas

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
- A small frame per target beside the canvas shows the edit's effect on
  every target as it lands, so a `%r` drag's cross-device consequence is
  visible (research 26 §4.4).
- **Measured:** the drag-to-final-frame time, and whether shifting the
  image feels direct. This is research 28 §8's first measurement, and
  G6's trigger.

### Slice 5 — structure

- **Add an element** by type from a palette of types (slice 0's add,
  extended to every type the schema has; a type that needs a choice, such
  as a `graph`'s series, asks for it first).
- Delete and duplicate, from the tree and the canvas.
- Reorder by drag in the tree; into and out of a group; **static and
  dynamic**, and across layouts (new in `wfb/edit/`: moving an entry
  between blocks).
- Group and ungroup a selection.

### Slice 6 — the YAML tab

- CodeMirror 6 with the face schema (G5's bundle). `wfb` diagnostics in
  the gutter.
- A typed edit is sent, debounced at about 300 ms, as a whole-text
  replace against the version it started from, recorded as one change. A
  stale version is refused and the pane reloads.
- **Selection both ways:** a selected element selects its text range
  (`Element.span` to the composed node), and the cursor in the text
  selects the element on the canvas and in the tree.

### Slice 7 — close-out

- `docs/guide/studio.md`: a guide chapter, linked from the hub.
- `docs/container.md`: the port published to loopback, and the
  `wfb-studio` volume for the history store.
- `docs/limitations.md` §2: what the editor does not do (build, values no
  widget covers, beyond the YAML tab).
- `docs/lore/roadmap.md`: the editor is built.
- The root `CLAUDE.md` §6.
- Delete this plan, and add its row to `docs/plans/README.md`.

### Later, not in this plan (S7)

- A build button: `wfb build` on the document's temporary directory as a
  subprocess, streaming its log; each target's `.prg` as a download, and
  its memory against `Device.watchface_memory_limit`.
- Live redraw from the JSON during a gesture: a JavaScript rasteriser of
  `wfb.draw.jsonform`'s ops, held to `jsonform.rasterise`'s pixels by
  fixtures checked in Node.
- `wfb build` reading a bundle `.zip` directly.

## 3. Tests, beyond each slice's own

- **The patch engine over the corpus** (slice 0 on): every example face,
  every edit kind, a no-op byte-identical, nothing outside the edited
  lines changed.
- **The server** through Starlette's test client (G2):
  - a stale version refused;
  - upload then download returns the same bytes (`.yaml` and `.zip`);
  - each bundle refusal: `..`, an absolute path, a link, no face, two
    faces, over the limits;
  - a missing asset listed, uploaded, and its reference patched;
  - diagnostics naming `face.yaml`, never the temporary path;
  - the history surviving a new app over the same state directory: the
    text, the assets, and the undo and redo cursor;
  - a snapshot on the timer (an injected clock), on download, and a
    restore that is itself undone;
  - pruning by age and by count;
  - nothing written outside the temporary directories and the state
    directory.
- **No build changes:** `tools/snapshot.py` at every slice.
- **The front end:** the pure functions (unit display, snapping,
  hit-testing by alpha) as ES modules, checked in Node when it is present.
  The UI itself is checked by hand. There is no headless browser in the
  container, and the plan says so rather than claiming coverage.

## 4. Risks

- **A large face's re-render on release** (showcase, 250 ms memoised)
  could feel slow. The image shift hides it during the gesture, and the
  drop is one render. G6 is the answer if it does.
- **An inspector over every key is a large surface.** It is generated
  from the schema, so it is as complete as the schema; a widget the
  generator does not have falls back to "edit in YAML" rather than to a
  wrong form.
- **The history store in the container** is lost without its volume. The
  editor's home screen says where the store is, and warns when it is
  inside a container with no volume mounted there (`WFB_CONTAINER`).
- **CodeMirror bundle upkeep (G5):** one script with pinned versions,
  rerun deliberately.
- **Security:** loopback by default. The server writes only its
  temporary directories and its state directory, reads only what was
  uploaded, its templates and its state, and extracts a bundle only after
  checking every entry. No host path reaches it from the browser.
