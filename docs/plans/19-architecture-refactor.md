# Plan 19: architecture changes proposed by the 2026-09-24 code review

**Status: A0–A5 done (A4 and A5 2026-09-25). The P6 rule is in `CLAUDE.md`
§7. A6 and the small items in §3 are approved and in progress. A7 awaits a
user decision.**
These change the project's shape (root `CLAUDE.md` §7: stop and ask), so
**do not start an unapproved step**, and record each decision in §5. Delete
this file once every step is built or dropped. The full plan as written,
including the A0–A3 sections, is at
`git show c0b0601:docs/plans/19-architecture-refactor.md`.

## 1. Done

Each step was proven with `tools/snapshot.py` (357 cases: every example
and fixture's generated project on three device mixes, lint on every
installed device, eight preview variants, every CLI command).

| Step | Commits | As built |
|---|---|---|
| A0 snapshot harness | `927e4f9` | `tools/snapshot.py save`/`diff`/`compare` (`docs/development.md`, "Tests"). |
| A1 host/device parity | `d7d8edd`, `56ad550` | `wfb.kinds.pattern.PatternTextAngle`, `layout.radial_direction_sign`/`radial_align_offset`, `ir.aod_color_choice`, `wfb.kinds.hands.HAND_ANGLES` (pinned to `WfbHands.mc` by a test; both moved to their kind modules by A4). The slow `tests/test_expr_parity.py` checks operators against `monkeyc`'s constant folder and compile-checks every function. It cannot *run* Monkey C, so runtime-only behaviour (`Math.round`, the `WfbMath` bodies) stays hand-ported. Output identical. |
| A2 roles | `9fdd7c1` | `Element.bound_expressions()` (role-tagged, in the old order) with a per-kind `VALUE_ROLES`, and `Element.color_roles()` (`ColorRole`). The five absence checks stay separate (different rules) but read the roles. Output identical. |
| A3 usage from emitted code | `c0b0601` | `wfb/emit/usage.py` scans the generated sources: `barrel_modules` for the copied runtime-lib files, `toybox_modules` for the view's imports. It replaces `_barrel_for`, `Code.helper` and `_view_imports`. 29 views gained one redundant-but-correct import each. Fonts are out of reach: baking precedes layout, and font loads are inputs to emission. |
| A4 kind registry | `60a8769` (design), `901f90d` (scaffolding), then one commit per kind: `3631f3f` progress, `2126318` icon, `8f76928` graph, `f3c5807` shape, `e44a5dd` text, `929df0e` hands, `d633b68` pattern, `508f044` complication_slot, `45b9e2f` group | `wfb/kinds/`: one `ElementKind` per kind, whose hooks replace every per-kind ladder and table in the stages (the hook table is `ElementKind`'s own fields). Each kind module holds the builder, resolver, preview, emitter and layout-constant code only that kind uses; shared helpers stay in their stage. `group` owns only `build`: its resolution stays `Resolver._resolve_list`'s structural recursion, and preview and emit filter it out before dispatch. Stage modules import the package, never a kind submodule, and read the registry only at call time. `tests/test_kinds.py` pins the registry to the schema's discriminators. Output identical at every commit. |
| A5 resolve once, union | the commit that added this row | `wfb.build` hands `resolve_all`'s faces to `generate(..., resolved=...)`, which no longer bakes or resolves again (a caller without them, such as a test, still passes `baked`). Per-device needs are decided over every target: `Guards.partial_update_unsupported` for `onPartialUpdate` (it read device 0), and the icon-glyph need as a union. `generate` emits the view and delegate from every target and compares them; a difference is a `shared-source` build error (`Divergence`), driven red by a test. The view's header no longer names device 0, and its partial-update comment no longer quotes device 0's clip share. A `shared-view` note names the MIP targets of a mixed AMOLED/MIP build, which carry the AOD code without running it. Generated code is identical apart from those two comments; the note is new output. |

## 2. Open problems, with evidence

### P1. Adding an element kind doesn't scale

**Addressed by A4 (built, §1).** The evidence as measured:

About **120 kind/shape switch sites** (`isinstance(…, Placed*)`,
`kind ==`, `shape ==`), measured after the review:

| Module | Sites |
|---|---|
| `emit/monkeyc/layout_constants.py` | 24 (now a per-kind table) |
| `preview.py` | 22 |
| `lint.py` | 20 |
| `emit/monkeyc/view.py` | 17 |
| `emit/project.py` | 11 |
| `emit/monkeyc/common.py` | 10 |
| `emit/monkeyc/rotated.py` | 9 |
| `emit/monkeyc/shapes.py` | 7 |

(A2 and A3 removed some of these: `ReadPlan._value_expressions`,
`_hold_auto_sources` and `_barrel_for` no longer switch on kind.) On top of
them, the builder has about 10 per-kind facts in separate tables:
`_build_element` dispatch, `_KIND_SYMBOLS`, `_STATIC_FORBIDDEN_KINDS`,
`_AOD_FONT_UNSUPPORTED`, and more. Layout, preview and emit each have their
own `_BY_TYPE` table. Font use is derived by separate walks
(`resources.glyph_set`, `resources.icon_font_specs`,
`common._loaded_fonts`/`_aod_only_fonts`/`_vector_fonts_used`).
`validate.py` hard-codes `ELEMENT_TYPES` and per-kind keys that the schema
already defines.

### P2. Preview and codegen still implement some rules twice

A1 unified the per-copy text angle, the radial sign and offset, the AOD
colour choice and the hand angles. Still written on both sides, held
together by "matches X exactly" comments:

- AOD layout/geometry override: `_aod_geometry` vs `AodStyle.value/layout`
- layout gating, AOD membership, the awake-only second-hand skip
- pattern arc start composition
- pattern when-absent early return, fill/outline per shape with the AOD
  swap
- `vertical_align: bottom` glyph shift, the radial-text `top` radius shift
- progress fallback fraction, whole-degree `arc_span` vs `WfbArc`
- the complication-slot pair layout

### P3. Lint recomputes layout results

`visible_reach` runs after `inside_visible_area_for`, and
`inside_visible_area_for` runs twice.

### P4. Codegen uses device 0 for everyone

**Addressed by A5 (built, §1).** The evidence as found:

`wfb/emit/project.py` generates the shared view and `needs_icon_glyphs`
from `devices[0]`'s resolved layout (the barrel set is now scanned from
that view's text, so it follows the same device). `build.build` resolves
every device in `resolve_all`, discards the result, and `generate` resolves
again. Anything whose presence varies per device silently follows the
first target.

### P5. IR records that do too many jobs

- `HandPart` is about 30 fields covering the hand primitive, the pattern
  primitive and the pattern text; many rules reduce to "`None` unless
  pattern and text". `ResolvedHandPart` has 34 fields for five shapes.
- Font fields (`font_reference`, `font_is_custom`, `font_px`,
  `font_metric`, `font_face`, `font_is_vector`, `font_available`) and five
  `curve_*` fields are repeated on `PlacedText`, `ResolvedHandPart` and
  `PlacedComplicationSlot`.
- The named blocks (palette, schemes, layouts, slots, fonts, hand sets)
  each keep their own dict, `_NamedBlock` and lookup method.

### P6. Comment volume

Before the review there were about 12k comment/docstring lines against 17k
code lines, much of it "plan N slice M" history that the house style says
belongs in git. The review cut about 2k.

## 3. Proposed steps

### A4. One spec object per element kind (addresses P1)

Built; see §1. The approved design, with its hook table and migration
plan, is at `git show 60a8769:docs/plans/19-architecture-refactor.md`. The
rule it set for where code goes is in `docs/development.md` ("Element
kinds").

### A5. Resolve once, and decide per-device (addresses P4)

Built with the union choice; see §1. A probe before the change emitted the
view and delegate from each target's own resolved face, for every example
and fixture on its own targets and on all 22 installed devices: they
differed only in the header's device name and the partial-update comment.
The one per-device *code* decision, `onPartialUpdate`, cannot diverge in a
build that compiles, because low-power elements on an AMOLED target are a
`partial-update` error. The union therefore changes no generated code; the
cross-check makes that hold by construction from now on.

### A6. IR shape cleanups (addresses P5; independent, do opportunistically)

- `ResolvedFont` and `ResolvedCurve` value objects on `PlacedText`,
  `ResolvedHandPart` and `PlacedComplicationSlot` (about 150 reads to
  update). Plan 18 item 8 had to thread `fonts_root` through six layout
  functions because font data travels as loose fields.
- Split `ResolvedHandPart` into one frozen class per shape, each owning
  `ink()`/`reach()`. The same for `HandPart` in the IR, with a shared
  `TextStyle` for text and pattern-text parts.
- `NamedRegistry[T]` for the named blocks (accepted/declared/rejected plus
  one `resolve()`); `Catalogue[T]` with one `did_you_mean_notes` for
  `catalog`, `series`, `complications` and `icons` (the notes are
  hand-built in 5 places today).
- Preview: one glyph-source interface (baked sheet / system outline face /
  `.cft`) with one "place line box, blit glyph by glyph" loop, replacing
  `_draw_text`, `_blit_bitmap_text`, `_approximate_text`,
  `_draw_system_line`, `_draw_bitmap_line` and the slot text path. It is
  not pixel-identical by construction, so gate it with the snapshot tool.

### A7. A single draw program (P2's other option; only if the user wants it)

Lower each element once into a small display list of drawing steps over
symbolic expressions. Preview evaluates it, emit prints it as Monkey C.
This removes P2 entirely, but rewrites most of `preview.py` and
`emit/monkeyc/`. **Recommendation: don't**, unless the user expects many
more drawing features; extending A1's shared definitions to the P2 list
gets most of the safety for a fraction of the cost.

### Also noted (small, no decision needed beyond "go")

- Tests: move the `_face`/`_errors`/`_resolved`/`_lint` helpers duplicated
  in 5–7 files (about −120 lines) into `tests/helpers.py`; share the
  design-header builders in the `test_pattern_text*`, `test_text_outline*`
  and `test_vector_text*` families.
- Tests: run most CLI tests in-process via `cli.main(argv)` + `capsys`
  (about −20 s), and cache resolved examples per session (`dashboard`
  resolves are 4 s each, repeated across modules).
- **Built:** `wfb/emit/monkeyc/complication_slot.py`'s left/right and
  top/bottom pair layouts are one axis table (49 lines shorter), proven
  byte-identical over all 234 `icon_position:` x `align:` x
  `vertical_align:` x icon/no-icon x `icon_gap:`/`icon_color:` x guards
  cases against the old emitter, as well as by the snapshot.
- **Built:** `Binding.kind` (`wfb/expr.py`) removed, with a dated ADR 0006
  note.
- **Built:** dead or test-only code removed: `Source.intermediate_guard`,
  `icons.weather_icon_for_condition`, `icons.METRIC_ICON`/`icon_for_source`/
  `icons.get`. The `*_night` icon entries stay: they are documented,
  author-usable `icon:` names (`docs/guide/icons.md`), not dead code.
- **Built:** the sub-pixel owner in `layout.Resolver` is now one `_Owner`,
  set per scope by `_owned_by`, which restores the previous owner on exit:
  `_resolve_hand_part` narrows it for the part's duration only. Threading
  it as a parameter was the proposal; it would add an argument to 34
  `_extent` call sites that almost all pass "the element being resolved",
  so the scope is the smaller fix for the same bug.

## 4. Suggested order

1. **A4** (built), one kind per commit.
2. **A5** (built), with the union.
3. **A6** items and the small items as convenient; plan 18 §2 leftovers.
4. **A7** only on an explicit decision.

## 5. Decisions

| Question | Options | Recommendation | User's answer |
|---|---|---|---|
| Approve A0–A3? | each separately | yes | approved 2026-09-24, built |
| Parity approach | A1 (shared definitions + parity test) / A7 (draw program) | A1 | A1 |
| Approve A4? | yes / no | yes | approved 2026-09-24, built 2026-09-25 |
| Per-device needs (A5) | device 0 (today) / union across targets | union | union, 2026-09-24, built 2026-09-25 |
| Approve A6 items? | each separately | yes, opportunistically | all approved 2026-09-25 |
| Small items (§3 "Also noted") | go / don't | go | go, 2026-09-25 |
| P6 comment rule in `CLAUDE.md` | add / don't | add | added 2026-09-25 |
| A7 | build / don't | don't, unless many more drawing features are expected | asked why, 2026-09-25; open |
