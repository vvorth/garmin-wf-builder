# Plan 19: architecture changes proposed by the 2026-09-24 code review

**Status: proposal, awaiting user decision.** Nothing here is approved.
These change the project's shape (root `CLAUDE.md` §7: stop and ask), so
**do not start a step until the user approves it**, and record each
decision in §4. Plan 18 holds the bug list from the same review. Its fixes
come first unless the user says otherwise (§3 gives the combined order).
Delete this file once every step is built or dropped.

## 0. Where things stand

The review (commits `6aacfee`..`f2efa36`) already did every *local*,
output-identical refactor: tables instead of `isinstance` ladders inside
each module, shared helpers, about 2k lines of narrative removed. Net −3.7k
lines. What is left needs cross-module changes, and this plan covers that.

## 1. Problems, with evidence

### P1. Adding an element kind doesn't scale

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

On top of those, the builder alone has about 10 per-kind facts spread over
separate tables: `_build_element` dispatch, `_KIND_SYMBOLS`,
`_STATIC_FORBIDDEN_KINDS`, `_hold_auto_sources`, `_AOD_FONT_UNSUPPORTED`, and
more. Layout, preview and emit each have their own `_BY_TYPE` table. Font
use is derived by three separate ladders (`resources.glyph_set`,
`resources.icon_font_specs`, `common._loaded_fonts`). `validate.py`
hard-codes `ELEMENT_TYPES` and per-kind keys that the schema already
defines.

### P2. Preview and codegen implement the same rules twice, and have drifted

`wfb/preview.py` re-implements in Python what `wfb/emit/monkeyc/` emits as
Monkey C, held together only by "matches X exactly" comments. Rules that
exist in both:

- AOD colour choice (override → dim → awake): `_aod_color` vs `AodStyle`
- AOD layout/geometry override: `_aod_geometry` vs `AodStyle.value/layout`
- layout gating, AOD membership, the awake-only second-hand skip
- hand angles (Python vs `WfbHands.mc`)
- the radial/linear part transform (Python vs `WfbGeom.mc`)
- pattern arc start composition
- curved-text per-copy angle `(g - copy_angle) % 360`: **three copies**
  (`layout._pattern_text_ink`, `preview._pattern_text`,
  `emit.rotated._emit_pattern_text_angle_expr`)
- pattern when-absent early return, fill/outline per shape with the AOD
  swap
- `vertical_align: bottom` glyph shift, the radial-text `top` radius shift
- progress fallback fraction, whole-degree `arc_span` vs `WfbArc`
- the complication-slot pair layout
- expression functions and strftime codes, now each in one table row with
  both halves (`wfb/expr.py FUNCTIONS`, `wfb/formatting.py Code`)

Drift already found: plan 18 items 3–4 (`round`, `percent`, `clamp`, `%`).
Constant folding uses the host half, so drift reaches generated code.

### P3. Stages re-derive the same facts separately

- "Which colours does this element draw" is answered about 6 ways:
  `lint._users_of`, `lint._contrast_subjects`, `lint._outlined_interiors`,
  `HandsElement.colors`/`PatternElement.colors`, the builder's AOD key loop,
  and `preview._aod_color`. Plan 18 item 6 comes from these disagreeing.
- "Which expression is the value" is decided by
  `ReadPlan._value_expressions` (emit) and `Builder._hold_auto_sources`
  (IR), and the two already differ on purpose.
- The absence policy is written five ways (`_check_absence`,
  `_check_other_absence`, `_check_slot_color_absence`,
  `_check_pattern_absence`, `_reject_hand_data_color`).
- Which barrel `.mc` files to copy: `emit/project.py::_barrel_for` walks
  the IR and also greps generated source for `WfbColor.dim(` and
  `WfbAodMask.apply(`. It has drifted (plan 18 item 9: `WfbTime.mc` copied
  unused).
- Lint recomputes layout results (`visible_reach` after
  `inside_visible_area_for`, and `inside_visible_area_for` twice).

### P4. Codegen uses device 0 for everyone

`wfb/emit/project.py:99` generates the shared view, the barrel set and
`needs_icon_glyphs` from `devices[0]`'s resolved layout. `build.build`
resolves every device in `resolve_all`, discards the result, and
`generate` resolves again. Anything whose presence varies per device
silently follows the first target.

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

## 2. Proposed steps

Each step is independently shippable and ordered so earlier ones make later
ones cheaper. The payoffs are estimates.

### A0. Commit the verification harness (prerequisite for everything below)

The review proved output identity with throwaway scripts that are now
lost. Recreate them as `tools/snapshot.py` (not in the fast suite):

- emit every example and fixture for its targets plus an AMOLED set
  (`fenix847mm+fenix8solar47mm+fr245+fenix6`, `fenix947mm+fr955`) and hash
  every file;
- SHA every preview variant (default, `--aod`, `--minute 7/1234`, every
  style, heatmap);
- snapshot every CLI command's stdout/stderr with `--color never/always`;
- run every lint over every example on every installed device.

`tools/snapshot.py save DIR` / `compare DIR`. It makes every later step
provable as "no output change" or "exactly these changes". Small, and
worth doing even if nothing else here is approved.

### A1. Host/device parity (addresses P2, option "a")

Extend the pattern `formatting.Code` and `expr.Function` already use:
every rule that exists in both preview and codegen becomes one pure
function or table row with both halves side by side. First targets:

- AOD choice, as a shared decision function. The review declined this as
  too small alone (preview gates on "rendering the AOD frame", emit on
  "this build emits AOD code"); revisit it together with the others.
- hand angle, the part transform, and the per-copy text angle (one
  `PlacedPattern.copy_curve_angle(part, i)` used by layout, preview and emit);
- the radial glyph positions (a pure
  `layout.radial_glyph_positions(...)` used by preview and the lint band).

Add a **slow parity test** that compiles each `Function`/`Code` row with
`monkeyc`, runs it (or a probe), and compares against the host half. This
is what would have caught plan 18 items 3–4.

### A2. Role-tagged expressions and colour roles on the IR (addresses P3)

- `Element.expressions()` returns `(role, expr)` with role in
  `{value, other, visible}`. `ReadPlan` and `_hold_auto_sources` derive from
  it; the five absence checks become one.
- `Element.color_roles()` yields `(label, expr, role ∈ {ink, ring, track,
  icon}, is_glyph)`, AOD overrides and outlines included. `_users_of`,
  `_contrast_subjects`, `_outlined_interiors`, `.colors` and the
  preview/emit AOD colour loops all consume it. This fixes plan 18 item 6
  by construction.
- Changes expression order for `IconElement` and `Graph`, so `ReadPlan`
  output may reorder: expect golden diffs and explain them.

### A3. Emitters record what they use (addresses P3)

The emitter records barrel helpers, fonts and Toybox modules as it writes
them (e.g. `SourceFile.used_barrels`, filled by `Writer.call` sites), the
way `compute_guards` already works for API gates. That replaces
`_barrel_for`'s about 60-line IR ladder and grep, and the three font-use
ladders. It changes which barrel files are copied (fewer), so run a slow
build per target. It also fixes plan 18 item 9's barrel drift.

### A4. One spec object per element kind (addresses P1; the biggest payoff)

A registry `wfb/kinds/<kind>.py`, each registering an `ElementKind` with:
IR class, schema discriminator, builder, resolver, emitter, preview
renderer, `layout_constants`, fonts used, `color_roles`, value
expressions, AOD keys accepted, static-forbidden reason, extra symbols and
description. The builder, layout, lint, preview, emit, resources and
project all dispatch through it; `validate.ELEMENT_TYPES` is read from the
schema. A 10th kind becomes one new module plus schema, not about 120
edits. It is a mechanical move once A2/A3 exist, and much harder before
them. Do it one kind at a time, starting with `progress` (small), with
A0 proving no output change after each.

### A5. Resolve once, and decide per-device (addresses P4)

`generate` takes `resolve_all`'s resolved faces instead of re-resolving.
**Decision needed:** keep one shared view built from device 0 (today),
or union the per-device needs (barrels, icon glyphs, fonts) across all
targets, which is correct but may add unused code to some targets. The
recommendation is the union, with a lint note when the targets diverge.

### A6. IR shape cleanups (addresses P5; independent, do opportunistically)

- `ResolvedFont` and `ResolvedCurve` value objects on `PlacedText`,
  `ResolvedHandPart` and `PlacedComplicationSlot` (about 150 reads to
  update).
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
  not pixel-identical by construction, so gate it with A0.

### A7. A single draw program (P2, option "b"; only if the user wants it)

Lower each element once into a small display list of drawing steps over
symbolic expressions. Preview evaluates it, emit prints it as Monkey C.
This removes P2 entirely, but rewrites most of `preview.py` and
`emit/monkeyc/`. **Recommendation: don't**, unless the user expects many
more drawing features; A1 gets most of the safety for a fraction of the
cost.

### Also noted (small, no decision needed beyond "go")

- Tests: move the `_face`/`_errors`/`_resolved`/`_lint` helpers duplicated
  in 5–7 files (about −120 lines) into `tests/helpers.py`; share the
  design-header builders in the `test_pattern_text*`, `test_text_outline*`
  and `test_vector_text*` families.
- Tests: run most CLI tests in-process via `cli.main(argv)` + `capsys`
  (about −20 s), and cache resolved examples per session (`dashboard`
  resolves are 4 s each, repeated across modules).
- `complication_slot.py:~430/~510`: left/right vs top/bottom branches
  mirror each other with the axes swapped; one axis-descriptor table saves
  about 60 lines (risky; A0 first).
- `Binding.kind` (`wfb/expr.py`) is read by nothing, but ADR 0006 cites it;
  removing it needs a dated ADR note.
- Dead or test-only code: `Source.intermediate_guard`,
  `icons.weather_icon_for_condition` and the `*_night` entries,
  `icons.METRIC_ICON`/`icon_for_source`/`icons.get`, and `Guards.any`.
- The sub-pixel owner in `layout.Resolver` is mutable state
  (`_owner_id/_span/_element`) that `_resolve_hand_part` narrows and never
  restores. Pass the owner explicitly.
- P6: add a line to root `CLAUDE.md` §7: no plan/slice history in code
  comments; cite the plan in the commit message instead.

## 3. Combined order (plans 18 + 19)

1. Plan 18 items 1–2 (build break, wrong error on in-scope devices).
2. **A0** harness.
3. Plan 18 items 3–4 together with **A1** (the parity test catches them).
4. Plan 18 item 5.
5. **A2** (absorbs plan 18 item 6), then plan 18 item 7.
6. **A3** (absorbs plan 18 item 9's barrel drift).
7. Plan 18 item 8, then **A5**.
8. **A4**, one kind per commit.
9. **A6** items as convenient; plan 18 item 9 leftovers.
10. **A7** only on an explicit decision.

## 4. Decisions

| Question | Options | Recommendation | User's answer |
|---|---|---|---|
| Approve A0–A4? | each separately | yes, all | — |
| Parity approach | A1 (tables + parity test) / A7 (draw program) | A1 | — |
| Per-device needs (A5) | device 0 (today) / union across targets | union | — |
| P6 comment rule in `CLAUDE.md` | add / don't | add | — |
