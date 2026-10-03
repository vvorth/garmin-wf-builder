# 29 — Live handles for centred boxes and gauge arcs

**Status: built (2026-10-03): E, plain arc gauges, and D for centred
boxes: they keep the outline for now. C1–C4 do not arise. Slice 1 is
dropped. Slices 0 (its gauge checks), 2 and 3 are one commit: the corpus
test checks 107 live handles of 304 (from 63), 204 edits, each drawn by
the browser exactly as the server lands it; ignoring the fill fraction
fails it. Slice 3's jsdom check was not run: there is no jsdom or browser
in the sandbox, and the canvas applies a declared handle generically.** Delete
this file once every slice has shipped (`docs/CLAUDE.md`).

Records this builds on:
- `docs/research/29-browser-renderer.md`: the browser renderer, and the
  correction under its table C;
- plan 28 (`git show 2ab22c4:docs/plans/28-browser-renderer.md`), slice 3:
  live handles, and why only 63 of the corpus's 304 are live.

In short:

* Today a handle is live, drawn as it will land while it is dragged, only
  where its kind declares a linear rule that is exact
  (`ElementKind.live_handle`). Every other handle draws an outline until
  the release.
* **Centred boxes: how is open (§1, options A–D).** A centred box's edges
  round one by one, half to even, about a centre that is usually
  fractional (`units.Box.rounded`). So where its near edge lands depends
  on a fraction the browser does not have. The options are:
  - a table from the server, worked out with the layout's own rounding
    (A, recommended);
  - the rounding rule copied into the browser (B);
  - drawing it approximately (C);
  - keeping the outline (D).
* **E: plain arc gauges, by one more barrel twin.** A gauge's arc draws
  through `WfbArc.drawProgress`, a fill fraction of its sweep. The JSON
  carries the fraction, `raster.js` gains a `drawProgress` twin, and a
  centred `style: arc` gauge's radius and angles become live.
* Every new declaration is proven the way plan 28's were: the browser's
  prediction draws, byte for byte, what the server's own landed edit
  draws, over the example faces.
* Nothing on the watch side changes, nor in `wfb build`.

**What it should reach**, on the example faces (fr955), against today's
63 of 304:

| Handles | Count | Today | After |
|---|---:|---|---|
| centred rectangles and rounded rectangles | 120 | outline | live under A or B, within 1 px under C, outline under D |
| centred ellipses | 10 | outline | as above, if slice 0 finds the rounding unique for them |
| centred plain arc gauges (radius, angles) | 42 | outline | live (E) |
| centred gauge bars | 18 | outline | outline: the fill width is computed from the width |
| groups, graphs | 26 | outline | outline: they re-lay out their children or re-sample |
| aligned, segments and scale gauges, and the rest | 25 | outline | outline |

Up to **235 of 304** under A or B, if slice 0 confirms the rounding for
every centred box shape; **105 of 304** under D (E alone).

## 1. Decisions

### Decided

- **E (user, 2026-10-03):** a `drawProgress` twin for plain arc gauges,
  in a plan of its own after plan 28 closed.
- **D (user, 2026-10-03):** centred boxes keep the outline for now. A, B
  and C stay below as the options considered, for a later plan.

### Considered: how centred boxes become live

| Option | How it works | Exact? | Cost and risk |
|---|---|---|---|
| **A. A table from the server (recommended)** | When an element is selected, the browser fetches, for each centred handle, every extent the box can reach and the `Layout` constants each gives, worked out with the layout's own pieces (`Resolver.point`, `units.Box.rounded`). A drag is looked up in the table. | yes | A small request per selection. The rule stays in Python, in one place; the browser holds a lookup, not a rule. |
| **B. The rounding rule in the browser** | The handle carries the box's unrounded centre, and `raster.js` rounds the two edges half to even as `Box.rounded` does. | yes | No request. But a piece of layout lives twice, in Python and in JavaScript; the corpus test would catch drift. |
| **C. Drawn approximately** | The box is drawn grown about its centre, a pixel off at worst, and the release corrects it, as a move already is for 26 of 319 elements. | within 1 px | The least work. But "live" stops meaning exact for a resize. |
| **D. Keep the outline** | No change for centred boxes; only E is built. | — | None. |

A and B both have to settle unreachable extents: with a whole-pixel
centre, odd widths cannot be reached, since both edges round at once. The
table, or the rule, can tell the browser which extents exist, so a drag
snaps to one the release really lands.

**The recommendation is A.** It is exact, and the layout's rounding stays
single-sourced in Python, which is what the draw program set out to
achieve (research 27). Slice 0's measurement serves A and B alike.

### Had A been chosen

- **C1: where the table is worked out.**
  - **A (recommended):** each kind, beside `live_handle`:
    `ElementKind.handle_table(view, placed, handle)`. A box kind builds
    the box for each extent with the layout's own pieces (`Resolver.point`
    for the unrounded centre, `units.Box.rounded`). The table therefore
    rounds exactly as the layout does, by construction.
  - **B:** in `wfb/studio/drag.py`, one function for every box kind.

  A keeps "what a kind's handle does" in the kind, as `live_handle` does.
- **C2: when the browser fetches it.**
  - **A (recommended):** when an element is selected, so the table is
    there by the time a handle is pressed. It is cached per frame version
    and handle.
  - **B:** on press. The outline shows until it arrives.
- **C3: an extent the box cannot reach.** With a whole-pixel centre, odd
  widths are unreachable: both edges round at once, so the width steps by
  2.
  - **A (recommended):** the drag snaps to the nearest reachable extent,
    so the drawn box is exactly what the release lands.
  - **B:** draw an outline at an unreachable extent.
- **C4: how far the table reaches.** **A (recommended):** every extent
  from 1 px to the parent's extent on that axis, keyed by extent. That is
  at most a few hundred entries a handle.

## 2. Slices

Each slice ships with:
- the fast suite and `mypy --strict` green;
- `tools/snapshot.py` unchanged;
- its own measurement written down here.

Every new guard is driven red.

### Slice 0 — measure before building

- **Is the table unique?** For every centred rectangle, rounded rectangle
  and ellipse handle in the corpus, and every extent change from −20 to
  +20 px:
  - run the real `wfb.edit.resize`;
  - record whether it landed, and the constants it produced;
  - check that one extent always gives the same constants, whatever author
    value the server chose to land there (the claim that the edges'
    rounding is monotonic).

  Record per shape: unique or not, and which extents are unreachable. An
  ellipse's `RX`/`RY` and a rounded rectangle's `CORNER` are the
  constants most likely to depend on more than the extent.
- **Cost:** a table's build time per handle, and its size.
- **Gauges:** confirm that a plain arc gauge draws only `arc` ops, its
  track and its fill (rings included), and that its fill fraction is the
  one value the JSON folds away.

  Shapes that fail stay outlined, with the reason recorded here.

### Slice 1 — centred boxes (as written, for A)

Written for option A. Under the other options:
- **B:** the handle carries the unrounded centre, and `raster.js` gains
  `Box.rounded`'s rule in place of the lookup. The corpus test is the
  same.
- **C:** the kind declares the near edge at −½ per pixel, and the browser
  rounds it. The corpus test checks within 1 px, not byte for byte.
- **D:** the slice is dropped.

- `ElementKind.handle_table`, built for the shapes slice 0 cleared, and
  `live: {"table": true}` on their handles.
- **An endpoint**, `GET /api/documents/{id}/handle?device&element&key`
  (with the frame's switches): `{version, table: {extent: {const:
  value}}}`.
- `raster.liveOps` with a table: the drag's extent is looked up, and each
  named constant set to its value.
- **Tests:**
  - the corpus test of plan 28 slice 3, extended: every table-live
    handle, and extent changes across its whole range, the browser's
    lookup drawing exactly what the server's landed edit draws;
  - a table entry deliberately off by one fails it.

### Slice 2 — plain arc gauges (E)

- `to_json`'s `arc` op from `ArcProgress` keeps its `fraction`.
- `raster.drawProgress`, swept in Node against `barrel.draw_progress` the
  way `drawSpan` is.
- `ProgressKind.live_handle` for a centred `style: arc` gauge: its radius
  (`{"consts": {"<P>_RADIUS": 1}}`), and its start angle and sweep
  (`{"angle": ...}`). `liveOps` works the call out again through
  `drawProgress` when the op has a fraction.
- **Tests:** the corpus test over every live gauge handle; the fraction
  dropped fails it.

### Slice 3 — the canvas, and close-out

- **The canvas:**
  - fetches the selected element's tables (C2);
  - snaps a table-live drag to a reachable extent (C3) and draws it live;
  - draws gauges live as any other declared handle.
- **Checked in a DOM** (jsdom against a live server):
  - a centred card's width drag draws the frame from ops;
  - the drag snaps to a reachable width;
  - a gauge's sweep is drawn live;
  - the table request's timing is recorded;
  - no page errors.
- **Docs:**
  - `docs/guide/studio.md`: which handles draw live;
  - `docs/limitations.md`;
  - the roadmap, if it names the live handles;
  - research 29's status.
- Delete this plan; add its row to `docs/plans/README.md`.

## 3. Risks

- **The table may not be unique for every shape.** That is slice 0's
  question, answered before anything is built. A shape that fails stays
  outlined, as it is today.
- **A table request per selection.** On loopback the table is pure
  arithmetic over at most a few hundred extents. Slice 0 measures it.
- **The browser holds a lookup, not a rule.** It cannot drift from the
  layout, because the layout computes every entry. The corpus test still
  proves each entry against a real edit.
