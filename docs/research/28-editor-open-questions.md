# 28 — Closing the editor's and the draw program's open questions

**Question (user, 2026-10-01).** Close every open question left by
research 26 (the editor) and research 27 (the single draw program), now,
before planning.

**Status (2026-10-03): every question is settled, and both plans that
built on this are built and deleted.** The draw program is plan 26
(`git show 270c595:docs/plans/26-draw-program.md`), and the editor,
`wfb studio`, is plan 27 (`git show cf4b310:docs/plans/27-studio.md`).
What they are now is in `docs/lore/roadmap.md` and `docs/guide/studio.md`.
Each question's outcome is in the table's last column. §8 says how the
three questions that could not be closed on paper turned out.

**Short answer.** Ten are closed: one by the user's decisions, eight by
measurement, and #10 by a capture from the user's simulator (§7). #12 and
#13 were plan requirements, and plan 26 built both. #11 was never
measured, because the feature it was about was postponed. The editor ships
a simpler drag that needs no browser rasteriser (§8).

| # | Question (where it was raised) | Status | Answer (and outcome) |
|---|---|---|---|
| 1 | Platform, server dependencies, front-end tooling (26 §8 D1–D3) | **decided** | local web app, Starlette + uvicorn, no front-end build step (ADR 0002 amendment) |
| 2 | Does format 2 lowering rename a key the editor patches? (26 §7) | **closed** | only `align:` (split into `align`/`vertical_align`); the editor patches the author's one key (§1) |
| 3 | Element ↔ author node mapping (26 §7) | **closed** | 452/452 elements, including groups, `static:` and layout blocks, found by their `span` (§1) |
| 4 | Structural patches: add/remove key, add/delete/duplicate/reorder element (26 §3.3, §7) | **closed** | 404/404 accepted over the corpus, under three rules found here (§2) |
| 5 | Patch target under `overrides:` (26 §4.4, 27 §4) | **closed** | 18/18 drags moved exactly the devices that read the patched key (§3) |
| 6 | Font-bake memoisation (26 §3.1, §7 "large faces") | **closed** | showcase 893 → 250 ms per edit, pixels identical; incremental validation not needed (§4) |
| 7 | `codemirror-json-schema` and JSON Schema 2020-12 (26 §4.5) | **closed** | usable: no false errors, but `dependentRequired` (3 sites) is not enforced; `wfb`'s diagnostics cover it (§5) |
| 8 | Layer compositing fidelity (26 §4.3, 27 §5.4) | **closed** in 27 §5.4 | 28/29 faces stack pixel-identical; the 29th is off by 1 in one channel on anti-aliased edges |
| 9 | Can the program express `text`? (27 §5.6, §7) | **closed** | printer 102/102 byte-identical to `emit_draw`, evaluator 102/102 pixel-identical, every font and value route (§6) |
| 10 | Which ring is right on the watch, grown or stamped? (27 §2.5, §7) | **closed** (simulator, 2026-10-02) | grown: the watch draws the grown copy it is sent, and it differs from the stamp by 4–20 px per shape. The preview now draws it grown (§7) |
| 11 | Does the live drag feel direct at 60 Hz? (27 §5.3, §7) | **not measured; superseded** | the in-browser redraw from the JSON op list was postponed. The shipped drag shifts the element's own layer image and draws outlines for a resize or an angle (§8) |
| 12 | Primitive twins drift too (27 §7) | **plan requirement, built** | each barrel function the evaluator transcribes is checked against the `.mc` source, and the arc is swept over every half-degree start (`tests/test_draw_barrel.py`, §8) |
| 13 | AOD variants and group ring passes in the program (27 §2.5 scope) | **plan requirement, built** | AOD variants came with each kind's port. A group's ring is each member's own ring pass, as the watch draws it (§8) |

Probes: `docs/research/probes/gui-editor/` (`structural.py`,
`overrides.py`, `bake_cache.py`, `schema-dialect/`),
`docs/research/probes/draw-program/spike_text.py`, and
`docs/research/probes/ring-on-device/`. Results are in each `*results.txt`.
**No compiler code changed.**

---

## 1. Lowering renames and the author-node mapping

`wfb/lower.py` renames keys with `rekey`/`add`, recording an `Origin` per
rename. Of the keys the editor patches (`at`, `to`, `size`, `radius`,
`corner_radius`, `thickness`, `start_angle`, `sweep`, `points`, `align`),
**only `align` is touched**: a compass or combined value is split into
`align` and `vertical_align` (`lower.py`, the `align` branch). The editor
patches the author's text, not the lowered document, so it writes the one
`align:` key the author wrote. That is also the 3×3 picker's natural value.
A pattern part's `type` → `shape` is the only other rename near geometry,
and the editor does not change a part's type. VERIFIED (code reading).

Every `Element` carries `span`, the 1-based line and column of its key in
the author's file. Matching it against the composed tree's key marks
(`YAML().compose`) finds the author entry for **452 of 452 elements** in the
29 example faces. That includes the synthetic `static` group and each
Styles layout's static block, which point at their `static:` key. VERIFIED.

## 2. Structural patches

`probes/gui-editor/structural.py` applies each edit to the text alone,
using the composed tree's marks. It accepts a result only if:
- it parses to exactly the intended data (key order included);
- it loads through the full pipeline with no error.

| Edit | Accepted |
|---|---|
| add an absent key (`dx` into a flow or block `at:`) | **79/79** |
| remove a key (`dy` from a flow or block `at:`) | **77/77** |
| delete an element (with its leading comment lines) | **86/86** |
| duplicate an element, inserted after the original | **86/86** |
| move an element above its previous sibling | **50/50** |
| add a new element at the end of `elements:` | **26/26** |

VERIFIED. Three rules came out of the failures on the way there. They
belong in the patch engine, not in a later fix:

- **A block value ends where the next token starts.** The composed node's
  end mark sits at the *next key's column*, not at a line start. An
  element's line range is from its first leading-comment line (same
  indent) to the line before that mark, with trailing blank lines and
  shallower comments left to the next entry.
- **Deleting the last entry of a block removes the block's key too.** An
  emptied block mapping parses as null (`static:` with nothing under it).
  This happened in five faces, each deleting a block's only element
  (`background`).
- **Duplicating renames every element id inside the copy**, the element's
  own and each descendant's, or a copied `group` clashes with its
  original's children (three faces). A new element likewise takes a
  colour the face already uses: `color.white` exists in only 10 of the 26
  faces with `elements:`.

**No delete or duplicate was refused for a dangling reference** in the
corpus. As first written, this paragraph supposed that `on_hold:` or a slot
could name an element. Neither does: `on_hold:` names a complication, and
`slot:` names a `config: slots:` entry. Nothing in the format names an
element by id. A later sweep (2026-10-03) deleted every element of every
example face through the editor's gate, nested ones included. **413 of 415
were accepted.** The two refusals are the real dangling cases:
- `features/analog`'s `sport_hands` is the only element of the `sport`
  layout. Deleting it removes the emptied layout, which a style still
  names: "unknown layout 'sport'".
- `features/aod`'s `date_text` is the only child of group `info`, which
  would be left with no children: "missing required key 'children'".

Both are refused with the face untouched. VERIFIED
(`tests/test_studio_structure.py`).

## 3. A drag under `overrides:`

`probes/gui-editor/overrides.py` works on `features/shapes`, with targets
fenix8solar47mm, fenix8solar51mm and fr955. For each of its six elements
with a cartesian `at.dy`, it inserts
`overrides: { fr955: { at: { dy: <own + 5> } } }` as a text patch. It then
"drags" on each device by patching the **most specific source** of `at.dy`
for that device:
1. the device-id override;
2. else a `shape:` override;
3. else the element's own key.

| Measure | Result |
|---|---|
| drags (6 elements × 3 devices) | 18 |
| moved on the dragged device, and exactly the devices that read the patched key moved | **18/18** |

VERIFIED. A drag on fr955 patches `overrides.fr955.at.dy`, and only fr955
moves. A drag on either fēnix patches the shared key, and both fēnix move
while fr955 keeps its override. That is the rule research 26 §4.4 proposed.
The inspector's "all targets" choice is the shared key, shown with "fr955
overrides this" beside it.

## 4. Font-bake memoisation

`probes/gui-editor/bake_cache.py` memoises `wfb.emit.resources.bake` on
its arguments plus the font file's mtime, and `dilate` on its inputs. That
is what a long-lived server would do. Warm timings per edit, in ms, on
fenix8solar47mm at 2×:

| Face | Plain total | Memoised total | Resolve, plain → memoised | Pixels identical |
|---|---:|---:|---:|---|
| `features/progress` | 40 | 28 | 1 → 1 | yes |
| `features/styles` | 59 | 40 | 2 → 1 | yes |
| `features/vector-text` | 277 | 181 | 98 → 2 | yes |
| `showcase` | 893 | **250** | 652 → 7 | yes |

VERIFIED. Research 26's estimate ("under 0.5 s") holds. What remains on the
showcase is load: parse plus schema validation, 238 ms. Under research 27
§5.3 the server re-runs the pipeline on each **release**, not each pointer
move (the browser redraws the dragged layer itself), so 250 ms per drop is
acceptable. **Incremental validation is not needed.** The research 26 §7
"large faces" risk is closed.

## 5. The text pane's schema support

`codemirror-json-schema` 0.8.1 validates through `json-schema-library` 9,
constructing `Draft04` for validation and hover and `Draft07` for
completion (its `dist/features/validation.js`, `hover.js`,
`completion.js`). The schema declares 2020-12. `probes/gui-editor/
schema-dialect/` validates 353 documents with both drafts against `wfb`'s
own validator (jsonschema, 2020-12):
- every example face as written;
- four mutations of up to three elements each (an unknown key, a bad
  `type:`, a missing `type:`, a non-mapping `at:`);
- 36 documents that break only a `dependentRequired` rule.

| Draft | False errors on valid faces | Missed errors | of which `dependentRequired` |
|---|---:|---:|---:|
| `Draft04` (validation, hover) | **0** | 29 | **29 of 36** |
| `Draft07` (completion) | **0** | 29 | **29 of 36** |

VERIFIED. The 7 `dependentRequired` cases it does catch also break another
rule. So CodeMirror **never flags a valid file**, follows `$defs`/`$ref`,
and catches unknown keys and wrong types and values. It does not enforce
the schema's three `dependentRequired` sites:
- `at.angle` ↔ `radius`, twice;
- a gauge's `value` → `max`.

That is acceptable because research 26 §4.5 already shows `wfb`'s own
diagnostics in the same gutter, and they do enforce it. Monaco with
`monaco-yaml` would enforce it, but `monaco-yaml` runs
`yaml-language-server` in a web worker that has to be bundled, which the
no-build-step decision rules out. **CodeMirror with `codemirror-json-schema`
is the text pane**, vendored as one prebuilt bundle. Rebuilding that
vendored file is a maintainer step that needs Node. Using it does not.

## 6. The draw program expresses `text`

`probes/draw-program/spike_text.py` extends the `shape` spike (research 27
§2.5) to the hardest kind. Its program has:
- **string values:** a literal, a formatted reading, readings
  concatenated, and a variable holding a `placeholder`/`fallback`
  substitution under the element's null guards;
- **ops:** loading a font field (with its null check), `setColor`,
  `drawText`/`drawAngledText`/`drawRadialText`, and a null-guarded block.

The printer writes Monkey C through the emitter's `Writer`, with the format
code from the existing single-sourced `formatting.emit`. The evaluator
emulates the three `Dc` calls on the preview's existing glyph machinery,
with strings from `formatting.render`.

| Measure | Result |
|---|---|
| text elements in the examples (without `aod:`) | 102 |
| routes covered | baked, system and vector fonts; upright, `angled` and `radial` curves; literal, formatted, several placeholders, `placeholder` substitution; rings from a ring font and stamped |
| printed Monkey C byte-identical to `TextKind.emit_draw` | **102/102** |
| evaluated pixels identical to `draw_preview` at 1× and 2× | **102/102**, **102/102** |

VERIFIED. One spike bug was fixed on the way: `_emit_ring` ends a ring with
a blank line inside a vector font's `if (font != null)` too. Not covered,
because no example face has them:
- a `fallback:` substitution;
- an `aod:` override on a text.

The first is a fixture in the plan's port. The second is part of the AOD
scope (§8). With `shape`, the two spikes cover 266 of the 395 example
elements: **the two kinds research 27 named as the risk are retired.**

## 7. Grown or stamped ring: answered by a simulator capture

Research 27 §2.5 found that the preview stamped an outline ring (the shape
at the disc offsets), while the generated code draws a filled circle's,
rectangle's or rounded rectangle's ring as **one grown copy**. The same
holds for a gauge bar (one rounded rectangle, the ring's width larger, with
that width as its corner radius) and a filled circle part of a needle, a
hand or a pattern (`WfbGeom.fillCircleRotated` with the radius grown). Only
the watch's rasteriser could say which picture is true.

`docs/research/probes/ring-on-device/` holds:
- `face.yaml`, generated by `make_face.py`: five rows (circle, rectangle,
  rounded rectangle, gauge bar, filled circle part), each with a **grown**
  `outline:` (left of each pair) beside a **hand-built stamp** (right), at
  1 px and 2 px;
- `compare.py`, which takes a simulator screen capture and reports per
  pair: grown vs stamp *on the simulator*, and each cell vs the draw
  program's evaluator taking the watch's side (grown) and the preview at
  the time of the capture (stamp). Its self-check, fed its own model as the
  capture, separates grown from stamp by 2–16 px a cell in every row;
- `capture.png`, the Connect IQ simulator's screen capture of the probe on
  fenix8solar47mm (SDK 9.2.0, simulator firmware 6.0.2, the user's host,
  2026-10-02), and `compare_results.txt`, the script's report on it.

**Result (VERIFIED in the simulator, not yet on a watch).** The watch
draws the grown copy it is sent, and **it is not the stamp**. Grown vs
stamp on the simulator, 1 px / 2 px ring:

| Shape | 1 px | 2 px | What differs |
|---|---:|---:|---|
| circle | 16 | 20 | the grown ring is two pixels thick on the diagonals, the stamp's one |
| rectangle | 4 | 8 | the grown ring has square corners; the stamp leaves the corner pixels out |
| rounded rectangle | 0 | 8 | the corners |
| gauge bar | 4 | 10 | the corners, as for the rectangle |
| filled circle part | 16 | 20 | as for the circle |

So the preview was wrong to stamp. The fix is the first branch this
section foresaw: the preview draws the grown copy the watch is sent, and
the emitter keeps its one draw (4 or 8 fewer than a stamp). Plan 26's
slice 10 built it (`270c595`). Every grown ring in the preview now draws
grown, including a gauge bar's ring and a filled circle part's, and the
stamping code is deleted.

**Found on the way: Pillow's primitives are not Garmin's.** The cells show
the simulator's shapes themselves differ from the Pillow model, ring or no
ring:
- `fillCircle` of radius 14 is a different shape from Pillow's `ellipse`:
  flatter at the top, a pixel off centre, slightly asymmetric. About
  80–100 px a cell, which swamps every circle comparison above;
- `fillRoundedRectangle`'s corners differ from Pillow's by a few pixels
  each;
- a corner radius of 1 is square on the watch, while Pillow rounds it off,
  which is why the 1 px rectangle and bar rings match neither model by 4 px;
- `fillRectangle`, and the 2 px bar's grown ring, match exactly.

Matching Garmin's circle and rounded-corner rasterisation was not
attempted: it would need its own transcription from captures, the way the
arc's whole-degree rule was. `docs/limitations.md` records the gap.

## 8. Not closable on paper, or not a question

Each item says what was asked here, then how it turned out.

- **Live-drag feel (27 §5.3).**
  - *Asked:* whether redrawing a layer's partly evaluated op list in the
    browser feels direct at 60 Hz. That needs a running editor and a
    person dragging, so it was to be the GUI plan's first measurement,
    compared against the fallback: shift the layer's PNG and re-render on
    the server, throttled.
  - *Outcome:* never measured. The user's re-scope of the editor
    (2026-10-02) postponed the in-browser redraw, and it is still
    unbuilt. The editor ships the fallback:
    - during a move, the element's own layer image is shifted, which is
      exact;
    - a resize, a radius, an angle or a line's end is drawn as an
      outline;
    - on release, one round trip patches the text, gates it and returns
      the new frame. It takes 66 ms on `features/progress` and 464 ms on
      the showcase, measured over HTTP in-process.

    `wfb.draw.jsonform` exists and is tested in Python against its
    reference rasteriser, but nothing in `wfb/studio/` uses it yet.
    Research 29 studies building the browser side.
    Whether the shipped drag feels direct is checked by hand in a
    browser. No measurement is recorded.
- **Primitive twins (27 §7).**
  - *Asked:* §2.5 of research 27 found the arc rounding twin wrong, so
    every evaluator op was to get a sweep test against the barrel
    function's own arithmetic, transcribed from `runtime-lib/*.mc`. This
    was a requirement for the A7 plan.
  - *Outcome:* built across plan 26's slices. The evaluator's
    transcriptions live in `wfb.draw.barrel`. `tests/test_draw_barrel.py`
    looks up each transcribed statement in its `.mc` source (`WfbArc`,
    `WfbGeom`, `WfbMath`, `WfbScale`, `WfbSeries`, `WfbRing`). It also
    sweeps the arc over every half-degree start, which fixed the 1°
    disagreement.
- **AOD variants and group ring passes (27 §2.5's scope).**
  - *Asked:* the `_aod ? … : …` ternaries, `if (_aod)` blocks and the
    `RingPass` mode are more printer cases of the same ops. They were to
    be covered by `shape` and `text` first, proven by `tools/snapshot.py`.
  - *Outcome:* built. Each kind's port carried its AOD variants, proven
    byte-identical with `aod:` off, on, and with `dim:`. An outlined
    group's ring is now each member's own ring pass at its own width, as
    the view draws it. It used to be a dilation of the members' union.

---

## Sources

- Research 26 §3–§8, research 27 §2.5, §5, §7; research 19 §3.2.
- `wfb/lower.py` (`rekey`, `add`, the `align` branch), `wfb/ir/model.py`
  (`Element.span`, `Text.segments`), `wfb/emit/resources.py`
  (`bake_fonts`), `wfb/kinds/text.py` (`emit_draw`, `_emit_text_draw`,
  `_emit_ring`, `draw_preview`), `wfb/emit/monkeyc/shapes.py`,
  `wfb/emit/monkeyc/common.py` (`glyph_y_expr`), `wfb/preview.py`
  (`draw_text`, `draw_vector_text`, `draw_outlined`),
  `schema/wfb-face-2.schema.json` (`dependentRequired`).
- `codemirror-json-schema` 0.8.1 (npm; `dist/features/validation.js`,
  `hover.js`, `completion.js`), `json-schema-library` 9.3.5.
- Probes: `docs/research/probes/gui-editor/` (`structural.py`,
  `overrides.py`, `bake_cache.py`, `schema-dialect/`, with results),
  `docs/research/probes/draw-program/spike_text.py`
  (`spike_text_results.txt`), `docs/research/probes/ring-on-device/`
  (`make_face.py`, `face.yaml`, `compare.py`).
