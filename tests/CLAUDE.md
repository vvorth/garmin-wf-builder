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

  `test_availability.py::test_an_ordinary_reader_is_available_everywhere_installed`,
  `test_devices.py::test_every_target_has_weather_and_solar_intensity` and
  `test_font_registry.py::test_every_installed_ww_filename_resolves_or_is_unmapped`
  used to be listed here too (plan 14 slice 0, 2026-09-23): `fenix847mm`'s
  incremental device install also installed `enduro3`, `fenix5`, `fenix5x`,
  `fenix947mm`, `vivoactive4` and `vivoactive4s` in the same pass (root
  `CLAUDE.md` §2), surfacing that `fenix5`/`fenix5x` (ConnectIQ 3.1.6)
  couldn't build at all under the then-current 3.2.0 manifest floor, that
  `Weather`/`solarIntensity` were never actually universal, and that 22
  installed `ww` font filenames were unmapped. All three are now fixed: the
  floor is 3.1.0 (`wfb/emit/manifest.py::BASE_API_LEVEL`), the negative
  control moved to `ActivityMonitor`/`battery` with a real positive-gap test
  for `fenix5`'s `Weather` absence, the weather readers get their own
  per-device contrast test, and the 22 filenames are mapped in
  `wfb/fonts/registry.json` (a later `venu` install surfaced two more,
  `FNT_VENU_ROBOTO_LARGE[_PLUS]_BOLD`, mapped the same way). The three
  tests above now assert real, currently-true invariants again and are
  part of the green fast suite.
- **Shared helpers live in `tests/helpers.py`**: loading, resolving and
  linting a design from text (`load_face`, `resolve_text`, `lint_text`, ...),
  running `wfb` in-process (`run_cli`; use a real subprocess only to test
  `wfb.py` itself), and the session-cached examples (`example`,
  `resolved_example`, read-only). Reach for these before writing a new
  private copy.
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
