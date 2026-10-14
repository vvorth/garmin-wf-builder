# Plan 33 — A full-featured editor: `wfb studio` rebuilt over its engine

**Status: open, in progress.** The user took every decision D1–D11 of
`docs/research/34-full-editor.md` §10 as recommended on 2026-10-13 and
asked for the slices to be built in order, unattended, starting with 0a.
Each slice's status is noted at its heading as it ships.

**Scope.** Keep the engine (`ts/src/edit/`, `store.ts`, `router.ts`,
`worker.ts`, `gate.ts`, `bundle.ts`, the rasteriser). Replace the page
(`ts/app/`) and the studio layer that knows the format (`inspect.ts`, the
`EDITS` table and `editPath` in `document.ts`, `globalsOf`). Take the ten
format changes of research 34 §5 alongside the editor slice that needs
each. Add browser-driven tests.

**What done looks like.** Every key the schema admits is editable in a
control (the read-only fallback appears only for a key the schema lacks);
`overrides:`, `aod:` and layouts are edited through the editing context;
hand parts, pattern parts, needles and polygon points are dragged on the
canvas; conditions and templates are built, not typed; Playwright drives
every documented gesture against the real worker; the guide's "What it does
not do" shrinks to sideloading and sharing between browsers.

---

## Slice 0a — Stop the bleeding (no decision needed)

**Shipped 2026-10-13** (`git log --grep "slice 0a"`; the three commits after
the decisions). Every defect below has its regression test; the gate now
runs the whole pipeline (`Document.admit`), so a resolve-time error is
refused like a load-time one and a text that has one still reads.

The four defects of research 34 §2.4 that lose work or corrupt a face are
fixed in the editor as it stands, before and independently of the rewrite,
each with the regression test that was missing:

1. **The gate covers the whole pipeline** (defects 1 and 12): `Gate.check`
   runs the resolve as well as the load (or `Document.analysis()` catches a
   resolve-time error into the bag as a diagnostic on the author's line),
   so a `pt` length with no font in scope, or a target the face cannot
   draw on, is refused with its reason and never committed. A face already
   bricked opens again: a read that fails degrades to "the face does not
   load" with the error shown, not a thrown request. `ts/test/gate.test.ts`
   drives both red first.
2. **A unit change converts or asks** (defect 2): the unit select converts
   the number through the device's pixel equivalent where the units are
   commensurable (`px`, `%`, `%r` on the viewed device; `deg`/`turn`) and
   otherwise clears the number until one is typed; `pt` is offered only on
   a key whose element has a font in scope.
3. **Nothing in flight is lost on reload** (defect 11): the outbox flushes
   on `beforeunload`/`pagehide` through the worker, the YAML pane's
   debounce flushes with it, and the page shows "saving…" until the
   worker has committed.
4. **A thin element moves** (defect 3): a press inside an element smaller
   than the handle zone is a move; handles win only outside the ink.

With them, the small ones that are one-line fixes: the Face-tab section
follows Ctrl+K while the tab is open (defect 4), a font upload is checked
for an sfnt header (defect 6), an emptied override is pruned (defect 8),
"+ add…" of a live type with a `static:` selection goes to `elements:`
(defect 10).

**Gate:** each defect's reproduction, as a test, is red before and green
after; the fast suite green.

## Slice 0 — The engine's three additions (D2)

**Shipped 2026-10-13** (`git log --grep "slice 0"` and the four commits
after 0a: `display:` selectors, the batched edit and router lanes, list
items, `protocol.ts`). Every existing edit op is a batch step; the page
still reads the contract through JSDoc until slice 1.

1. **List-item primitives** in `ts/src/edit/patch.ts`: `insertItem(path,
   index, data)`, `removeItem(path, index)`, `moveItem(path, from, to)` for
   block and flow sequences, byte-exact like the mapping primitives (an
   emptied block sequence takes its key, as an emptied mapping does), run
   over the example corpus in `ts/test/edit.test.ts` for every list the
   examples hold (points, parts, choices, targets, bands, skip).
2. **A batched edit** (`op: "batch"`, a list of primitive ops: `set`,
   `remove`, `rename`, `rename_reference`, `insert_item`, `remove_item`,
   `move_item`, `move_element`, …) applied in order to one text, gated once,
   committed as one history entry with the batch's own label. `chain`
   becomes the n-ary composition it already is for two.
3. **A typed contract**: `ts/src/studio/protocol.ts` exporting the summary,
   frame, inspect, globals, tree and event payload interfaces; `document.ts`
   and the page build and consume those types. `Record<string, unknown>`
   leaves the worker's public surface.

Also: `display:` selectors writable (`geometry.ts:62-72`); two lanes in the
router so an edit never waits on a thumbnail (`router.ts:156-164`).

**Gate:** the fast suite green; every existing edit op re-expressed as a
batch gives byte-identical text on the corpus (so the named ops can be
retired one by one later).

## Slice 1 — The page in TypeScript, at parity (D1)

**Shipped 2026-10-14** (`git log --grep "TypeScript"` from `89a6db7` to
`99a8031`): the page is bundled from `ts/app/main.ts`, every module is
strict TypeScript with Preact and htm from npm, and `app/store.ts` holds
the editor's state behind `useStore`. The old `ts/app/*.js` is gone.

`ts/app/` becomes TypeScript bundled by esbuild like the worker
(`npm run bundle`), `strict`, importing `protocol.ts`. One store holds the
editor's state (document summary, selection, editing context, pending
edits, view); the outbox's ordering and the YAML pane's save machine are
kept as behaviours but live in that store. Preact stays as the view
library; CodeMirror stays for the YAML tab.

Parity means every row of `docs/guide/studio.md` works as before: home and
library, Layers, canvas gestures, Properties (still the old widget set in
this slice), Face sections, YAML tab, Ctrl+K, history, build, download.
`ts/test/page-*.test.ts` are ported to the new modules and must pass
before the old page is deleted.

**Gate:** the ported page tests and the Playwright smoke test of slice 6
(opened early, see below) pass; the old `ts/app/*.js` is deleted in the
same commit, never left as a second page.

## Slice 2 — Properties v2: the generic form and the editing context (D3, D5, D6)

**Shipped 2026-10-14** (`git log --grep "format:" --grep "Properties v2" --grep "Face tab"`
from `37ddac9` to the page commits `ae6f0c2`/`6a611bf` as cherry-picked): the five
format changes (F3 `absent:` 37ddac9, F4 `outline:` 995c86c, F5 `icon:`
b6568a3, F6 `range:`/`step_angle:` cb2a231, F7 whole-key `overrides:`
b492d13), the icon picker writing `{codepoint}` (e93c344), the worker half
of Properties v2 (55e027b: the field tree with `kind`, `children`, `items`,
`branches`/`chosen`; `effective` with provenance per editing context; the
`aod` edit scope; `rename_layout`, `delete_layout`, `move_key`,
`set_default_style`; `face`, `defaults` and `layout_entries` in the
globals), the page half (`ts/app/form.ts`: the generic form over the tree;
the store's `context.target` and the **Edit for** control; the AOD frame
writing into `aod:` with provenance badges; the scope buttons and the
read-only summaries gone) and the Face tab's Face, Defaults and Layouts
sections, the Styles matrix and reorder controls (`ts/app/face-sections.ts`).
Not built: a layout `label:` (the schema has none; F9). Two notes for the
record:

- F3 and F5 mechanically rewrote `examples/dashboard/face.yaml`, the
  user's playground (`absent:` and `icon:` spellings only; nothing else
  in it changed). The generated Monkey C comments in
  `ts/test/goldens/monkeyc/` still quote the old spellings until the
  goldens are regenerated.
- The goldens were frozen with five devices this container lacks
  (`venusq2`, `instinct2`, `instinct2x`, `instinct3solar45mm`,
  `instincte45mm`), so `WFB_UPDATE_GOLDENS=1` has not been run: the two
  golden tests and one `display:` override test stay red with diffs read
  and accounted for per format change (baseline 156 corpus designs from
  the missing devices; F3 17, F6 11, F4 157, F5 about 177, F7 14). They
  are regenerated once the user uploads those device folders.

- **The generic form**: a recursive renderer over the schema branch —
  object → fieldset, list → list editor on the slice-0 primitives, `oneOf`/
  `anyOf` → segmented control over branches with the value's shape
  pre-selected, `enum` → select, known `$defs` → dedicated control, unknown
  key → raw value. The "edit this in the YAML" caption is deleted.
- **The editing context**: the bar above the canvas (watch · shape · frame
  · style · picks · time) also decides where an edit lands; Properties shows
  effective values with a provenance badge (own · override `<selector>` ·
  aod · inherited from `<group>` · defaults) and **Edit for all watches** /
  **this frame only** toggles. `aod:` blocks, `overrides:` of every allowed
  key and `defaults.aod` become editable through it; the scope buttons and
  the read-only override list go.
- **Format, alongside** (each its own commit, schema + compiler + guide +
  examples + goldens in one): F3 tagged `absent:`, F4 object `outline:`,
  F5 `icon:` forms, F6 `range:`/`step_angle:`, F7 `overrides:` whole-key
  replacement with one allowlist and writable `display:`.
- New Face sections: **Face** (name, version), **Defaults**, **Layouts**
  (rename, delete, label), the **Styles matrix** with reorder; palette,
  targets, slot choices and style entries get reorder controls.

**Gate:** the coverage script of research 34 §2.1 reports zero read-only
and zero invisible slots for every key the schema has; a Playwright test
edits an `aod:` colour and a `display:amoled` override from the context and
reads the YAML diff.

## Slice 3 — Parts and points (D4)

- **Format F1, F2**: id-keyed `parts:` on hands, patterns and needles (the
  list form read as sugar with generated ids), `mirror: x` on a polygon
  part. Schema, compiler, guide, examples and goldens in one commit each.
- **Enter the set / the pattern**: the canvas switches to the local frame
  (axis, 12 o'clock, `%r` ring), Layers lists the parts, Properties edits a
  part as an element; other hands or copies are ghosted; the hand set's
  thumbnail route (`document.ts:676-696`) grows into the frame renderer.
  Pattern copies ghost live as count, step and skip change.
- **Polygon vertices**: a vertex list in Properties and vertex handles on the
  canvas (drag in the author's unit through `geometry.ts`'s landing search,
  add on a segment, delete). The refusal at `geometry.ts:338` goes.

**Gate:** a Playwright test drags a hand's blade vertex on the showcase's
`vintage` set and the pattern tick on its `analog` layout, and the frame
and YAML agree; `ts/test/studio-canvas.test.ts`'s "every live handle
predicts the edit" covers the new handles.

## Slice 4 — Data editors (D7, D8)

- **Templates**: a chip editor over `parseTemplate` for `text:` and
  pattern text parts — literal chips, placeholder chips with a source
  picker over the catalogue, a format-spec picker per source type, units;
  `absent:` beneath it as the tagged control of slice 2.
- **Conditions**: source · operator · value rows with `else` for `visible:`,
  `color:` (follows data…), `value:`, `max:`, `min:`, `aod.visible`; the raw
  expression as the power-user form, round-tripped through `expr.ts`.
- **Format F10**: rule lists as the conditional spelling the editor writes
  (the reserved vocabulary becomes built: schema, compiler folding to the
  same Monkey C ternary, guide). If D8 defers it, the editor writes
  expressions and the rows are a view over them.
- **Format F8, F9**: a text's own `font: {source, size}` (desugared and
  deduplicated into `resources.fonts`), giving text a size handle;
  `label:` on layouts and `base:` on schemes for the Styles matrix.

**Gate:** the showcase's and enduro's every template and expression opens
in the editors without a raw fallback; a condition built in rows produces
byte-identical Monkey C to the ternary it replaces (goldens).

## Slice 5 — Layers, palette, the rest of the surface

Search in Layers; lock and hide-in-editor as browser state beside the face
(D9); `z:` badges; the diagnostic row's **accept here…** writing `lint:
{allow, reason}`; fonts with every option (`glyphs`, `antialias`,
`monospace`, `align`, `face`); `paletteEntry.label` and `scheme.label`;
colour-axis inline choices. The named compound ops in `schemes.ts`,
`hands.ts`, `colors.ts`, `slots.ts` that carry format knowledge (reference
renames, dangling refusals) stay; the ones that are mere composition are
retired for batches.

**Gate:** the guide's "What it does not do" lists sideloading and sharing
between browsers only; `docs/limitations.md` §2's `wfb studio` row shrinks
to match, in the same commit.

## Slice 6 — Browser tests and CI (D10)

Opened at slice 1 and grown with every slice: Playwright against the real
server and worker in headless Chromium — open each example as yaml and
zip, select each element type, drag each handle, use each Face section,
type in the YAML tab (valid, invalid, compiler error, conflict), undo and
redo across tabs, Ctrl+K, history, download, build one device. The
scenarios are the live session of research 34 §2.4, as regression tests.
The device files come from the user's archive stored as a CI secret; a
probe tries the synthetic fixture device of research 34 §8 and, if it
loads, the fast suite and the browser tests run from a clean clone on it.

**Gate:** CI runs the fast suite, the type check and the browser tests on
every push; the "checked by hand" sentence leaves `ts/test/CLAUDE.md` and
`docs/guide/studio.md`.

---

## Order and dependencies

```
0a stop the bleeding (independent, first)
0 engine ──► 1 page at parity ──► 2 Properties v2 + context ──► 3 parts/points ──► 4 data editors ──► 5 the rest
                 │                                                                                      
                 └──► 6 browser tests (opened at 1, grown through 5, CI at the end)
```

Format changes ride the slice that needs them (F3–F7 in 2, F1–F2 in 3,
F8–F10 in 4), each in its own commit with schema, compiler, guide,
examples and goldens together (root `CLAUDE.md` §7, ADR 0009: a changed
key becomes a schema error naming its replacement; a kept shorthand is a
desugaring pass).

## Decisions recorded

**2026-10-13:** D1 B (rewrite the page and inspector over the engine); D2
engine additions now; D3 the editing context decides where an edit goes;
D4 id-keyed parts and `mirror:`; D5 all four shape clean-ups; D6
whole-key `overrides:` with writable `display:`; D7 F8 and F9; D8 rule
lists built with the condition editor; D9 editor-only state in browser
storage; D10 Playwright with the user's device files, and a probe of the
fixture device; D11 engine first, format changes alongside the editor
slice that needs each. Work proceeds slice by slice without further
sign-off; subagents build, and every subagent's result is re-verified
before it is integrated.

## Not in this plan

- Sideloading from the editor and sharing faces between browsers
  (`docs/limitations.md` §2): unchanged.
- Reusable components (`use:`/`with:`), `effects:`, the data widget: still
  reserved vocabulary. Slice 2's generic form and slice 3's id-keyed parts
  are designed so each lands as a form over its schema when built.
- Anything in the compiler, the draw program or the rasteriser.
