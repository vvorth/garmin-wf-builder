# examples/

Loaded automatically when working in `examples/`. Each example's header
comment explains what it exercises; `slots/` is the only one using the Data
axis (`config: data:`), `config/` the colour axes and `color_scheme:`,
`styles/` `layouts:` and `config: style:` (widget-set switching, not just
colour), and `analog/` analog hands (plan 04, 2026-09-14) -- two hand sets
in two layouts, an off-centre small-seconds subdial, all four rotatable
part shapes, and a `config.*` hand colour, and `patterns/` `type: pattern`
(plan 05, 2026-09-14) -- radial and linear repeats, every part shape
including `arc`, `start:`, `skip:`/`skip_every:`, in and out of `static:`.
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
