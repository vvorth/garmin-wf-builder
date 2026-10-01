# 28 — Closing the editor's and the draw program's open questions

**Question (user, 2026-10-01).** Close every open question left by
research 26 (the editor) and research 27 (the single draw program), now,
before planning.

**Short answer.** Nine are closed: one by the user's decisions, eight by
measurement. One is waiting on the user's simulator, with the probe built
and the comparison scripted. One can only be answered by the GUI's first
slice, and is made that slice's first measurement. Two are not questions
but plan requirements, recorded as such.

| # | Question (where it was raised) | Status | Answer |
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
| 10 | Which ring is right on the watch, grown or stamped? (27 §2.5, §7) | **needs the user** | probe face, signed `.prg` and comparison script ready (§7) |
| 11 | Does the live drag feel direct at 60 Hz? (27 §5.3, §7) | **the GUI's first measurement** | needs a running editor; cannot be answered on paper (§8) |
| 12 | Primitive twins drift too (27 §7) | **plan requirement** | every evaluator op gets a sweep test against its barrel arithmetic (§8) |
| 13 | AOD variants and group ring passes in the program (27 §2.5 scope) | **plan requirement** | the A7 plan's first slice; proven by `tools/snapshot.py` like the rest (§8) |

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
corpus. A delete of an element that `on_hold:` or a slot names would be
refused by the compiler, and the re-parse gate turns that into "cannot
delete: X refers to it". UNVERIFIED (no example has such a reference).

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

## 7. Grown or stamped ring: the one question for the user

Research 27 §2.5 found that today's preview stamps an outline ring (the
silhouette at the disc offsets), while the generated code draws a filled
circle's, rectangle's or rounded rectangle's ring as **one grown copy**.
The two differ by 8–16 px per shape in the Pillow model. Only the watch's
rasteriser can say which picture is true. Garmin's `fillCircle` and
Pillow's `ellipse` are not the same algorithm.

`docs/research/probes/ring-on-device/` holds:
- `face.yaml`, generated by `make_face.py`: circle, rectangle and rounded
  rectangle, each with a **grown** `outline:` (left of each pair) beside a
  **hand-built stamp** (right), at 1 px and 2 px;
- the signed `.prg`, built here warning-free
  (`build/ring-probe/ring-probe/ring-probe-fenix8solar47mm.prg`, 3 687 B);
- `compare.py`, which takes a simulator screen capture and reports per
  pair: grown vs stamp *on the simulator*, and each cell vs the program's
  evaluator (grown) and today's preview (stamp).

Its self-check, fed the program's own frame as the "screenshot", reports 0
differences against the program and 8–16 against the preview, as designed.

**What the answer changes.**
- If the simulator's grown cells match the program, the A7 port's planned
  preview fix stands as is.
- If they match the stamp instead, the emitter should stamp these shapes
  too, so the watch draws what research 19 measured, and the "fix" moves
  to the emitter.

Either way the program makes preview and watch agree. The question is only
which picture they agree on. UNVERIFIED until the capture.

## 8. Not closable on paper, or not a question

- **Live-drag feel (27 §5.3).** Whether redrawing a layer's partly
  evaluated op list in the browser feels direct at 60 Hz needs a running
  editor and a person dragging. It is the GUI plan's **first measurement**,
  compared against the fallback (shift the layer's PNG, re-render on the
  server, throttled). Both are designed. Only the feel is unknown.
- **Primitive twins (27 §7).** §2.5 of research 27 found the arc rounding
  twin wrong. So every evaluator op (about 24 `Dc` calls and the barrel's
  drawing functions) gets a property test that sweeps its inputs against
  the barrel function's own arithmetic, transcribed from
  `runtime-lib/*.mc`. This is an A7 plan requirement, not an open question.
- **AOD variants and group ring passes (27 §2.5's scope).** The `_aod ?
  … : …` ternaries, `if (_aod)` blocks and the `RingPass` mode are more
  printer cases of the same ops. The A7 plan's first slice covers them for
  `shape` and `text`, proven by `tools/snapshot.py` across the AOD
  fixtures. That is a plan requirement too.

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
