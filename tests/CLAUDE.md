# tests/

Loaded automatically when working under `tests/`.

- **Fast suite:** `./.venv/bin/python -m pytest -m "not slow"`. Only tests
  marked `slow` invoke the real `monkeyc`.
- **11 known, pre-existing failures**, all from user-authored example
  content (the examples are the user's to change). Not regressions to chase:
  - `test_templates.py::test_example_is_clean_on_every_target[...]` for
    `dashboard` (the user's playground; its `clock` font's TTF is missing),
    `big-clock-3` and `enduro` (lint findings), `analog` (`hour_ticks`
    outside the visible area), `showcase` (`partial-update-budget`),
    `system-fonts` and `system-fonts-numbers` (`safe-area` on fr245);
  - `test_hands_codegen.py::test_the_design_has_the_shape_these_assertions_assume`
    and `::test_layout_constants_name_the_axis_then_each_part`;
  - `test_hands_preview.py::test_at_3_00_the_minute_tip_is_up_and_the_hour_tip_is_to_the_right`
    and `::test_at_9_00_the_hour_tip_is_to_the_left` (`examples/analog`
    gained a third hand set and date windows).

  If this set changes, notice it before assuming your change broke something.
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
