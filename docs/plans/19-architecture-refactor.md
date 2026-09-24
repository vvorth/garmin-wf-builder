# Plan 19: architecture changes proposed by the 2026-09-24 code review

**Status: A0–A3 done (2026-09-24). A4–A7 and the small items in §3 are open
and await a user decision.** These change the project's shape (root
`CLAUDE.md` §7: stop and ask), so **do not start an unapproved step**, and
record each decision in §5. Delete this file once every step is built or
dropped. The full plan as written, including the A0–A3 sections, is at
`git show c0b0601:docs/plans/19-architecture-refactor.md`.

## 1. Done

Each step was proven with `tools/snapshot.py` (357 cases: every example
and fixture's generated project on three device mixes, lint on every
installed device, eight preview variants, every CLI command).

| Step | Commits | As built |
|---|---|---|
| A0 snapshot harness | `927e4f9` | `tools/snapshot.py save`/`diff`/`compare` (`docs/development.md`, "Tests"). |
| A1 host/device parity | `d7d8edd`, `56ad550` | `layout.PatternTextAngle`, `layout.radial_direction_sign`/`radial_align_offset`, `ir.aod_color_choice`, `layout.HAND_ANGLES` (pinned to `WfbHands.mc` by a test). The slow `tests/test_expr_parity.py` checks operators against `monkeyc`'s constant folder and compile-checks every function. It cannot *run* Monkey C, so runtime-only behaviour (`Math.round`, the `WfbMath` bodies) stays hand-ported. Output identical. |
| A2 roles | `9fdd7c1` | `Element.bound_expressions()` (role-tagged, in the old order) with a per-kind `VALUE_ROLES`, and `Element.color_roles()` (`ColorRole`). The five absence checks stay separate (different rules) but read the roles. Output identical. |
| A3 usage from emitted code | `c0b0601` | `wfb/emit/usage.py` scans the generated sources: `barrel_modules` for the copied runtime-lib files, `toybox_modules` for the view's imports. It replaces `_barrel_for`, `Code.helper` and `_view_imports`. 29 views gained one redundant-but-correct import each. Fonts are out of reach: baking precedes layout, and font loads are inputs to emission. |

## 2. Open problems, with evidence

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

### A4. One spec object per element kind (addresses P1; approved 2026-09-24)

**Design.** A registry package, `wfb/kinds/`:

- `wfb/kinds/__init__.py` defines a frozen `ElementKind` dataclass and the
  registry: `get(name)`, `for_element(element)`, `for_placed(placed)`,
  `all()` and `names()`. The registry is **loaded lazily**: the first
  lookup imports the nine kind modules, in schema order (`group`, `shape`,
  `text`, `progress`, `icon`, `graph`, `complication_slot`, `hands`,
  `pattern`). `__init__` imports no stage module. Stage modules import the
  package, never a kind submodule, and **never read the registry at
  import time**. A module-level table built from it would re-enter a
  half-imported stage module.
- `wfb/kinds/<kind>.py` holds one `ElementKind` and that kind's own code
  from every stage, as module-level functions whose first argument is the
  stage object (`b: Builder`, `r: Resolver`, `r: Renderer`). A function
  moves there **iff only that kind uses it**. Helpers shared between kinds
  (for example `Builder._build_hand_part`, which is shared by `hands:` sets
  and patterns, or preview's text blitting, which is shared by text, slots
  and pattern text) stay in their stage module. Kind modules are friends
  of every stage and may call its underscored helpers.
- The IR classes (`wfb/ir/model.py`) and `Placed*` classes
  (`wfb/layout.py`) stay where they are: they are the data model, and the
  spec references them. A 10th kind is therefore an IR class, a `Placed`
  class, one kind module and the schema.

**Rule for a switch site.** A site goes through the registry if adding a
10th kind would force an edit there: a ladder over kinds, a per-kind table
or a list of kind names. Each such site becomes one hook on
`ElementKind`. The hook's default returns the ladder's fallthrough value,
and each kind module implements its own arm verbatim. A site that asks
about one kind's own feature stays as it is: collecting every
`complication_slot`, a `graph`'s series barrel, `check_pattern_step`, or
`p.kind != "group"` ("a group draws nothing").

**Hooks** (the known sites; the migration may add more under the same
rule):

| Hook | Replaces |
|---|---|
| `name`, `ir_class`, `placed_class` | `validate.ELEMENT_TYPES` (now read from the schema's discriminator `const`s, in schema order) and every `isinstance` ladder's class list |
| `build(b, node, common)` | `Builder._build_element`'s `builders` dict |
| `extra_symbols` | `Builder._KIND_SYMBOLS` |
| `static_forbidden: (phrase, note) \| None` | `Builder._STATIC_FORBIDDEN_KINDS` |
| `aod_refusal(key, shape, literal_text)` | `Builder._AOD_FONT_UNSUPPORTED`, the shape/text arms of `_aod_refusal`, `_aod_kind` |
| `precheck(doc, bag, node) -> bool` | `validate._check_progress_style`, `_check_hands_seconds_always` |
| `resolve(r, element, parent, depth)` | `Resolver._BY_TYPE` (a group keeps its structural recursion) |
| `antialiased: bool` | `layout.ANTIALIASED_PRIMITIVES` |
| `circular_extent(placed)`, `ink(placed, fonts_root)` | the ladders in `layout.circular_extent` and `_shape_ink` |
| `draw_preview(r, placed)` | `Renderer._BY_TYPE` |
| `emit_draw(...)`, `describe(placed)` | `view._emit_element_method`'s ladder, `common._describe` |
| `layout_constants(prefix, placed)` | `layout_constants._CONSTANTS_BY_KIND` |
| `loaded_fonts(placed)`, `vector_fonts(placed)`, IR-level font/glyph hooks | `common._loaded_fonts`/`_vector_fonts_used`, `resources.glyph_set`/`icon_font_specs`, `availability.vector_fonts_used`, `lint._vector_text_carriers`/`check_glyphs` |
| `contrast_subjects(placed)` | `lint._contrast_subjects`'s ladder |

**Migration.** First a scaffolding commit: the package, nine thin kind
modules whose hooks point at the existing stage functions (such as
`build=Builder._build_progress`), and every site above switched to the
registry. Then one commit per kind moves that kind's code into its module,
starting with `progress`. Every commit must be output-identical under
`tools/snapshot.py compare`, with the fast suite at its known state.
`tests/test_kinds.py` pins the registry: its names equal the schema's
discriminators in order, and every `Element` and `Placed` subclass has
exactly one kind.

### A5. Resolve once, and decide per-device (addresses P4)

`generate` takes `resolve_all`'s resolved faces instead of re-resolving.
**Decision needed:** keep one shared view built from device 0 (today), or
union the per-device needs (icon glyphs, fonts, the barrel scan over every
device's view) across all targets, which is correct but may add unused code
to some targets. The recommendation is the union, with a lint note when the
targets diverge.

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
- `complication_slot.py:~430/~510`: left/right vs top/bottom branches
  mirror each other with the axes swapped; one axis-descriptor table saves
  about 60 lines (risky; snapshot first).
- `Binding.kind` (`wfb/expr.py`) is read by nothing, but ADR 0006 cites it;
  removing it needs a dated ADR note.
- Dead or test-only code: `Source.intermediate_guard`,
  `icons.weather_icon_for_condition` and the `*_night` entries,
  `icons.METRIC_ICON`/`icon_for_source`/`icons.get`.
- The sub-pixel owner in `layout.Resolver` is mutable state
  (`_owner_id/_span/_element`) that `_resolve_hand_part` narrows and never
  restores. Pass the owner explicitly.
- P6: add a line to root `CLAUDE.md` §7: no plan/slice history in code
  comments; cite the plan in the commit message instead.

## 4. Suggested order

1. **A5** once its decision is made (it touches `generate`, which A4 moves).
2. **A4**, one kind per commit.
3. **A6** items and the small items as convenient; plan 18 §2 leftovers.
4. **A7** only on an explicit decision.

## 5. Decisions

| Question | Options | Recommendation | User's answer |
|---|---|---|---|
| Approve A0–A3? | each separately | yes | approved 2026-09-24, built |
| Parity approach | A1 (shared definitions + parity test) / A7 (draw program) | A1 | A1 |
| Approve A4? | yes / no | yes | approved 2026-09-24 |
| Per-device needs (A5) | device 0 (today) / union across targets | union | union, 2026-09-24 |
| Approve A6 items? | each separately | yes, opportunistically | — |
| P6 comment rule in `CLAUDE.md` | add / don't | add | — |
