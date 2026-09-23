# tests/

Loaded automatically when working under `tests/`.

- **Fast suite:** `./.venv/bin/python -m pytest -m "not slow"`. Only tests
  marked `slow` invoke the real `monkeyc`.
- **The fast suite is green**, with the known exceptions below. Every
  example lints clean on every target: intended rim contact and platform
  gaps are accepted per element with `lint: {allow: [...], reason: ...}`.
  `test_hands_*.py` assert against `examples/features/analog/`, which is the
  generated plan-04 design and is kept that way; the user's hand-tuned copy
  is `examples/analog-custom/`. A red test here, outside the list below, is
  a real regression.
  - `test_templates.py::test_example_is_clean_on_every_target[showcase]` —
    pre-existing (predates plan 14), unrelated to any AMOLED/AOD work: an
    `off-screen` warning on `numerals` plus a `graphics-pool` note on the
    static buffer. Not caused by a target-list or device-install change.
  - `test_availability.py::test_an_ordinary_reader_is_available_everywhere_installed`,
    `test_devices.py::test_every_target_has_weather_and_solar_intensity`,
    `test_font_registry.py::test_every_installed_ww_filename_resolves_or_is_unmapped`
    (plan 14 slice 0, 2026-09-23) — these iterate **every installed
    device**, not just the three verification targets or `fenix847mm`.
    Re-running `tools/setup-env.sh` to install `fenix847mm` also installed
    every other not-yet-installed `vendor/devices/` entry in the same pass
    (incremental install copies in everything new, root `CLAUDE.md` §2):
    `enduro3`, `fenix5`, `fenix5x`, `fenix947mm`, `vivoactive4`,
    `vivoactive4s`. `fenix5` lacks `Toybox.Weather` entirely and several of
    these older devices' own `.cft` filenames aren't in the font registry —
    both real gaps in those devices' support, not in `fenix847mm` or in
    anything plan 14 touches. Fixing them is out of scope for plan 14.
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
