# examples/

Loaded automatically when working in `examples/`. Each example's header
comment explains what it exercises; `slots/` is the only one using the Data
axis (`config: data:`), `config/` the colour axes and `color_scheme:`,
`styles/` `layouts:` and `config: style:` (widget-set switching, not just
colour), and `analog/` analog hands (plan 04, 2026-09-14) -- two hand sets
in two layouts, an off-centre small-seconds subdial, all four rotatable
part shapes, and a `config.*` hand colour, and `patterns/` `type: pattern`
(plan 05, 2026-09-14) -- radial and linear repeats, every part shape
including `arc`, `start:`, `skip:`/`skip_every:`, in and out of `static:`,
a per-copy colour (`copy` + `date.weekday`: `week_dots` lights today,
2026-09-15), and `when_absent: hide` with a per-copy part `visible:`
(`test_visibility`, a move-bar row, 2026-09-15), and `shape: text` parts
(plan 06, 2026-09-15: `hour_numerals`, a radial ring, and `weekday_labels`,
a linear row), and `align/` `align:`/`vertical_align:` as one placement
rule on every accepting kind (plan 07, 2026-09-15) -- an hour/minute dial
with four diagonal readouts (`complication_slot`, a `group`, a `graph`,
`text`), each aligned to grow away from the centre, covering all four
`align`×`vertical_align` combinations, plus every accepting shape, both
`progress` styles, a static `icon`, and aligned hand/pattern parts.
`showcase/` is the widest single face in this directory: two `layouts:`
switched by Styles -- a quiet classic three-hand `analog` dial (`hands:`, a
radial tick `pattern`, twelve numerals as one `shape: text` pattern part)
and a data-rich `digital` dashboard (a monospaced two-tone clock, a
weather row with a dynamic `icon_for:` condition icon, a heart-rate
`graph`, `group`+`on_hold:` icon/value clusters, both `progress` styles,
and a conditional-colour status row) -- plus two shared
`complication_slot` "registers" (the Data axis, one with per-choice icon
overrides, one `choices: any`), three `color_scheme:` entries and five
`config: style:` entries pairing them with the two layouts, and
several-colour `accent_color`/`data_color` axes. Builds warning-free on
all three targets at 14.4% of the 128 KB budget.

The Phase 2 slice is no longer an
example: it is the test fixture `tests/fixtures/slice/`.

`big-clock-3` and `enduro` carry genuine, user-authored lint
warnings/errors (see `tests/CLAUDE.md`) -- not bugs to fix unasked.

### `examples/dashboard/face.yaml` is the user's own playground

The user edits this file directly between sessions and has said explicitly:
**it is a playground, leave it alone.** Do not proactively "fix" its lint
warnings, geometry or content — even a broken `wfb validate` or a failing
`test_example_is_clean_on_every_target[dashboard]` is not, by itself, a defect
to correct unless asked. Two sessions have now found this test red on `main`
at the start of work; in one, fixing it was explicitly in scope (a review
task) and the geometry fix was welcomed, in the other the user later edited
the file further and the instruction was to leave it be going forward. When in
doubt here, ask rather than assume — this is the one file in the repo where
"the test suite is red" is not automatically a bug report.
