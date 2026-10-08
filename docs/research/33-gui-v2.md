# 33 — GUIv2: closing `wfb studio`'s coverage gaps without adding clutter

**Question (user, 2026-10-08).** Read the project scope and research a
"GUIv2" pass over `wfb studio`: ergonomic, covering every feature, not
looking like clutter, easy to use.

**Status (2026-10-08): research complete, decisions below adopted by the
user the same day, and all seven buildable slices built the same day**
(plan 32, `git show 19ae010:docs/plans/32-gui-v2.md`); three items are
deliberately deferred to their own research (§5).

**Short answer.**

| # | Finding | Fix |
|---|---|---|
| 1 | The inspector is schema-generated (ADR 0002: nothing GUI-only), but its `widget()`/`deref()` only follows a single `$ref` and a short allow-list of keys. Everything else — an array, an object with no matching ref, a `oneOf` — renders as an inert, **read-only** `<code>` block, not even an editable text field | close the specific gaps found (§2) |
| 2 | A pattern's `step:` is `oneOf [angle, patternStep]`. `deref()` never resolves a `oneOf`, so **well-formed YAML silently gets the inert fallback regardless of which shape was written** — this is a bug, not a coverage gap | fix `widget()`'s `oneOf` handling (slice 1) |
| 3 | A graph's `series:` is a bare schema `string` (no `enum`, by design — the catalogue is prose, not a closed list), so it gets a free-text field, even though the same catalogue (`vocab.series`) already drives a picker in the "add element" dialog | reuse that picker in the inspector (slice 1) |
| 4 | `overrides:` is in `inspect.ts`'s `SKIPPED` set — an element with a non-geometry override (colour, font, `visible:`) shows **no sign it exists** | surface it read-only, same precedent as hand parts (slice 5) |
| 5 | The Face tab is 8 stacked accordion sections in one 654-line file with no second-level nav and no search; every future face-wide feature (AOD defaults, layouts, patterns) is section #9, #10, #11 in the same scroll | second-level nav (slice 2) + a command palette (slice 4) |
| 6 | Polygon points, hand parts and `aod:` blocks are real, open-ended design problems (a point/handle model each), not a quick widget | defer, each to its own research (§5), as the project already did once for hand parts |

Audited: `ts/app/app.js`, `ts/app/panels.js`, `ts/app/layers.js`,
`ts/app/canvas.js`, `ts/app/dialogs.js`, `ts/app/keys.js`,
`ts/src/studio/inspect.ts`, `ts/src/studio/server.ts`,
`ts/src/edit/structure.ts`, `ts/src/edit/geometry.ts`,
`schema/wfb-face-2.schema.json`. No code changed.

---

## 1. What the editor is today, and the constraint it must keep

`wfb studio` is a lossless, bidirectional view over the YAML (ADR 0002):
**nothing may be expressible only through the GUI**, so a "GUIv2" pass is
scoped to closing coverage against the format and improving the shape of
the existing surface — never to inventing GUI-only state.

The inspector (an element's Properties panel) follows directly from that
constraint: it is **generated from the schema branch for the element's
`type:`**, not hand-built per property (research 26 §4.6). `widget()`
(`ts/src/studio/inspect.ts:92-109`) picks a renderer by:

1. a short allow-list of schema `$defs` names (`WIDGET_BY_REF`:
   `length`, `handLength`, `patternLength`, `angle`, `align`,
   `colorExpression`/`colorRef`/`color`/`hexColor`/`swatchColor`,
   `visible`/`expression`), resolved through `deref()`
   (`inspect.ts:62-68`), which follows **one** `$ref` chain, never a
   `oneOf`;
2. a handful of special-cased keys (`text` on `type: text`, `slot`,
   `set` on `hands`, `font`, `icon`, `on_hold`);
3. else the JSON `type`: `boolean`→bool, `integer`/`number`→number,
   `string`→text, `enum`→enum;
4. **else `["yaml", resolved]`** — and `panels.js:181-183` renders that
   case as a read-only `<code>` block captioned "edit this in the YAML",
   not a text box. There is no partial credit: a key that misses every
   rule above gets no editing surface at all, only a pointer to the text
   tab.

That fallback is the right default for truly open-ended values (a list,
a free-form `aod:` block) — it is also, by construction, where every
coverage gap in §2 lives, including one outright bug.

The rest of the editor is a fixed three-pane layout (`ts/app/app.js`,
confirmed against `docs/guide/studio.md`): **Layers/Face** tabs left
(`app.js:688-690`), canvas-or-YAML centre with a per-target frame strip
below it (`app.js:701-704,742`), **Properties/Diagnostics/History** right
(`app.js:316-355`). The Face tab (`FacePanel`, `panels.js:541-653`, ~113 of
the file's 654 lines) is 8 collapsible sections in one scroll: Targets,
Colours, Colour settings, Schemes, Styles, Hand sets, Slots, Fonts.

## 2. Coverage: where the fallback bites

| Gap | Schema shape | Why it falls through | Citation |
|---|---|---|---|
| Pattern `step:` (bug) | `oneOf [angle, patternStep]` | `deref()` never follows `oneOf`; **both** valid shapes get the inert fallback | schema `:2689-2699`; `inspect.ts:62-68,92-109` |
| Pattern `skip:`/`skip_every:` | array / plain integer | `skip` is an array (no rule matches arrays); `skip_every` is a bare integer and *does* get the generic number widget today, so only `skip` is a true gap | schema `:2704-2717` |
| Graph `series:` | plain `string`, no `enum` (the catalogue is prose by design, so a schema enum was never intended to drive this) | gets the generic free-text widget; the same catalogue already backs a picker, but only in the "add element" dialog (`CHOICES` in `ts/src/edit/structure.ts:31`, consumed by `ts/app/layers.js:14,74`), never when editing an existing graph | schema `:2380-2383` |
| `overrides:` beyond geometry | object, per-device/`shape:`/`display:` keyed | **actively hidden**: `overrides` is in `SKIPPED` (`inspect.ts:50`), so it is never listed as a field at all. Only `at`/`size`/`radius`/`align` get the "all targets / this device / this shape" scope chooser (`GEOMETRY`, `inspect.ts:37`, used at `panels.js:188,237-241`); a colour, font, or `visible:` override is invisible in the inspector even though it is legal YAML (`docs/limitations.md` §2 lists which override keys are built: geometry, `color`/`track_color`, `visible:`) | `inspect.ts:37,50,157-164` |
| `curve:` | object (vector-font text curving) | no ref/key rule matches `curve`; not referenced anywhere in `inspect.ts` or `panels.js` | — |
| `aod:` blocks | `$ref: faceAod`/`aodGroup`, one per element kind | ref names not in `WIDGET_BY_REF`; object type never special-cased | schema `:868-873,1220,1373` (+ one `aod` ref per element kind, `:1471`–`:2749`) |
| Polygon `points:` | array of points | no array rule; **also explicitly refused for drag-editing**, independent of the inspector | `ts/src/edit/geometry.ts:338` ("is a polygon: move its points: in the text") |
| Hand set `parts:` | array of `handPart` | no array rule; `panels.js` already surfaces this as a deliberate link to the YAML tab rather than pretending to edit it (":486", "a hand's parts are edited in the YAML") | `panels.js:486` |
| Styles → **new** layout | — | the Styles section's layout `<select>` only lists `g.layouts` names that already exist (`panels.js:600-603`); there is no "+ layout" control anywhere, and `structure.ts`'s `CHOICES` has no layout-creation op | `panels.js:600-603,617`; `ts/src/edit/structure.ts:31` |

Two of these are categorically different from the rest:

- **The `step:` fallback is a correctness bug.** An author who writes a
  perfectly valid `step: 30deg` or `step: {dx: 5%r}` gets no widget either
  way, purely because `deref()` stops at the first `$ref` and a `oneOf`
  has none at the top level. This should be fixed regardless of any other
  GUIv2 decision.
- **The `overrides:` gap is a visibility bug, not a missing editor.** The
  cheap, immediate fix is the one the project already took for hand
  parts: show the override read-only, named, with a link to its lines in
  the YAML tab. Building an editor for arbitrary override keys is a
  separate, larger piece of work.

Everything else is an honest coverage gap against a genuinely open-ended
value, and the right scope differs by gap (§4).

## 3. Ergonomics: why the Face tab will not survive more features as it is built today

`panels.js`'s `FacePanel` stacks 8 `<Section>` accordions (Targets through
Fonts) in one scroll, each independently foldable but all sharing one
list. That is a flat, linearly-growing list: every face-wide concept this
project adds next — a layouts editor, AOD defaults, a patterns library —
is section 9, 10, 11 in the same place, each competing for the same
scroll real estate and the same set of fold/unfold clicks to get past.

There is **no second-level navigation and no search anywhere** in the
front end. `ts/app/keys.js:53-76`'s `SHORTCUTS` table is a static
reference list shown by `?` (`ShortcutHelp`, `app.js:303-313`), not a
command surface: there is no way to jump directly to "the `accent` colour"
or "the `digital_dusk` style" or "the `heart_rate` graph" by typing its
name — the only route is open the right tab, find the right accordion,
scroll.

The project has already found, and shipped, the one pattern that scales
well here: a slot is edited from **both** the Face tab's list and a card
on the element drawing it (`docs/guide/studio.md`, "The Face tab" —
"Slots"), so an author who is looking at one data element never has to
leave Properties to reach its slot. That pattern was built once, for
slots, and nowhere else — hand sets, schemes and pattern parts all still
require a trip to the Face tab even when an element using them is
selected.

## 4. Options, by concern

**a. The two bugs (`step:` oneOf, `series:` free text).** No real option:
fix `widget()`'s `oneOf` handling (resolve by picking the branch whose
shape matches the value present, falling back to the first when the key
is absent) and give `series:` the `enum` widget seeded from
`series.names()` (already computed for the add-element picker). Low risk,
no format change.

**b. The Face tab's growth problem.**
- **A. Keep stacking accordions** (status quo). Costs nothing now, pays
  compounding interest later: every new face-wide feature adds scroll.
- **B. Second-level navigation** — a list of section names, one section
  shown at a time (the shape a settings app uses), so the tab's own
  height stops growing with feature count.
- **C. A single searchable flat list** merging every section's rows.
  Scales better than A but loses the section groupings that make "where
  do I edit colours" discoverable without searching.

Recommended: **B**, because it keeps today's section identities (nothing
to relearn) and bounds the tab's height regardless of how many sections
the format eventually needs.

**c. Reaching a face-wide thing from the element using it.** Extend the
slot card's "edit from both places" pattern to hand sets, schemes and
pattern parts, or leave it slot-only.

Recommended: **extend it.** It is the same component, the same patch
ops, applied to three more things the Face tab already edits; no new
mechanism.

**d. Finding anything without a trip through tabs.** Add a command
palette (Ctrl/Cmd+K: jump to any element, colour, font, slot, style,
hand set by name/type) or leave navigation to the fixed tree and tabs.

Recommended: **add it.** It is the lever that lets coverage keep growing
without the UI looking busier — an author stops needing to *see*
everything to *reach* it, which is the real difference between "covers
every feature" and "looks like clutter."

**e. `overrides:` visibility.** Show every override key read-only with a
jump-to-YAML link (the hand-parts precedent) now, or wait for a general
override editor.

Recommended: **show now.** It costs one more `field()`-shaped read path in
`inspect.ts` (stop skipping `overrides`, render its keys the way hand
parts already render as a dead-end-with-a-link) and closes the worst part
of the gap — an override an author cannot even see exists — without
committing to the editor design for every override key up front.

**f. `curve:`.** A bounded control (style enum, angle, radius — the same
three fields `docs/guide/text.md`'s `curve:` section documents) closes
most real use without a geometry model. Build it now; it is schema-sized
work, not a new interaction.

**g. Layouts creation.** Add a "+ Layout" control beside Styles' "+
Style" (a structural op: an empty `layouts: {<name>: {}}` entry, the same
shape `structure.ts`'s existing add ops take). Small, no new mechanism.

## 5. Deferred: not a widget, a design problem

Three gaps are real, open-ended design work, each needing its own point-
or block-editing model, and should not block the rest of this plan:

- **Polygon `points:`.** Needs its own drag model: add/remove a vertex,
  drag one in `px`/`%r`, keep it inside the geometry patcher's existing
  per-element-key assumptions or extend them to per-point keys.
- **Hand `parts:`.** The project already flagged this once (hand sets
  shipped as a list/preset/rename/delete section with "edit in YAML" for
  parts, explicitly deferring a visual part editor to its own research,
  because it needs a frame-relative-to-an-axis handle model with
  mirrored-pair symmetry). Nothing has changed that assessment.
- **`aod:` blocks.** A structured editor here is not one widget but a
  second, parallel view of nearly every property an element has (every
  allow-listed override key, per `docs/limitations.md` §2), which wants
  its own information-architecture answer (an awake/AOD toggle on
  Properties itself, most likely) rather than being bolted onto the
  existing single-state inspector.

Each is real work on the scale of the hand-parts editor the project
already chose to defer once; none should be designed by extension of a
simple-widget plan.

## 6. Decisions for the user

| # | Decision | Options | Recommended |
|---|---|---|---|
| D1 | `step:`/`series:` bugs | fix now · leave | **decided 2026-10-08: fix now** (slice 1) |
| D2 | Face tab's growth | A keep stacking · **B second-level nav** · C flat searchable list | **decided 2026-10-08: B** (slice 2) |
| D3 | Element-side cards | slot-only (status quo) · **extend to hand sets, schemes, pattern parts** | **decided 2026-10-08: extend** (slice 3) |
| D4 | Command palette | none · **add one** | **decided 2026-10-08: add** (slice 4) |
| D5 | `overrides:` visibility | leave hidden · **show read-only + jump-to-YAML now** | **decided 2026-10-08: show now** (slice 5) |
| D6 | `curve:` control | build now · defer | **decided 2026-10-08: build now** (slice 6) |
| D7 | Layouts creation | add "+ Layout" · leave YAML-only | **decided 2026-10-08: add** (slice 7) |
| D8 | Points/parts/AOD editors | build now · **defer, each to its own research** | **decided 2026-10-08: defer** (§5) |

---

## Sources

- ADR 0002 (authoring interface: YAML canonical, GUI as a lossless
  editor); research 26 §4.6 (the schema-generated inspector).
- `ts/app/app.js` (top-level layout, tabs), `ts/app/panels.js`
  (`FacePanel`, `Widget`, `Field`, the Styles section), `ts/app/layers.js`
  (the add-element picker's series/slot/hand-set choices),
  `ts/app/keys.js` (`SHORTCUTS`).
- `ts/src/studio/inspect.ts` (`widget`, `deref`, `field`, `GEOMETRY`,
  `SKIPPED`), `ts/src/studio/server.ts` (the `Host` allowlist — the only
  server-side access control; document storage is per-browser IndexedDB,
  per the file's own header, so the cross-browser leak research 30 found
  in the old Python server does not apply to this architecture).
- `ts/src/edit/structure.ts` (`CHOICES`, the add-element ops),
  `ts/src/edit/geometry.ts:338` (polygon points refused for drag-editing).
- `schema/wfb-face-2.schema.json` (`patternStep` `:504`, pattern `step`/
  `skip`/`skip_every` `:2689-2717`, graph `series` `:2380-2383`, `faceAod`/
  `aodGroup` `:868-873,1220,1373`).
- `docs/guide/studio.md` ("The editor", "The Face tab" — the slot card
  precedent), `docs/guide/text.md` (`curve:`), `docs/limitations.md` §2
  (which override keys are built).
