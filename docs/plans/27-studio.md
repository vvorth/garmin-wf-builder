# 27 — `wfb studio`: the visual editor

**Status: accepted (2026-10-02), re-scoped by the user the same day (S1–S7
below); slices 0–6 done, 7 to go.** Building it was decided by the user on
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
| Typing in the YAML tab | browser (CodeMirror), sent as the whole text against its version; the server records it when it is YAML (slice 6: a load error is shown, not refused) |
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

### Slice 2 — history: undo, redo, snapshots, restore: done

Built as below:
- **The journal holds every action.** A `change` line adds a state; an
  `undo` or `redo` line names the state it moved to (`target`). Every line
  also names the text and assets the document has after it, so the last
  line is still the document, and `store.replay` gives the line of
  states and the cursor. A change after an undo drops the states past the
  cursor; their blobs stay.
- **Undo and redo** (`Document.undo`/`redo`), version-checked like a
  change, refused with "nothing to undo/redo". Ctrl+Z, Ctrl+Shift+Z and
  Ctrl+Y outside a text field, and two buttons in the top bar.
- **Snapshots** (`snapshots/<seq>-<ms>.json`, naming text and assets by
  hash): on the timer (`Studio.tick`, run every quarter interval by a
  daemon thread, at most 30 s apart), when a document changed since its
  last snapshot and an interval has passed since that one; on a download
  of a version that has none; and on "snapshot now".
- **Restore** is one change, so it can be undone; it works for a snapshot
  taken in a redo branch a later change dropped. **Open copy** makes a new
  document from a snapshot, its files copied.
- **Pruning** on start (`--keep-days`, `--keep-snapshots`), each removal
  printed.
- The History tab beside Diagnostics: snapshot now, the snapshots with
  restore and open copy, and the changes, newest first, the current one
  marked and the redoable ones dimmed. The home screen shows each face's
  snapshot count.

**Found on the way:** a journal append whose `fsync` failed left its
line in the file, so a change reported as refused would have come back as
applied after a restart. A failed append now truncates the journal to its
previous length. The test that found it fails the append with the text's
blob already stored, so only the journal write is exercised.

Measured over the 29 example faces (`examples/dashboard` excluded):
duplicate, move to the top and delete the first three elements of each,
258 changes:

| Measure | Result |
|---|---|
| journal append (blob write, line, `fsync`) | median 1.28 ms, p95 1.79 ms, max 4.58 ms |
| store after the 258 changes and 29 opens | 2.5 MB: text versions 1.9 MB, font files 0.6 MB (each stored once), journals 53 KB |
| text versions under zlib | 3.1× smaller, 0.22 ms a version |

Every version is a full copy of the text. That is cheap until slice 4,
where each drag's release is a version: a thousand changes to the 35 KB
showcase would store 35 MB (11 MB compressed). Slice 4 decided:
compressed (below).

Tests: `tests/test_studio.py` (replay, undo and redo, a change ending the
redo line, a stale undo, an undone asset leaving the directory, the
history across a new server, a refused change not recorded, the timer
with an injected clock, restore and its undo, a dropped branch's
snapshot, open copy, pruning by age and by count, every endpoint, the CLI
defaults). Each guard was seen red.

### Slice 3 — the properties inspector and the global panel: done

Built as below:
- **New in `wfb/edit/`:**
  - `set_value` replaces a block mapping or sequence too, in block style
    at its indent, keeping the key's own line and its comment;
  - `rename_key`; `rewrite_scalars` (every string value, never a key or
    a block scalar, each in its own quoting); `chain`, two patches as one
    with the first's text checked against its data;
  - `rename_reference`: a declared name and every `color.<name>` (or
    `font.<name>`) that refers to it, inside expressions too, never a
    longer name;
  - the gate's `ordered` moved to `spans`; `Gate` takes a `before` load;
    `SpanIndex` composes once (below) and `index_for` shares one per text.
- **`wfb/studio/inspect.py`:** the inspector from the element's schema
  branch: every key, its widget from the `$defs` entry it names (`length`,
  `angle`, `align`, a colour, `position` and `size` as nested keys,
  `visible`/`expression`) or its JSON type, with `text`, `font`, `icon` and
  `on_hold` given pickers; a shape's keys narrowed to its own
  (`SHAPE_GEOMETRY_KEYS`); a list or nested structure shown as its text.
  The overrides the viewed device reads, per scope. The Face panel's data:
  palette (with the targets whose panel would dither each colour),
  schemes and roles, style entries, layouts, fonts, targets. The
  vocabulary: sources by namespace, icon names, complication types, and
  the installed watch-face devices with their system fonts.
- **`Document.edit`:** set, remove and rename, gated and recorded with a
  label in the author's terms. A geometry key edited for "this device" or
  "this shape" goes to that override (created when missing); any other key
  is refused there. **`add_asset`** also adds a font from an uploaded file,
  or replaces a font's file (the old file leaves the bundle when nothing
  else refers to it).
- **One load per edit.** The gate's load of the text before the patch is
  the current version's analysis, and its load of the patched text seeds
  the next one, so an edit loads the face once, not three times. A test
  checks that the analysis it gets equals a fresh one.
- **UI** (`panels.js`, `values.js`): the inspector with the scope chooser
  ("all targets", the viewed device, its shape), a note where a key is
  overridden, an override's unit and placeholder taken from the value it
  replaces, and × to remove a key; widgets for a length or angle with its
  unit, the 3×3 align picker, a colour (palette and roles, a custom colour,
  a warning off the MIP palette), a template with a data picker, a font
  (the face's and the device's system fonts), an icon, a complication, an
  enum, a boolean, a number. A Face tab beside Layers: targets (add from
  the installed devices, remove), colours (rename everywhere, edit, add,
  delete), the schemes' role × scheme table, styles (default, layout,
  scheme, add shaped like the others, delete), fonts (size, replace the
  file, add from a file, delete).

**Checked in a DOM.** The UI was driven in jsdom (installed outside the
repo, not a dependency) against a live server: select an element, set its
font, override `at.dy` on one device and on the shape, rename a colour,
add and undo a target, see a refusal as a message, add a style and a font
from a file, change the font's size and a colour's value. No page errors.
It found two bugs: a text field committed its state rather than its
value when the blur arrived before the re-render, and a new style entry
lacked the `scheme:` its siblings had. A browser by hand is still owed.

**One load per edit, one scan per index.** Measured first, an edit on the
showcase scanned its 35 KB text four times (the span index composed it and
parsed it again, the gate parsed the patched text, the gate loaded it)
and loaded the face three times (the gate's before and after, then the
analysis). Now the gate's "before" is the current version's analysis, its
"after" seeds the next analysis, and the span index builds its data from
its own nodes, composed by the safe loader (identical marks and styles on
all 39 corpus files; the round-trip composer's folded scalars differ),
cached per text so the tree, the inspector, the Face panel and the next
patch share it.

Measured, in-process on fr955 at 2×, best of four `z:` edits on the last
element, idle machine:

| Face | edit → frame | gate + record | analysis | summary | frame |
|---|---:|---:|---:|---:|---:|
| `features/progress` | 105 ms | 35 ms | 2 ms | 1 ms | 67 ms |
| `showcase` | 616 ms (793 ms before the reuse) | 321 ms | 19 ms | 2 ms | 274 ms |
| `features/vector-text` | 443 ms | 51 ms | 5 ms | 0 ms | 387 ms |

What is left on the showcase is the gate's one load of the patched face
(schema and IR) and the frame (each layer painted twice). Both are slice
4's concern, where a drag's release pays them.

Tests: `tests/test_edit.py` (every face's index data equal to its parse;
a block list replacing `targets:` in either
style on all 29 faces, only its lines changed; a block mapping at its
indent; every palette colour of every face renamed with its references
and back, byte-identical, 177/177; a rename in expressions and lists but
not a longer name; renaming onto a sibling refused; keys and block
scalars left alone; a chain's first step checked);
`tests/test_studio_inspect.py` (every key of every element of every face
is a field; a shape's own keys; widgets; the overrides a device reads;
the Face panel's data and MIP flags; each edit and each refusal; fonts
added and replaced; one load per edit); `tests/test_studio_frontend.py`
(`values.js`). Each guard was seen red.

### Slice 4 — direct manipulation on the canvas: done

Built as below:
- **The frame is the render, fast.** `Document.frame` returns
  `wfb.preview.render`'s image and every element the frame draws (and
  every group the author wrote, in the frame's layout) with its box,
  centre and handles: 24 ms on the showcase where the layered frame took
  274. The layer images moved to `Document.layers`, fetched after the
  frame, for hit-testing by alpha and a drag's moving image; until they
  arrive a click picks the smallest drawn box. `Document.thumbnail` is the
  strip's PNG.
- **Handles** (`wfb/studio/drag.py`), from what the engine can write
  back: a line's two ends; `size:` width and height on the edge that
  moves for the element's alignment, with its gain (a centred box grows
  both ways); `radius:`; an arc's `start_angle` and `sweep` at its two
  ends. A polygon has none. A test drags every handle on five faces and
  each lands, so a handle never offers a drag the engine refuses.
- **New in `wfb/edit/geometry`:** `move(..., part="at"|"to")` moves one
  end of a line; `turn` sets an arc's angle in the author's unit, landing
  within half a degree (144/144 over the corpus, line ends 196/196); a
  gauge's `size:` is measured from its declared size, since its ticks
  grow its box; `View` reuses an analysis and the font memo, and keeps
  its last placed load (`tried`) for the gate.
- **`Document.drag`**: one gesture (`move`, `resize`, `turn`) on the
  viewed device, through the engine, the gate and the history, labelled
  "move clock by (+6, -3) px on fr955". The scope is the inspector's: "all
  targets" makes a drag write where the viewed device reads the key
  ("auto"), the device or shape its override. **One load per drag**: the
  engine's load of the landing text is the gate's.
- **The canvas** (`canvas.js`): press on an element or a handle, drag,
  release. During a move the face is drawn from its layers with the
  dragged one shifted, exact; a resize, a radius, an angle and a line's
  end draw as outlines; guides show what it snapped to. On release the
  gesture is sent and its preview stays until the new frame replaces it;
  a refusal clears it and says why. Escape cancels; Alt turns snapping
  off.
- **Snapping** (`snap.js`): a guide (the screen centre, another element's
  centre or edges) within 4 px wins; failing that, the centre goes to a
  5%r grid about the screen centre; an axis the drag did not move along
  does not snap. Lengths to the 5%r grid within 3 px; angles to 30° within
  3°, else to 6°.
- **The strip**: one small frame per target under the canvas; a click
  views that device.
- **The history is compressed**: a text version is stored as
  `<sha256>.z` (zlib), still named by the raw content's hash; a store
  written before reads as it was.

**Checked in a DOM** (jsdom against a live server): a move landing
exactly on the dragged pixels, a width handle growing a centred box by
twice the drag, an arc's sweep snapped and turned, the strip, and the
slice 3 script again. It found that two pointer events could arrive
before the re-render the first scheduled, so the handlers read the press
from a ref. Whether the shifted image feels direct is a browser
question; it is still owed by hand.

**Snapping, as first written, nudged the element on an axis it was not
dragged along**, the grid every 6.5 px outbidding the real guides; the
Node test that pinned the intended rule found it.

Measured over HTTP (Starlette's client, in-process) on fr955 at 2×, best
of four moves of each face's last element, idle machine:

| Face | release → new frame | drag (engine, gate, record) and summary | frame | layers, fetched after |
|---|---:|---:|---:|---:|
| `features/progress` | 66 ms | 52 ms | 14 ms | 62 ms |
| `showcase` | 464 ms | 442 ms | 22 ms | 292 ms |
| `features/vector-text` | 241 ms | 78 ms | 163 ms | 405 ms |

Before the fast frame and the shared load, the showcase took 690 ms from
release to frame. What remains is one load of the patched face (schema
and IR) and, for vector text, the render. **G6 stays A**: the image shift
covers the gesture, the release is one round trip of at most half a
second on the largest example, and nothing measured here needs the
browser to patch text itself. Whether it *feels* slow is the browser
check still owed; G6 B is the answer if it does.

The slice 2 corpus edits (258 changes, 29 opens) now store 1.2 MB, the
text versions 611 KB where they were 1.9 MB.

Tests: `tests/test_edit.py` (a line's ends, an arc's angles, refusals);
`tests/test_studio_drag.py` (each kind's handles; the edge a size handle
sits on for three alignments; every handle on five faces landing; the
frame, layers and thumbnail; a group as an item; a drag landing and
undone; one device's override leaving the others; one load per drag;
every refusal; the endpoints; compressed blobs and old ones);
`tests/test_studio_frontend.py` (`snap.js`). Each guard was seen red; one
that could not be (a `size:` on an arc gauge, which the compiler refuses)
was removed.

### Slice 5 — structure: done

Built as below:
- **`wfb/edit/structure.py`:**
  - `move_to_block`: an element cut with its leading comments and pasted
    into another block, re-indented: static and dynamic, a layout's own
    blocks, a group's `children:`, before a given sibling or at the end. A
    block that does not exist yet is created; an emptied one goes with
    its key. Refused: the block it is in, into itself, a non-block, a
    non-group's children.
  - `group`: sibling elements wrapped in a new group with only `type:` and
    `children:`, where the first was; side-by-side members keep the blank
    lines between them. `ungroup` lifts the children back and is refused
    for a group with any other key (`at:`, `visible:`, ...), whose children
    take something from it.
  - `add` for every type: shapes and text as before; `icon`, `gauge`
    (a battery bar), `pattern` (twelve ticks), an empty `group`; `graph`,
    `data` and `hands` take their series, slot or set, a graph with a
    range its series can show.
- **`Document.structure`**: add, delete, duplicate, reorder (within a
  block), move (between blocks), group, ungroup, gated and recorded, and
  the id to select after (the new element, the copy, the group). The tree
  lists every block an element can go to, empty ones included.
- **UI** (`layers.js`, `tree.js`): an add bar (with the series, slot or
  set a type needs, or what to declare first when there is none), and for
  the selection ↑ ↓, Duplicate (Ctrl+D), Delete (Del), Group (Ctrl/Cmd/
  Shift-click selects more), Ungroup, and "move to" any block or group.
  Rows drag: onto a row's upper half before it, lower half after it, a
  group's middle third into it, a block's label to its end.

Measured over the 29 example faces:

| Measure | Result |
|---|---|
| group the first two siblings of each block, through the gate | **69/69** (one more refused: `anchor: subscreen` is top-level only) |
| every placed box and centre unchanged by the grouping, on fr955 | **69/69** |
| ungroup the new group: the text byte-identical to the original | **69/69** (23/69 before side-by-side members kept their blank lines) |
| move each top-level element between `elements:` and `static:` | **161** accepted, **91** refused by the gate, each for a reason the compiler gives (a live reading in `static:`, a `data` element) |
| add each type (but `data`, `hands`) to each face | **348/348** |

**Checked in a DOM** (jsdom against a live server): add a circle after
the selection, a graph only once its series is picked, duplicate, move
up, a refused move to `static:` with its reason, group by Ctrl-click and
ungroup, delete. Drag-and-drop in the tree is HTML5 drag events, which
jsdom does not dispatch; its drop rule is `tree.dropTarget`, tested in
Node, and the drag itself is owed to a browser.

**Found on the way:** an empty block in the tree (`line` null) ended the
line range of the block before it, so a diagnostic below one would not
select its element (`hit.elementAtLine`).

Tests: `tests/test_edit.py` (grouping over the corpus: placement and the
round trip; moves creating and emptying blocks and into a group;
refusals; every type added); `tests/test_studio_structure.py`;
`tests/test_studio_frontend.py` (`tree.js`, and `elementAtLine` past
empty blocks). Each guard was seen red.

### Slice 6 — the YAML tab: done

Built as below:
- **G5's bundle**: `tools/studio-frontend/` (pinned `package.json` and
  `package-lock.json`, `entry.js`, `build.mjs`) is built by
  `tools/vendor-studio-frontend.sh` (`npm ci`, esbuild) into
  `vendor/codemirror.module.js`: CodeMirror 6, its YAML mode and
  `codemirror-json-schema`'s YAML schema support (lint, completion,
  hover). Its markdown renderer pulled in markdown-it and Shiki for
  highlighted hovers, 400 KB of the 1.1 MB; a stub renders descriptions as
  text with `code` spans instead, so the bundle is 700 KB. Every bundled
  package's licence and version is in `vendor/LICENSES-codemirror`.
- **`Document.replace_text`** and `POST .../text`: the whole text against
  the version it started from, recorded as one change ("edit the text"),
  loaded once (the analysis reuses it); the same text is no change.
- **A decision made in building it** (recorded here, the plan's "gated the
  same way" amended): typed text is refused only when it is not YAML, and
  then not recorded, so the author keeps typing. A text the compiler
  reports errors on is recorded, with the errors in the gutter: someone
  typing passes through broken states, and the YAML tab is where they are
  mended. The canvas, inspector and tree keep the full gate, so they
  cannot add an error to it.
- **UI** (`yaml.js`): a Face | YAML switch above the canvas. Typing is sent
  300 ms after it stops; "not YAML yet" shows under the text; a stale
  version reloads the pane with a message; a change made elsewhere
  reaches the pane when nothing typed is unsent. `wfb` diagnostics join
  the schema's in the gutter. A selection in the tree or on the canvas
  selects the element's lines (the tree gives each element its last
  line, `end`); the cursor selects the element it is in.

**Checked in a DOM** (jsdom against a live server, with the layout calls
CodeMirror makes stubbed): the pane shows the text; a typed change is
recorded; not-YAML is not recorded and its message clears when mended
(a bug found here: the message stayed when the text returned to the last
recorded one); a tree selection selects the element's lines; a stale
send reloads the pane. Typing, completion and hovers in a real browser
are owed by hand.

Tests: `tests/test_studio_text.py` (one change, no change, not YAML,
errors recorded, stale, one load, each node's last line, the endpoints);
`tests/test_studio_frontend.py` (the bundle exports what `yaml.js`
imports). Each guard was seen red.

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
