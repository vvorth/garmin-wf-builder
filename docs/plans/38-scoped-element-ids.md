# 38 — Element names unique among siblings, ids qualified by path

**Status: planned 2026-11-05, D1–D8 decided (the user chose "always
path-qualify" over "qualify only on collision").** Delete this file once
all three slices have shipped (`docs/CLAUDE.md`).

## 0. Why

Today every element key in a face must be unique across the whole
document: a group's child may not be called like a top-level element or
like another group's child (`duplicate-id` in `ts/src/ir/builder/tree.ts`).
Nothing in the format needs that. No key of the YAML names an element by
its id (`docs/guide/studio.md`, "Properties": a rename changes one YAML
key), and YAML already refuses a duplicate key inside one mapping. The rule
exists because codegen derives one flat set of Monkey C symbols per element
(`drawLabel`, `LABEL_*`, `ringLabel`, `drawStaticLabel`, `iconForLabel`,
`holdLabel`; `ts/src/ir/naming.ts`) inside one generated view class, and
Monkey C has no notion of the YAML tree. The editor then inherited the rule
as the identity of an element in its protocol, and works around it when it
duplicates a group (every nested key gets a suffix).

The user asked for the natural rule instead: a name need only be unique
among its siblings, as in any tree.

## 1. Decisions (2026-11-05)

- **D1: the element's *id* is its YAML key qualified by the ids of the
  groups it sits in, joined with `.`.** `elements: top: children: label:`
  is the element `top.label`; a top-level element's id is its key, so a
  flat face changes nothing. The key itself is the element's *name*
  (`elementName(id)`); the whole derivation lives in
  `ts/src/element_ids.ts` and nowhere else. `.` was chosen over `/` because
  the editor already uses `/` for a part's tree-path id (`pathOfId` in
  `ts/src/studio/parts.ts`, `isPartId` in `ts/app/store.ts`), and over
  `_` because `top_label` must stay a legal top-level name.
- **D2: the synthetic containers desugaring mints count as groups.** The
  top-level `static:` block's elements are `static.<name>`; a layout's are
  `layout_<layout>.<name>` and `layout_<layout>_static.<name>`. Without
  this, `static: {ticks: …}` and `elements: {ticks: …}` would clash, which
  is exactly the restriction being lifted. The reserved-id rules shrink to
  the top level: a top-level element may not be called `static` while a
  `static:` block exists, nor `layout_<name>`/`layout_<name>_static` while
  that layout exists (`desugar.ts` already reports both; `collectIds` no
  longer needs to recurse).
- **D3: generated symbols derive from the qualified id, `.` treated as a
  word break.** `top.label` gives `drawTopLabel`, `TOP_LABEL_*`,
  `ringTopLabel`, `TOP_LABEL_VARIANT`; `static.ticks` gives
  `drawStaticTicks`. Symbol length is free on the watch (`monkeyc` numbers
  symbols; constants are inlined). This is option 1, "always qualify":
  the goldens of every face with a nested element, a `static:` block or a
  layout change once, and the change is explained in the commit as this
  renaming and nothing else.
- **D4: the symbol-collision check stays, and is the only global rule
  left.** `top.label` and `top_label`, or `top.label` and `topLabel`, still
  fold to one symbol; `checkSymbolCollision` keeps reporting that as
  `duplicate-id`, its note rewritten (ids are now unique by construction;
  the symbol is what must be distinct). The literal `seen_ids` check stays
  as an internal invariant and is expected never to fire.
- **D5: the editor's identity is the qualified id, exactly as the
  compiler's.** Every `id` the protocol carries for an element (tree,
  frame items, layers, selection, `hidden`, `enter`, drags) is the
  qualified id; `TreeNode` gains `name`, the key, for display. The span
  index derives the same id from a YAML path (`elementIdOfPath`), so
  `SpanIndex.elementIds()` and the compiler's `face.walk()` ids agree, and
  a test holds them equal over the example corpus.
- **D6: edits scope uniqueness to one mapping.** Add, group, paste and
  rename refuse a name only when a *sibling* has it; `freshId` counts
  siblings in the destination block; duplicate copies a group without
  renaming anything inside it (the copy's own key gets the suffix, as
  today); moving an element into another block refuses when that block
  already has a child of that name (a clash that could not happen before).
  Renaming a group renames every descendant's id: the page keeps the
  selection by following the rename, and drops extras it can no longer
  find.
- **D7: diagnostics name an element by its qualified id** (`'top.label'
  may draw over …`): more informative than the bare key, and unique.
- **D8: an inline `font:` is still hoisted as `<name>_font`** from the
  element's *name*, deduplicated with `_2`, `_3` as today, since a
  `resources: fonts:` key must be an identifier.

## 2. Slices

Each slice is one commit on its own worktree branch, merged into
`claude/eloquent-rubin-suzh1w` after review; the whole lands on `main`
once the fast suite, the slow suite and the browser suite are green.

### Slice 1 — the compiler

`ts/src/desugar.ts` injects the qualified id (`childElementId(parentId,
key)`) while it rewrites each mapping, the synthetic groups' children
included, and hoists fonts under the name (D8); its `STATIC_GROUP_ID` and
`layoutIds` move to `element_ids.ts` (re-exported or imported where used).
`ts/src/ir/naming.ts` treats `.` as a separator in `elementSuffix`;
`elementConstPrefix` and `pascal` already do. `Element` gains a `name`
getter. `tree.ts`'s collision note is rewritten (D4). The lints and
diagnostics keep quoting `element.id` (D7). Tests, in `ts/test/`: the same
name in two groups, at the top level and in a group, in `static:` and in
`elements:`, and in two layouts, each building to the expected symbols
and warning-free under `generated`; `elementIdOfPath` against
`childElementId` for every element of the example corpus; the symbol
collision across scopes still an error (one error, not N); the hoisted
font name. Goldens regenerated and the diff read: only renamed symbols.

### Slice 2 — the editor

`ts/src/edit/spans.ts`: an `Entry` of an element knows its qualified id
(`elementIdOfPath(entry.path)`), `elementIds()` returns those, and a new
`siblingNames(block)` serves the uniqueness checks. `structure.ts` (add,
group, paste, move, duplicate), `patch.ts` (rename, duplicate) and
`document.ts` follow D6; `document.ts`'s "new id" discovery and
`hiddenIds`/`authored` filters work on qualified ids. `protocol.ts`:
`TreeNode.name`. `ts/app/`: the tree, layers, inspector title and the
rename control show `name` and key on `id`; selection follows a rename of
an ancestor. Tests: `edit.test.ts` (each new refusal driven red first),
`studio*.test.ts`, `protocol.test.ts`, `page-*.test.ts`; the corpus
agreement test of slice 1 is shared.

### Slice 3 — the written record

`docs/guide/elements.md` (the three errors), `docs/guide/studio.md`
(rename), `docs/development.md` ("Symbol names derive from element ids"),
`docs/lore/codegen.md` (a bullet on qualified ids and symbol derivation,
beside the part-id bullet), the schema's description of an element
mapping's keys where it speaks of uniqueness, `docs/guide/lints.md` if it
lists `duplicate-id`, and the `watchface-from-image` skill if it states
the old rule. Then this file is deleted and `docs/plans/README.md` indexes
it.
