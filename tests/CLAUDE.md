# tests/

Loaded automatically when working under `tests/`.

- **Fast suite:** `./.venv/bin/python -m pytest -m "not slow"`. Only tests
  marked `slow` invoke the real `monkeyc`.
- **3 known, pre-existing failures. These are not regressions to chase:**
  - `test_example_is_clean_on_every_target[dashboard]`
  - `test_example_is_clean_on_every_target[big-clock-3]`
  - `test_example_is_clean_on_every_target[enduro]`

  **Also red since 2026-09-15**, from the user's own edits to
  `examples/analog/face.yaml` (`45db779`, `6fab053`: a third hand set and
  date windows). These are not regressions to chase either, and the file
  is the user's to change:
  - `test_example_is_clean_on_every_target[analog]` (`hour_ticks` reaches
    outside the visible area)
  - `test_hands_codegen.py::test_the_design_has_the_shape_these_assertions_assume`
    and `::test_layout_constants_name_the_axis_then_each_part`
  - `test_hands_preview.py::test_at_3_00_the_minute_tip_is_up_and_the_hour_tip_is_to_the_right`
    and `::test_at_9_00_the_hour_tip_is_to_the_left`

  **Also red since 2026-09-16**, from the user's `9eb0b9f` edit to
  `examples/showcase/face.yaml` (a `partial-update-budget` lint):
  - `test_example_is_clean_on_every_target[showcase]`

  **Also red since 2026-09-18**, from the user's `add3545` edit to
  `examples/system-fonts/face.yaml` (new targets; `safe-area` on fr245
  for `spine` and `large_text`):
  - `test_example_is_clean_on_every_target[system-fonts]`
  - `test_example_is_clean_on_every_target[system-fonts-numbers]` (same
    commit, same `safe-area` on fr245 for `spine`)

  (Until 2026-09-14 this list also named
  `test_ir_draw_order_matches_the_resolved_one[enduro]` and `[dashboard]`;
  both pass as of `aa9137a`.)

  `dashboard` is the user's playground; since 2026-09-14 it also declares a
  `clock` font whose `assets/OpenSans-Regular.ttf` was removed. The other two
  carry genuine, user-authored lint findings nobody has asked to clean up. If
  this set changes, notice it before assuming your change broke something.
- **`tests/fixtures/slice/`** is the golden source and the real TTF every font
  test bakes (Open Sans). It is a fixture, not an example: a missing fixture
  fails rather than skips, because a skip once silently turned the goldens off.
- `tests/golden/` holds generated Monkey C the user reviews. A golden diff is
  a real output change: explain it, do not just regenerate.
- **Drive every new diagnostic red** against violating input before trusting
  it, and cut the whole path so a second branch cannot quietly answer.
- **A test must be able to fail against a knowingly broken implementation.**
  If it cannot, it tests the wrong contrast. Example: `00:00`/`11:11` cannot
  catch broken monospacing, because Open Sans figures are already tabular;
  `Fri 11:11`/`Wed 00:00` can.
- An error for a rejected named block must be **one error, not N**: the
  rejected name stays bound in scope (`docs/lore/codegen.md`).
- The incidents behind these rules are in `docs/lore/working-agreement.md`.
