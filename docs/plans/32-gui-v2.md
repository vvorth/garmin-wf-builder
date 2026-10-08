# Plan 32 — GUIv2: coverage and navigation in `wfb studio`

**Status: open.** Built from `docs/research/33-gui-v2.md`'s decisions
(D1–D8, all decided by the user 2026-10-08, as recommended). Three items
researched there are explicitly **not** in this plan (§8): polygon
points, hand parts and `aod:` each need their own design pass before they
can be built.

**Scope.** Seven slices, independent of each other except where noted.
Nothing here changes the format: every slice is a new or reshaped widget
over keys the schema already has (ADR 0002 — nothing GUI-only). No slice
needs a schema change, a new patch op beyond what §3–§7 name, or a new
server endpoint.

---

## Slice 1 — Two widget bugs

**`step:`'s `oneOf` is never resolved.** `widget()`
(`ts/src/studio/inspect.ts:92-109`) calls `deref()`, which follows a
single `$ref` chain and gives up at a `oneOf` with no top-level `$ref` —
so a pattern's `step:` always falls to the inert "yaml" widget, whether
the author wrote an angle or a `{dx, dy}`. Fix: `widget()` tries each
`oneOf` branch in order, picks the one whose resolved `$defs` name is in
`WIDGET_BY_REF` **and** whose present value matches that branch's shape
(a plain scalar/`%`/`%r`/`px` string for `angle`, a mapping with `dx`/`dy`
for `patternStep`); with no value present (the key is absent), use the
first branch. This is the one piece of general machinery this plan adds
to `deref`/`widget`, because it is a real bug, not a one-off.

**`series:` is free text.** Give it the `enum` widget
(`ts/src/studio/inspect.ts`'s existing `enum` case, `"enum" in resolved"`)
seeded from `series.names()` — the same list `ts/app/layers.js:74` already
uses for the add-element dialog — rather than widening the schema itself
(the catalogue stays documented in prose, per research 33 §2, not a
closed schema enum: `inspect.ts`'s `field()` can inject a synthetic
`enum` for this one key without touching the schema).

**Acceptance:** every example face's `step:` and `series:` values render
with a real widget, not the "edit this in the YAML" fallback; the fast
suite's studio tests cover one pattern face and one graph face.

---

## Slice 2 — Face tab: second-level navigation

Replace `FacePanel`'s 8 stacked `<Section>` accordions
(`ts/app/panels.js:541-653`) with a two-level layout: a list of section
names (Targets, Colours, Colour settings, Schemes, Styles, Hand sets,
Slots, Fonts) and one section's content shown at a time, the shape a
settings app uses. Keep every section's own component unchanged
(`Schemes()`, `HandSets()`, `SlotCard`, etc. — this is a navigation
change around them, not a rewrite of what is inside). The browser
remembers which section was open, the same way it already remembers fold
state, so switching tabs and back does not reset it.

This is the slice every later face-wide feature (a layouts editor, AOD
defaults) lands inside without growing the tab's height further.

**Acceptance:** all 8 existing sections reachable, each editable exactly
as before; opening the Face tab shows the section last open; no section's
own markup or patch calls change.

---

## Slice 3 — Element-side cards for hand sets, schemes, pattern parts

Extend the pattern a `data`/gauge element with `slot:` already gets — a
card above its keys, reading and writing the same `config: slots:` path
the Face tab's `SlotCard` does (`docs/guide/studio.md`, "The Face tab" —
"Slots") — to three more element/Face-tab pairs:

- a `hands` element shows its set's card (hand preview, each hand's
  colour, "edit the set" → the YAML tab's hand-set lines), reusing
  `HandSets()`'s row component;
- any element reading a colour **role** (one bound to the face's current
  `theme:`) shows which scheme role it is and a jump to the Schemes table;
- a pattern element's own `panels.js` properties gain a compact summary
  of its parts (count, shapes) with the existing "edit in YAML" link
  `panels.js:486` already gives hand parts — not a new editor, the same
  dead-end-with-a-pointer shape slice 5 formalises for overrides.

Each card edits through the exact ops its Face-tab counterpart already
sends; no new patch surface.

**Acceptance:** selecting a `hands` element shows its set's card;
selecting an element using a scheme role shows which scheme/role; a
pattern element's properties name its part count without a trip to Face.

---

## Slice 4 — Command palette

Ctrl/Cmd+K opens a fuzzy-find over: every element (by id or type), every
colour and role, every font, every slot, every hand set, every style.
Selecting a result does exactly what clicking it in the Layers tree, the
Face tab's matching row, or the canvas selection already does — the
palette is a second way to reach existing selection/navigation state, not
a new one. Source the list from `vocabulary()`
(`ts/src/studio/inspect.ts`'s existing `vocabulary` export) plus the
current document's own names (`globalsOf`'s palette/schemes/fonts/slots/
hand_sets), so it needs no new server call. `?` continues to list
keyboard shortcuts; the palette gets its own one-line mention there.

**Acceptance:** every element, colour, font, slot, hand set and style
name is reachable by typing at least a substring of its name; selecting
one matches the existing single-click behaviour exactly (same selection
state, same panel opened).

---

## Slice 5 — `overrides:` visibility

Stop skipping `overrides` in the inspector (`inspect.ts:50`'s `SKIPPED`
set). When an element has an `overrides:` block, show one read-only row
per overridden key per selector (device id, `shape:`, `display:`),
captioned with the selector and a "edit in the YAML tab" link to its
lines (the same span lookup `panels.js:486` already uses for hand parts).
This does not extend the "all targets / this device / this shape"
*editing* chooser (`GEOMETRY`, `inspect.ts:37`) to new keys — it only
makes an existing override's existence and value visible. Building edit
controls for non-geometry override keys is future work, not this slice.

**Acceptance:** an element with a `color`/`font`/`visible:` override
shows it (selector + value), previously invisible; a geometry override
still only shows through the existing chooser (unchanged); no new patch
op.

---

## Slice 6 — `curve:` control

A compact widget for `curve:` (style — `angled`/`radial` — plus angle and,
for `radial`, a radius), matching `docs/guide/text.md`'s documented
shape. Wire it the same way `align` gets its 3×3 picker: a new
`WIDGET_BY_REF` entry (or key-based special case, matching how `slot`/
`set`/`font`/`icon`/`on_hold` are already special-cased) resolving to a
small object widget, written through the existing `object` path
(`inspect.ts`'s `NESTED`/`field()` children handling) rather than a new
patch mechanism.

**Acceptance:** a `text` element's `curve:` (both styles) is editable
without the YAML tab; an element with no `curve:` gets an "add curve" path
consistent with how other optional object keys are added today.

---

## Slice 7 — Layouts creation

A "+ Layout" control beside Styles' existing "+ Style" (`panels.js:614`,
`AddName`), writing a new `layouts: {<name>: {}}` entry — the same
structural-add shape `structure.ts`'s `CHOICES`-driven adds already use
for `graph`/`data`/`hands`. A newly added layout appears in the Layers
tree (which already lists "each layout's own two blocks", per
`docs/guide/studio.md`) with nothing in it yet, and in every Style row's
layout `<select>` (`panels.js:600-603`), which today only lists layouts
that already exist.

**Acceptance:** "+ Layout" adds an empty layout, selectable from every
Style row and visible, empty, in Layers; deleting a layout with no style
referencing it works through the existing structural delete path.

---

## 8. Not in this plan

Deferred to their own research, per `docs/research/33-gui-v2.md` §5 and
D8 — each is a point- or block-editing design problem, not a widget:

- **Polygon `points:` editing** (drag-add/remove a vertex).
- **Hand `parts:` editing** (a frame-relative-to-an-axis handle model,
  mirrored-pair symmetry, 1–16 rotatable parts) — flagged once already
  when hand sets shipped, still unbuilt.
- **A structured `aod:` editor** (an awake/AOD dual view of Properties,
  not a single new widget).

Nothing in slices 1–7 touches the geometry patcher, the drag model, or
the AOD builder; each stays exactly as documented in `docs/limitations.md`
§2 until its own plan.

---

## Sources

`docs/research/33-gui-v2.md` (every decision and citation this plan
builds from); `docs/adr/0002-authoring-interface.md`; `docs/guide/studio.md`,
`docs/guide/text.md` (`curve:`); `docs/limitations.md` §2 (override keys
built today); `ts/app/panels.js`, `ts/app/layers.js`, `ts/app/keys.js`;
`ts/src/studio/inspect.ts`; `ts/src/edit/structure.ts`.
