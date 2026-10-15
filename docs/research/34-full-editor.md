# 34 — A full-featured editor: why `wfb studio` is crippled, and the way out

**Question (user, 2026-10-13).** The project started as a YAML-described
watch-face generator and later grew a GUI editor, which is now "a little
crippled as a GUI editor, still good as YAML to binary": some things break
in the GUI, others are not supported at all. Research how to make it a
full-featured GUI, with full freedom to change the YAML format and to
rewrite the GUI from scratch if needed.

**Status (2026-10-13): research complete; the user took every decision in
§10 as recommended the same day.** Plan 33 built it, slice by slice, and was
deleted once built on 2026-10-15 (`docs/plans/README.md` says how to read it).

**Method.** Three audits of the code as it stands at `695d1e9` (every file
under `ts/app/`, `ts/src/studio/`, `ts/src/edit/`, the schema, the guide
and the editor's tests), a scripted replay of the inspector's own widget
rules over the whole schema, a round-trip probe of the `yaml` package's
Document API over every example face, the fast suite and a real build in
this container with the user's device files, and a live session of the
editor driven in headless Chromium (§2.4). Prior art is Samsung's Watch
Face Studio and Google's Watch Face Designer (§9).

**Short answer.**

| # | Finding | Consequence |
|---|---|---|
| 1 | **The engine under the editor is sound and should stay.** YAML text is canonical, every edit is a byte-exact text patch checked by a full load (`ts/src/edit/`), the compiler runs in a worker, history is a journal in IndexedDB, and the browser rasterises the compiler's own draw program. All of it is corpus-tested. A whole-document re-serialisation is not an alternative: the `yaml` Document API reproduces **3 of 24** example faces byte for byte (§2.5, VERIFIED) | rewrite nothing below `ts/src/studio/document.ts`'s `EDITS` table |
| 2 | **The crippling is in one layer: the inspector, the per-feature edit ops and the page.** The inspector can edit only *a scalar at a known path whose `$defs` name or key name is in a hand-kept table*; everything else is a read-only "edit this in the YAML" block. Measured over the schema: of ≈481 key slots, **≈240 (50%) get a control, 58 are shown read-only and 133 are invisible** — `aod:` on all 14 element types, `outline:` on 13, every hand part, pattern part, polygon point, gauge band and needle, `defaults:`, `face:` (§2.1, VERIFIED by script) | this layer is replaced, not patched again |
| 3 | **The editor has one flat form for one state.** A face has variants — device, screen shape, awake/asleep/AOD frame, style and layout, the wearer's picks — and the format expresses them as `overrides:`, `aod:` and `layouts:`. The GUI can *view* each (the Preview menu) but writes to only one of them, and to that one for four keys (§2.2) | the editing context (what you look at) must decide where an edit goes |
| 4 | **The two most interactive files have no automated test**, and the gate does not cover the whole pipeline. `canvas.js` and `yaml.js` are "checked by hand" (`ts/test/CLAUDE.md`), and nothing drives a browser. A live session found 13 defects, one of which bricks a face (choosing the `pt` unit commits a text the worker can no longer read) and two of which lose work (§2.4) | fix the four worst now; browser-driven tests become part of the bar |
| 5 | **The format is mostly GUI-neutral; a few shapes fight a direct-manipulation editor.** Anonymous `parts:` lists, three-way `oneOf` values (`outline:`, `icon:`, `absent:`, `range:`, `step:`), merge-vs-replace rules in `overrides:`, and opaque expression strings. Each has a small, hand-writable alternative (§5) | ten format changes are proposed, each a separate decision; none is a precondition for the rewrite |

The recommendation (§6–§7): keep the engine; add to it a list-item
primitive, a batched edit and a typed page/worker contract; rewrite the page
in TypeScript around three ideas — an **editing context** that decides
where an edit lands, a **generic schema form** so no legal value is
read-only, and **purpose-built editors** for parts, points, patterns,
expressions and templates; and take the format changes that pay for
themselves in the GUI. Sequenced as plan 33.

---

## 1. What the editor is today, and what is worth keeping

`wfb studio` (ADR 0002, amended 2026-10-01 and 2026-10-02) is a local web
app. The server (`ts/src/studio/server.ts`) serves the page, two esbuild
bundles, the device files and fonts, and runs `monkeyc` on request; it
never sees a face except the zip posted for a build. Everything else is in
the browser:

```
page (Preact + htm, untyped JS, ts/app/)        worker (TypeScript, ts/src/studio/)
  Editor state, selection, outbox,  ── api() ──►  Router: one promise queue for every request
  textsync, localStorage                          Document: text + journal head (IndexedDB)
                                                    edit  → EDITS[op] → Patch → Gate.check → commit
  ◄── summary (whole text, tree, diagnostics,       frame → render PNG + per-element draw ops + glyph tiles
      history, Face globals) on every change        inspect → schema branch → widget table
  ◄── frame / inspect / thumbnail                   analysis → load → resolve per target → lint
```

(`ts/src/studio/document.ts:149-194` the edit table, `:300-306` the
commit, `:622-668` the frame; `ts/src/studio/router.ts:156-164` the
queue; `ts/src/studio/store.ts:1-34` the store; `ts/app/hooks.js:30-87`
the outbox.)

**Sound, keep as is** (the architecture audit's verdict, confirmed by the
tests that cover each):

- **The patch engine** (`ts/src/edit/yaml.ts`, `spans.ts`, `patch.ts`,
  `gate.ts`). A patch rewrites only the characters of the node it changes,
  keeps the scalar's quote style and the mapping's flow or block style, and
  the gate refuses any patch whose text does not parse to exactly the
  intended data *and* load without a new error (`gate.ts:86-101`). Every
  op runs over the example corpus in `ts/test/edit.test.ts`. The
  primitives are generic and path-based: `setValue`, `setScalars`,
  `remove`, `renameKey`, `renameReference`, `moveElement`, `deleteElements`,
  `duplicateElement`, `chain` (`patch.ts:581-745`).
- **The geometry patcher** (`ts/src/edit/geometry.ts`): a drag is written
  in the author's own unit, rounded coarse to fine until the element lands
  on the dropped pixel, verified by re-running the layout, and goes to the
  most specific `overrides:` entry the viewed device reads (`:57-72`,
  `:262-272`).
- **The store** (`store.ts`): content-addressed text, a journal in which
  undo and redo are records too, a timeline, snapshots and compaction;
  52 tests in `ts/test/studio.test.ts`.
- **The worker compile loop and router shape**: version-checked requests,
  events to other tabs, server reduced to assets and build.
- **The bundle** (`bundle.ts`): path checks and limits on upload.
- **The canvas's model of truth**: the browser never decides what a face
  looks like; it draws the compiler's draw ops with its own rasteriser,
  shifted for a live move (`ts/app/canvas.js:184-190`), and shows an
  outline where it cannot be sure (research 28, 29).

Of the whole TypeScript stack (`ts/src/`, about 35 000 lines), the editor-specific part is
about 6 200 lines in `ts/src/studio/` and `ts/src/edit/` plus 4 300 lines of
page JavaScript in `ts/app/` (vendored libraries aside). The rewrite proposed below replaces the page
and about 1 100 lines of the studio layer (`inspect.ts`, the `EDITS` table
and `editPath` in `document.ts`, the Face-tab globals), and keeps the rest.

## 2. Why it feels crippled — measured

### 2.1 Coverage against the format

The inspector is generated from the schema branch of the element's `type:`
(research 26 §4.6). `widget()` (`ts/src/studio/inspect.ts:97-121`) picks a
control by, in order: a `$ref` chain to one of twelve `$defs` names
(`WIDGET_BY_REF`, `:40-46`: lengths, angle, align, five colour refs,
`visible`/`expression`), four nested object refs shown one level down
(`NESTED`, `:48`: `position`, `size`, `patternStep`, `curve`), nine
key-name special cases (`:105-114`), then the JSON type, else **`yaml`** —
which `ts/app/panels.js:199-201` renders as a read-only `<code>` block
captioned "edit this in the YAML". `SKIPPED` (`:50`) hides `children`,
`overrides` and `parts` outright.

Replaying those rules over `schema/wfb-face-2.schema.json` by script
(VERIFIED, 2026-10-13):

| Where | Key slots | Real control | Read-only | Invisible or skipped | Correctly hidden |
|---|---:|---:|---:|---:|---:|
| 14 element types × their keys | 306 | 192 (+93 children of 22 object fields) | 48 | 16 | 50 |
| face level (`face`, `build`, `defaults`, `resources`, `theme`, `config`, `layouts`) | 68 | ≈31 | ≈10 | ≈27 | — |
| part vocabularies (`handPart`, `patternPart`, `hand`, `handSet`, `patternCurve`) | 58 | 17 | 0 | 41 | — |
| `aod:` blocks (ten per-kind defs) | 49 | 0 | 49 (as one `yaml` block each) | 4 (`defaults.aod`) | — |
| **total** | **≈481** | **≈240 (50%)** | **≈58** | **≈133** | 36 |

The read-only and invisible slots are not the obscure corners. They are:

- `aod:` on every one of the 14 types (`inspect.ts` has no rule for the
  `aod*` refs), and `defaults.aod` nowhere at all;
- `outline:` on 13 types: its schema is `oneOf [const none, colour, {color,
  width}]` with no branch carrying a top-level `$ref`, so the `oneOf`
  resolution research 33 added for `step:` (`:99-104`) never matches;
- `absent:` on `text`, `gauge` and `pattern` (an `anyOf`), though the same
  key is a text box on `data` — and `absent:` is **required** the moment a
  placeholder reads a nullable source, so the inspector's own **+ data**
  button leads to a build error only the YAML tab can mend;
- `graph.range` (`int | "4h"`), the same `oneOf` class as `step:` was;
- `pattern.skip`, `gauge.bands`, `gauge.needle`, `polygon.points`: lists;
- every hand part and pattern part (41 slots): anonymous lists in a local
  frame, reachable only through "edit in YAML" links
  (`panels.js:518-519, 546`);
- `face.name`/`version`, `defaults.antialias`/`min_1px`, every font option
  but `size` and `source` (`glyphs`, `antialias`, `monospace`, `align`,
  `face`), `paletteEntry.label`, `scheme.label`, `layout.lint`,
  `styleEntry.lint`, `lint: {allow, reason}` anywhere: no section reads
  them;
- `layouts:` can be created but not renamed or deleted
  (`document.ts:181-186` is the only layout op); style entries, palette
  entries and slot choices cannot be reordered, though their order is
  semantic (a style's position is its on-device `styleId`).

On the canvas: 13 of 14 types move, 7 resize, 2 turn, the line has end
handles, and a polygon has nothing — a move is refused with "move its
`points:` in the text" (`ts/src/edit/geometry.ts:338`). Text and icons have
no size handle (a text's size lives on its font resource; an icon's `size`
is a scalar `drag.ts:72` does not offer), and no handle reaches
`thickness`, `corner_radius`, a polar `at:` directly, a pattern's `step:`
or any part's geometry.

The example census (30 faces) shows where authors actually spend their
keys: `at:` 489 times, `color:` 516, 59 `parts:` lists, 83 `lint:` blocks,
90 text templates, 9 `aod:` blocks, 5 faces with `layouts:`, 14
expressions, **0 `overrides:`**. So the dead ends are hit by every face
with hands or ticks (parts), by every face with a bezel allowance (`lint:`),
by every AMOLED target (`aod:`), and by every text that reads a nullable
source (`absent:`).

### 2.2 The ceiling, precisely

The schema-generated inspector and the hand-written ops can only ever edit
**a scalar at a known author path**; the patch engine can create a missing
*mapping* key but **never a list item** (`patch.ts:294`, "cannot create the
list item": the only list edits are whole-list replacements, as `SlotCard`
does for `choices:` at `panels.js:342-345`). Every missing feature is a
structured value, a list, or a second *view* of the same element:

- `aod:` and `overrides:` are **the same property under another
  condition**. The inspector has one flat form for one state; `editPath`
  (`document.ts:458-474`) lets only `at`, `size`, `radius` and `align` go to
  a device or shape selector, refuses everything else with "cannot be
  overridden per device", and can never write a `display:` selector
  (`geometry.ts:62-72` reads one, writes device or shape). Colour and
  `visible:` overrides are listed read-only (`inspect.ts:144-164`).
- Each face-wide feature is **a hand-written compound op plus a hand-written
  panel**: 3 generic ops (`set`, `remove`, `rename`) and about 30 per-feature
  ones (`document.ts:149-194, 487-535`; `schemes.ts` 8, `hands.ts` 4,
  `colors.ts` 4, `slots.ts` 1, `structure.ts` 5), each with its own refusal
  strings (`Refused(` appears 114 times across the five files). Adding
  "rename a layout" is an `EDITS` entry, a panel row, tests and a guide
  paragraph; the GUI grows linearly with the format and never catches up.
- The page is **untyped JavaScript consuming an unwritten contract**:
  `summary()`, `frame()`, `inspect()` and `globalsOf()` return ad hoc
  `Record<string, unknown>` (`document.ts:759-770`, `inspect.ts:189-219,
  285-350`) that `panels.js` reads by field name; `tsconfig.app.json` checks
  the page with `strict: false`. State is spread over a 400-line `Editor`
  component with ~20 hooks (`app.js:434-836`), the outbox, the YAML pane's
  own save machine (`yaml.js`, `textsync.js`) reconciled after the fact
  (`app.js:623`), and `localStorage` used as a message bus to make the
  Face tab remount on a section (`app.js:469-474`, `panels.js:291-297`).
- **One queue for everything** (`router.ts:156-164`): edits, frames, the
  per-target thumbnails and inspections wait on each other; a drag runs the
  full front end once per candidate rounding step (`geometry.ts:262-272`),
  then the summary re-resolves and re-lints every target. The strip's
  one-second settle (`canvas.js:472-485`) and the outline-only previews
  while a resize is queued (`outbox.js:361-371`) are its visible symptoms.

None of this is in the compile loop, the store or the text-patching
primitives. The ceiling is in the layer between them, which is why
research 33's GUIv2 pass — seven slices of new widgets in the same layer,
all built — moved the coverage figure but not the feeling.

### 2.3 What is not tested

About 245 tests touch the editor, headlessly: the store and journal, every
edit op over the corpus, every live handle's prediction, the inspector's
widget choice, the Face panel and Layers rendered over a 96-line fake DOM
with their buttons clicked, and the whole page against a stand-in worker
(`ts/test/page-*.test.ts`, `studio*.test.ts`). **Not tested anywhere:**
`canvas.js` (pointer events, hit-testing against real layers, the overlay),
`yaml.js` (CodeMirror), the hooks as hooks (`usePanZoom`, `useShortcuts`,
`useClipboard`, `useFrame`), the real worker (`IdbBackend`,
`BroadcastChannel`), any pixel of the page, and multi-tab behaviour against
real IndexedDB. `ts/test/CLAUDE.md` says so: "Nothing drives a browser: the
pages are checked by hand." Chromium and Playwright are available on the
development machines and in this container; nothing uses them.

### 2.4 What breaks — a live session

The editor was driven in headless Chromium (Playwright 1.56, 1600×1000,
zoom 2×) against the real server and worker with the user's 22 device
files: every example face (24) and template (11) opened; every Layers row
of every face inspected; 83 moves, 71 handle drags and 166 nudges, each
undone to byte-identical text; every Properties control, Layers action,
Face-tab section, YAML-tab path, view-bar control, Ctrl+K, History,
Download and one `monkeyc` build. No console error, page error or failed
request was logged in any run. VERIFIED (2026-10-13); the harness and
screenshots were kept outside the repository.

**Most of the documented surface works as documented**, including the
hard parts: unit-preserving drags that land on the pixel, snapping, Alt
and Escape, group moves, overrides written for the viewed device, the
colour picker's three groups and automatic naming, compound scheme edits,
slot cards from both sides, text merging in the YAML tab, undo across
tabs and across two tabs of one browser, rapid drags recorded in order.
Timings: first frame 70 ms (gauge) to 1.7 s (showcase); a move 337 ms
median from mouse-up to the new version; a handle 198 ms; a nudge 48 ms; a
Properties edit 150–600 ms; the showcase built for `fenix8solar47mm` in
5.2 s.

**Defects found**, worst first:

| # | What | Severity | Cause (verified in code unless marked) |
|---|---|---|---|
| 1 | **Switching a length's unit to `pt` in Properties (offered on every length), or typing `4pt` in the YAML, bricks the face**: the change is committed, then every `get`/`frame`/`cover` throws `pt units need a reference font; none is in scope here`; Undo is disabled, a reload sits on "Loading…" for ever, the library cover is blank, and the face cannot be opened again (Download still works) | data loss | the gate loads the patched text (parse → schema → IR, `gate.ts:86-101`) where `pt` is legal; `Length.resolve` throws `UnitError` later (`ts/src/units.ts:55`) inside `resolveAll`, which `Document.analysis()` calls uncaught (`document.ts:578-580`), and `analysis()` feeds every read. The same hole lets a target the face cannot draw on be added silently (defect 12) |
| 2 | **Changing a unit keeps the number**: `sweep: 360deg` → `360turn`, `dx: -50%r` → `-50px`, written at once with no message | wrong result | `ts/app/panels.js:65`: `onChange … send(String(q.number), e.target.value)` |
| 3 | **A thin element cannot be moved**: a press on a 4-px bar resizes it (`height: 3%r → 5%r`) | wrong result | `canvas.js:394-395` tests the handles' 7-px zone before the ink pick, with no exclusion for an element smaller than the zone |
| 4 | **Ctrl+K and the Properties "Schemes" link do not switch the Face-tab section when the Face tab is already open** | wrong result | `openFaceSection` writes `localStorage` and switches tab; `useFaceSection` reads it only in its `useState` initialiser (`app.js:469-474`, `panels.js:291-297`) |
| 5 | **+ Layout is refused on a face whose styles name only schemes** (`config.style.choices.dark: needs 'layout:'`) | missing feature | `add_layout` (`document.ts:181-186`) adds a style only when none exists; it never gives existing entries a `layout:` |
| 6 | **Any file is accepted as a font** ("+ Font from a file…" with a zip): written, and the face stops drawing with `unknown file format` | wrong result | `addAsset` stores any bytes (`document.ts:409-418`); only the input's `accept` attribute guards |
| 7 | **`curve:` and a polar `at:` cannot be created from Properties**: each half of a required pair is refused alone (`missing required key 'radius'`) | missing feature | nested-object children are set one key at a time; no compound edit supplies the sibling |
| 8 | Removing a device override with × leaves `overrides: {fenix8solar47mm: {at: {}}}` behind | cosmetic | `remove` prunes nothing above the key |
| 9 | Controls that can never succeed are offered and then refused: `on_hold` types other than `auto` on `data`, `unsupported` on a rectangle, `anchor: subscreen` on a `static:` element (with a message about "a group's child"), a bar gauge switched to `arc` ("carries bar-only key: size"), deleting the starting style, removing one style's scheme | refused with reason | the inspector offers the schema branch's keys without the compiler's per-kind rules |
| 10 | **+ add…** with a `static:` element selected refuses `data`/`gauge`/`graph`/`hands` instead of placing them in `elements:` | refused with reason | the add goes in front of the selection |
| 11 | **A drag or YAML typing followed within a second by a reload is lost** (the guide promises nothing is lost) | data loss, narrow | the outbox posts to the in-page worker with no `beforeunload` flush (`hooks.js:30-87`); the YAML debounce is 300 ms |
| 12 | Adding a target the face cannot draw on is accepted silently; the face stops loading | low | as 1: resolve-time errors are outside the gate |
| 13 | Small: non-numeric text in a number box is ignored silently; a face whose targets are not installed shows an empty Device select and "No frame yet" with Build enabled; a slot's ★ is two history entries; `+ Slot` on the minimal template places an element off screen; deleting a used colour or font shows the raw compiler error rather than the guide's "refused while something uses it" | cosmetic | — |

Defects 1, 2, 11 and 12 are the "some things break"; 5, 7, 9 and 10 are
the ceiling of §2.2 seen from the author's chair (a required pair, a
compound edit, per-kind rules the schema branch does not carry); 3 and 4
are the untested files of §2.3. The dead ends the session hit most, in
order: `absent:` (15 of 35 faces; read-only on `text`/`gauge`/`pattern`
though editable on `data`), `outline:`, `graph.range` (required, every
graph), `curve:`/polar `at:` from scratch, `aod:`, polygon points, `lint:`,
`gauge.needle`/`bands`, `pattern.skip`, `icon: {for:}`, parts.

Not finished in the session: the YAML tab's two-tab conflict flow
("Keep my text / Take the face"), a drag on a `pt`-keyed text (blocked by
defect 1), and the bare-`.yaml` download warning. UNVERIFIED.

### 2.5 Re-serialising the document is still not an option

ADR 0002 and research 26 §3.2 rejected a load-then-dump editor because a
ruamel round trip reproduced 0 of 29 faces. The TypeScript stack's `yaml`
2.9.1 has a comment-preserving Document API, so the question was re-run
(VERIFIED, 2026-10-13, scratch probe over `examples/*/face.yaml` and
`examples/features/*/face.yaml`): `parseDocument(text).toString()`
reproduces **3 of 24** faces byte for byte with default options and 3 of
24 with folding off (`lineWidth: 0`). What changes is cosmetic but
everywhere: comment alignment collapses to one space, flow collections
gain inner spaces (`[a, b]` → `[ a, b ]`), a comment on a key's line moves
below it, blank lines before a block comment move, and long quoted strings
fold or unfold. On the showcase 673 of 964 lines differ. A model-canonical
editor would therefore rewrite the author's file on first save, which the
decision forbids and the user's own faces (the dashboard playground is
hand-formatted) would suffer from. The text-patch engine stays.

## 3. What "full-featured" has to mean here

Derived from the format (every key the schema admits), from what a watch
face designer does in Watch Face Studio (§9), and from the editor's own
guide:

1. **Every legal value is editable in a structured control**, with the
   YAML tab as a power tool, never as the only way. The read-only
   fallback exists only for a key the schema does not know.
2. **Variants are first-class.** The author picks what they are looking at
   — watch, screen shape, awake/asleep/AOD, style, the wearer's picks — and
   edits *that*; the editor writes to the element's own key, to the right
   `overrides:` selector, to its `aod:` block or to the layout, and shows
   where every effective value comes from.
3. **Geometry is manipulated where it is seen**: hand parts and pattern
   parts in their local frame, polygon vertices, a text's size, a pattern's
   step and count, a gauge's angles and bands.
4. **Data binding is built, not typed**: a placeholder's source, format and
   absence; a condition's source, operator and value; a colour that follows
   data.
5. **Face-wide structure is a matrix, not a scroll**: layouts × schemes ×
   styles as the wearer sees them, slots as the one object they are, fonts
   with every option.
6. **Lists are lists**: add, remove, reorder — for points, parts, bands,
   choices, targets, palette, style entries.
7. **Layers are a real layer panel**: search, lock, hide-in-editor, rename,
   multi-select, and the same tree for a hand set's or pattern's parts when
   editing one.
8. **It does not break**: a typed contract between page and worker, and
   browser-driven tests for the canvas and the YAML pane.
9. **Nothing only through the GUI** (ADR 0002) still holds: every control
   maps to a documented key, and the file the author downloads keeps their
   comments and formatting.

## 4. Options for the editing model

**A. Keep patching the inspector** (another GUIv2-style pass). Costs
nothing up front; each gap becomes a widget, an op and a panel. §2.2 says
why this never arrives: the structural gaps (lists, variants, parts) are
not widgets, and research 33 §5 already deferred exactly those three as
"a design problem, not a widget". Rejected.

**B. Rewrite the page and the inspector contract in TypeScript over the
existing engine.** Keep `store.ts`, `router.ts`/`worker.ts`, `gate.ts`,
`spans.ts`/`yaml.ts`, `patch.ts`'s primitives, `geometry.ts`, `bundle.ts`
and the rasteriser; replace `ts/app/`, `inspect.ts`, the `EDITS` table and
the Face-tab globals with the model in §6. The engine needs three additions
(§7). This is the recommendation: it removes the ceiling where it is and
keeps the ten thousand lines of compiler, patcher and tests that work.

**C. A model-canonical editor** (parse → model → re-serialise). Rejected by
the probe in §2.5 unless the project accepts normalising every file it
opens. It would also discard the patch engine for no gain: the generic
`setValue`/`remove` by path already give a model-shaped API over the text.

**D. A third-party canvas or editor framework** (tldraw, Fabric, Konva,
Penpot's). The canvas here draws the compiler's draw program at the
watch's resolution with the compiler's rasteriser; a framework's own shape
model would be a second, drifting model of the face (research 06 §6, 26
§3). Rejected for the canvas. CodeMirror stays for the YAML tab; Preact
stays as the view library (the rewrite is of the page's model, not its
renderer).

## 5. Format changes that pay for themselves in the GUI

The patch engine is path-based and format-agnostic; the code that knows
format 2 is exactly the layer the rewrite replaces (`inspect.ts`,
`EDITS`/`editPath`, `structure.ts`'s `CHOICES`, the colour/scheme/hand/slot
modules, `panels.js`). A format change therefore costs the compiler, the
schema and the guide, not the engine, and each should be decided on its
own merits. Each below is UNVERIFIED as to cost until planned; none blocks
the rewrite, because the generic schema form (§6.2) edits the current
shapes too. ADR 0009's procedure applies: a key that changes becomes a
schema error naming its replacement, as format 2 did; a shorthand kept as
sugar is a desugaring pass, as the mapping form of elements is.

| # | Change | Why the GUI wants it | Hand-written form after |
|---|---|---|---|
| F1 | **Id-keyed parts** in `hand_sets.<set>.<hand>.parts`, `pattern.parts` and `gauge.needle`: a mapping of named parts, like `children:` | the Layers tree, Properties and the canvas treat a part as an element with an id; a drag has a stable path to write to; the reserved data widget's `parts:` gets the same editor | `parts: {blade: {type: polygon, points: [...]}, hub: {type: circle, radius: 4%r}}` (the list form stays readable as sugar, ids `part1`…) |
| F2 | **`mirror: x`** on a polygon part | half the vertices to drag; symmetric hands by construction | `blade: {type: polygon, mirror: x, points: [{dx: 3%r, dy: 6%r}, {dx: 2%r, dy: -38%r}, {dy: -44%r}]}` |
| F3 | **Tagged `absent:`**: `hide` \| `{text: "--"}` \| `{value: expr}` | three radio states instead of a string that might be the word `hide`; the same control on `text`, `data`, `gauge`, `pattern` | `absent: {text: "--°"}` |
| F4 | **`outline:` is an object or absent**; `none` legal only inside `aod:` | one control (colour + width); the tri-state `oneOf` goes | `outline: {color: color.bg, width: 2px}` |
| F5 | **`icon:` object forms** beside the bare name: `{name:}` \| `{codepoint:}` \| `{for: expr}` | the picker has three tabs; `{for:}` stops dropping to read-only | `icon: {for: weather.condition_today}` (a bare name stays as sugar) |
| F6 | **`graph.range` as `{samples: n}` \| `{duration: 4h}`**, and a pattern's `step:` split into `step_angle:` and `step: {dx, dy}` | a value with one shape per key needs no shape sniffing | `range: {duration: 4h}`; `step_angle: 30deg` |
| F7 | **`overrides:` with whole-key replacement**, the same key allowlist on every kind, and `display:` selectors written like the others | one rule for "where does this edit go" and one chip row per key (default · fr955 · rectangle · amoled); no deep-merge-for-`at`-but-replace-for-`align` table | unchanged spelling; a partial `at:` override must repeat the whole `at:` |
| F8 | **A text element's own font**: `font: {source:, size:}` desugared into a deduplicated `resources.fonts` entry | a text gets a size handle, and "+ Text" needs no prior font resource | `font: {source: assets/Oswald.ttf, size: 22%r}`; `font: font.clock` stays |
| F9 | **`label:` on a layout; `base:` on a scheme**; `styles` entries and slot `choices` keep their order as today | the Styles matrix derives labels; a scheme no longer has to repeat every role; reorder controls have one meaning | `light: {base: dark, bg: color.white, fg: color.black}` |
| F10 | **Rule lists as the GUI's spelling of a conditional value** — the vocabulary format 2 already reserves (`docs/limitations.md` §2, "Reserved by format 2") | a condition is source · operator · value rows with an `else`; the expression string stays as the power-user form the editor round-trips through `expr.ts` | `color: [{when: system.battery < 20, value: color.low}, {else: color.accent}]` |

Considered and **not** recommended:

- Making `at:` carry an explicit mode (`offset: [dx, dy]` / `polar: [angle,
  radius]`). It touches 489 `at:` keys in the examples alone for a toggle
  the GUI can derive from which keys are present.
- `aod: {visible}` → `aod: {show: always|never|when:}` and `aod.text` → a
  spec. The cascade is documented and the GUI can present it as an
  awake/AOD switch with provenance; the renames buy little.
- Dropping `pt`. Zero uses in the corpus, but it costs nothing to keep and
  the GUI simply does not offer it for a drag.
- Editor metadata in the file (`editor: {locked, hidden}` per element).
  ADR 0002's "nothing GUI-only" is worth more than Figma-style locks
  travelling with the design; locks and hide-in-editor live in the
  browser's per-face storage (§6.5). This is D9 in §10 because the user
  may weigh it differently.

## 6. The editor as it should be

### 6.1 The editing context

One bar above the canvas holds what today's view bar and Preview menu hold
— **watch · shape · frame (awake/asleep/AOD) · style · wearer's picks ·
time** — and it means two things at once: what the canvas draws, and
**where an edit goes**. Properties shows every key's *effective* value for
that context with a provenance badge: *own*, *override fr955*, *override
shape:rectangle*, *aod*, *inherited from group `info`*, *defaults*. A drag
or a change writes to the context's layer; **Edit for all watches** and
**Edit for this frame only** flip the target explicitly. This replaces the
three scope buttons, the read-only override list and the `aod:` dead end
with one mechanism, and is the only way to give `aod:` an editor without a
second parallel form (research 33 §5's open question).

### 6.2 A generic form, then purpose-built editors on top

The Properties panel is built from the schema **recursively**: an object is
a fieldset, a list is a list editor (add, remove, reorder, each item its
own form), a `oneOf`/`anyOf` is a segmented control over the branches with
the value's shape pre-selecting one, an `enum` a select, a `$ref` to a
known def a dedicated control. The read-only fallback exists only for a
key the schema does not have. On top of the generic form, keys with a
better model get a purpose-built editor, declared per key, not per type:

| Key | Editor |
|---|---|
| `at`, `align` | anchor picker on a miniature of the parent box, cartesian/polar toggle derived from the keys present, drag on canvas |
| lengths | number + unit, with the device's pixel equivalent beside it |
| `color`, `track_color`, roles | today's picker (this face · MIP 64 · custom), plus **follows data…** which opens the condition editor (F10 or an expression) |
| `text` | a chip editor over `parseTemplate`: literal chips and placeholder chips (source picker, format spec picker per source type, unit), `absent:` right beneath it |
| `visible`, `value`, `max`, `min` | the condition editor: source · operator · value rows, `else`, or a raw expression |
| `font` | system fonts and the face's fonts, with a size handle on canvas (F8) |
| `icon` | the catalogue picker, a codepoint, or **follows data** |
| `outline`, `aod`, `overrides` | sections of the same form, shown by context (§6.1) |
| `points` | a vertex list, each vertex draggable on canvas, add on a segment, delete |
| `parts` (hands, pattern, needle) | **enter the set**: the canvas shows the local frame (axis, 12 o'clock, `%r` ring), the parts as selectable elements, the other hands or copies ghosted; Layers lists the parts; Properties edits a part like any element |
| `pattern` | count, step, skip, columns with the copies ghosted live; copy 0 editable in place |
| `bands`, `choices`, `targets`, palette, style entries | list editors with drag-to-reorder |
| `lint` | the diagnostic's own row offers **accept here…** which writes `lint: {allow, reason}` |

### 6.3 The Face as a whole

The Face tab keeps its sections and gains the ones missing: **Face** (name,
version, id), **Defaults** (antialias, min_1px, AOD defaults), **Layouts**
(rename, delete, label), and a **Styles matrix** — layouts across, schemes
down, each cell a style entry the wearer will see, with the default
starred, drag to reorder, labels editable. Slots, hand sets and fonts stay
as cards editable from both sides (research 33 §3's pattern).

### 6.4 Layers

The tree gains search, lock and hide-in-editor (browser state, not the
design), drag-reorder across blocks and layouts as today, and switches to
a part's tree when a set or pattern is entered (§6.2). `z:` is shown as a
badge where it is written, since it and document order both order drawing.

### 6.5 Page state

The page becomes TypeScript bundled like the worker (esbuild, `strict`),
importing the worker's own types for every payload (§7), with one store
for editor state (document summary, selection, context, pending edits,
view) in place of the outbox/textsync/ref/localStorage spread. Per-face
browser state (locks, hidden rows, zoom, last section) lives in IndexedDB
beside the face, not in `localStorage` keys.

## 7. What the engine needs

Three additions, each small against what exists:

1. **List-item primitives** in `patch.ts`: insert at index, remove at
   index, move between indices, for block and flow sequences, with the same
   byte-exact rules as the mapping primitives and the same corpus test.
   Everything list-shaped in §2.1 needs it.
2. **A batched edit**: one request carrying several primitive ops applied
   in order to one text, gated once, committed as one history entry with
   one label. `chain` already composes two patches (`patch.ts:398`); the
   batch makes compound edits (a scheme added, a slot renamed with its
   references, a style row moved) composable from the page without a new
   hand-written `EDITS` entry each. The per-feature modules that encode
   format knowledge the page should not duplicate (reference renames,
   dangling-reference refusals) stay as named ops.
3. **A typed contract**: the summary, frame, inspect and globals payloads
   as TypeScript interfaces exported by the worker and imported by the
   page; `Record<string, unknown>` goes.

Two improvements are worth taking with them: writing `display:` selectors
(`geometry.ts:62-72`), and two lanes in the router (`router.ts:156-164`) so
a thumbnail never queues ahead of an edit.

## 8. Testing and the device files

The editor's defects live where nothing drives a browser (§2.3, §2.4). The
rewrite's bar is **Playwright tests against the real server and the real
worker in headless Chromium**: open each example, select each element,
drag each handle, use each Face section, type in the YAML tab, undo, build
one device — the scenarios of §2.4 as regression tests. Chromium is
pre-installed in this container and on the user's host.

Those tests need device files, which are Garmin's and cannot be committed
(`CLAUDE.md` §2). Two routes, both UNVERIFIED until tried:

- **The user's files as a CI secret**: the archive the user already
  uploads to a session (22 devices, 110 MB with fonts) stored as an
  encrypted artifact the workflow unpacks into `vendor/`. Simple; the
  licence question is the user's to judge.
- **A synthetic fixture device** (`wfbtest`): `compiler.json`,
  `simulator.json` and a skin written by the project, the SDK-wide
  `bin/api.debug.xml` standing in for the per-device one, and the font
  registry's free stand-ins for its system fonts. It would make the fast
  suite and the browser tests runnable from a clean clone, and the
  goldens could freeze its output. Whether the compiler's device loader
  accepts a device with no `.cft` fonts, and whether `monkeyc` accepts a
  device id it does not know (it will not; builds would stay on real
  devices), needs a probe.

**The fixture probe (2026-10-15)**, with `ts/test/fixtures/devices/` the
only device folder visible (`WFB_DEVICES`, plus a new
`WFB_DEVICE_REFERENCE` for its reference page), SDK 9.2.0:

- VERIFIED: the loader accepts a device with no `.cft` font. Its nine
  `FONT_*` entries name `RobotoCondensed-Regular`, `RobotoCondensed-Bold`
  and `Roboto-Black`, which the registry's stand-ins cover exactly, and
  `Device.systemFonts` measures every one.
- VERIFIED: the SDK-wide `bin/api.debug.xml`, linked into the device
  folder as `wfbtest.api.debug.xml`, loads, and its functions and fields
  answer, but it has no `<dataEntry type="module">` rows, so
  `hasModule` is false for every module: the complications example lints
  with `warning[api-gated]: hr_value: 'complication.heart_rate' needs module
  Toybox.Complications, which wfbtest lacks`. The fixture ships its own
  symbol table instead, written for the project, listing every module,
  function and field the compiler asks about.
- VERIFIED: with no symbol table at all, the lint degrades to notes
  (`note[api-gated]: wfbtest: no symbol table, so API-level gating is not
  checked`), but two paths throw rather than degrade: resolving a `face:`
  font (`DeviceError: wfbtest: missing wfbtest.api.debug.xml` from
  `layout.ts`'s `vectorGate1Ok`) and generating a design that uses a
  module (the same error from `availability.ts`'s `computeGuards`).
- VERIFIED: with the fixture's own table, `examples/features/shapes`
  retargeted to `wfbtest` loads, resolves, lints with no diagnostic,
  generates and renders a frame in its skin; so do 28 of the other 29
  examples. `features/instinct` errors (`subscreen`), as it should on a
  watch with no subscreen.
- VERIFIED: `monkeyc` refuses the id: `error[monkeyc]: Invalid device id
  specified: 'wfbtest'.` Builds stay on real devices.
- VERIFIED: `wfb studio` started with the overrides opens a design
  targeting `wfbtest`, draws it, lists its layers and applies a drag
  (a scratch Playwright test over `browser/harness.ts`).
- VERIFIED: the existing suites are written against real devices by
  name. On the fixture alone 21 of the fast suite's 43 files pass whole,
  `fixture-device.test.ts` among them (154 tests, run in a copy of the
  repository with no device file, no SDK and an empty home folder); the
  other 22 fail, mostly on `unknown device
  'fenix8solar47mm'.  Installed: wfbtest`. The goldens are frozen on the
  real set, so they cannot run on the fixture without a second golden set.
- VERIFIED: the browser suite is written against real devices too. On the
  fixture alone `open.test.ts` passes 29 of 30, but only because each
  example takes the "targets not installed here, no frame" branch; "every
  template on the home screen opens and draws" fails, and `build.test.ts`
  and the first `canvas.test.ts` tests fail waiting for a frame
  (`page.waitForFunction: Timeout 60000ms exceeded`). The rest of the suite
  was not run on it.

So the secret stays the route for the full suites, and the fixture carries
a fork's pull request: the type check, those 21 files, and
`ts/test/fixture-device.test.ts` among them (`docs/development.md`,
"Continuous integration").

The three failures the fast suite shows in this container are not
regressions: the goldens were frozen with five devices (`venusq2`,
`instinct2`, `instinct2x`, `instinct3solar45mm`, `instincte45mm`) the
uploaded set lacks (VERIFIED, `ts/test/goldens.test.ts`,
`ts/test/overrides.test.ts:82`).

## 9. Prior art, briefly

**Samsung Watch Face Studio** (the editor for Google's Watch Face Format,
the one text-first format with several editors on top, research 04) is the
reference for what a watch-face designer expects: a layer list with search,
show/hide, lock and rename; components for text (static or tag-driven, with
curved text by angle and direction), images, shapes with fill and border,
linear and circular progress, analog hands with per-hand images and
rotation settings, digital clocks, indexes; grouping and masking; a
Properties tab of placement, colour (solid or gradient), text appearance,
theme colour and actions; conditional lines (show a layer by time range,
step goal, battery, event, weather); styles (image styles, theme palettes
of three colours, up to thirty per face) merged by a Customization Editor
into the style sets the wearer picks; a run panel that simulates time,
date, battery, steps, heart rate, notifications and weather in active or
always-on mode, with a timeline; always-on analysis of the on-pixel ratio;
and run on device. **Google's Watch Face Designer** (August 2025) is a
Figma plugin over the same format: digital and analog time, interactive
and ambient modes, custom fonts, complications, themes generated from Figma
styles, a live preview and export to Android Studio or Watch Face Studio.

What transfers: the layer panel's search/lock/hide (§6.4), conditions as
rows rather than strings (F10, §6.2), a style matrix the wearer's menu is
generated from (§6.3), the run panel as the editing context (§6.1, which
`wfb studio`'s Preview menu already is in viewing form), and the always-on
view as a first-class state. What does not: image-first design (this
project's elements are vector and compiled, by ADR 0003 and constraint 11),
gradients and masks (constraints 3 and 10), and a GUI-owned project format
(ADR 0002).

Sources: Samsung Watch Face Studio user guide, "Create a watch face"
(developer.samsung.com/watch-face-studio/user-guide/create.html); Android
Developers Blog, "Introducing Watch Face Designer" (August 2025).

## 10. Decisions for the user

| # | Decision | Options | Recommended |
|---|---|---|---|
| D1 | The editing model | A keep patching · **B rewrite the page and inspector over the engine** · C model-canonical · D a framework | **B** (§4) |
| D2 | Engine additions | list primitives + batch + typed contract now · as needed | **now**, as plan 33's first slice (§7) |
| D3 | The editing context as the place edits go (`overrides:`, `aod:`, layouts) | **yes** · keep scope buttons and read-only lists | **yes** (§6.1) |
| D4 | Format: id-keyed parts and `mirror:` (F1, F2) | **take** · keep anonymous lists | **take**: it is what makes a parts editor an ordinary element editor |
| D5 | Format: the four shape clean-ups (F3 `absent:`, F4 `outline:`, F5 `icon:`, F6 `range:`/`step:`) | **take all** · take some · none | **take all**; each is a one-day compiler change and removes a shape-sniffing special case |
| D6 | Format: `overrides:` whole-key replacement and `display:` writes (F7) | **take** · keep merge rules | **take** |
| D7 | Format: a text's own `font: {source, size}` (F8) and `label:`/`base:` (F9) | take · defer | **take F8, F9** |
| D8 | Format: rule lists as the conditional spelling (F10) | build with the condition editor · defer, expressions only | **build**: the vocabulary is reserved already, and the editor's condition rows need a target spelling |
| D9 | Editor-only state (locks, hidden rows) | **browser storage** · an `editor:` key in the file | **browser storage** (ADR 0002) |
| D10 | Tests and device files | **Playwright + the user's files as a CI secret** · a synthetic fixture device · hand checks as today | **Playwright now, with the files; probe the fixture device** (§8) |
| D11 | Sequence | engine → page shell at parity → Properties v2 and context → parts/points → data editors → format changes · format first | **engine first, format changes alongside the editor that needs each** (plan 33) |

---

## Sources

- ADR 0002 (authoring interface), 0004 (element model), 0009 (format
  versioning, amendments of 2026-09-29 and 2026-10-04).
- Research 26 §3–§4 (the editor's design), 28 (open questions closed),
  29 (browser renderer), 30 (editor gaps), 33 (GUIv2) and 18 §8 (rule
  lists).
- `ts/src/studio/inspect.ts` (`WIDGET_BY_REF` :40-46, `NESTED` :48,
  `SKIPPED` :50, `widget` :97-121, overrides :144-164), `document.ts`
  (`EDITS` :149-194, `editPath` :458-474, structure :487-535, `frame`
  :622-668, `summary` :759-770), `router.ts` (:156-164), `store.ts`,
  `worker.ts`; `ts/src/edit/patch.ts` (:294, :398, :581-745),
  `geometry.ts` (:26-31, :57-72, :262-272, :338), `structure.ts`,
  `schemes.ts`, `hands.ts`, `colors.ts`, `slots.ts`, `gate.ts` (:86-101).
- `ts/app/app.js` (:434-836, :469-474), `panels.js` (:199-201, :342-345,
  :518-519, :546), `canvas.js` (:184-190, :472-485), `outbox.js`
  (:361-371), `hooks.js` (:30-87), `yaml.js`, `textsync.js`;
  `ts/tsconfig.app.json`.
- `schema/wfb-face-2.schema.json`; `docs/guide/studio.md`,
  `placement.md` ("Per-device and per-shape overrides"),
  `always-on-display.md`, `styles-and-layouts.md`, `patterns.md`,
  `analog-hands.md`; `docs/limitations.md` §2.
- `ts/test/CLAUDE.md`, `ts/test/page-*.test.ts`, `studio*.test.ts`,
  `edit.test.ts`, `goldens.test.ts`, `overrides.test.ts`.
- The `yaml` package 2.9.1 Document API (`parseDocument`, `toString`),
  probed over the 24 example faces (§2.5).
- Samsung, *Watch Face Studio user guide: Create*; Google, *Introducing
  Watch Face Designer* (Android Developers Blog, August 2025).
