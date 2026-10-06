# tests/

Loaded automatically when working under `tests/`.

- **Fast suite:** `./.venv/bin/python -m pytest -m "not slow"`. Only tests
  marked `slow` invoke the real `monkeyc`.
- **Never pipe a test run through `tail`, `head` or `grep`.**
  - A cut-off log can hide the failures and the summary, and then the
    whole suite (about six minutes) has to be rerun just to read it.
  - A pipe also reports the filter's exit code, not pytest's.
  - Run it whole. When the output is long, send it to a file
    (`> log 2>&1; echo "exit=$?"`), then read that file in full.
- **Type check:** `./.venv/bin/python -m pytest -m typecheck` runs
  `mypy --strict` over `wfb/` (`mypy.ini`) against `tests/mypy-baseline.txt`.
  It is its own test set: `conftest.py` deselects it unless `-m` names it.
  `wfb/` is clean and the baseline empty, so any error fails it: fix it.
  Never add to the baseline to get green.
- **The fast suite is green.** Every
  example lints clean on every target: intended rim contact and platform
  gaps are accepted per element with `lint: {allow: [...], reason: ...}`.
  `test_hands_*.py` assert against `examples/features/analog/`, which is the
  generated analog-hands design and is kept that way; the user's hand-tuned copy
  is `examples/analog-custom/`. A red test here is a real regression.

  Two availability tests (now in `ts/test/availability.test.ts`) and
  `test_font_registry.py::test_every_installed_ww_filename_resolves_or_is_unmapped`
  were once known failures (2026-09-23): `fenix847mm`'s
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
- **`test_ts.py` runs `ts/`'s own tests (`node --test`) and its type
  check (`tsc`)**, so the fast suite keeps both halves green. Like the
  rasteriser's tests, it fails rather than skips without a Node that runs
  `.ts` files (`./tools/setup-env.sh` installs one). Parity with the Python
  stages is `npm run parity` in `ts/`, not part of this suite: it needs
  `tools/oracle.py`'s dump.
- **Shared helpers live in `tests/helpers.py`**: loading, resolving and
  linting a design from text (`load_face`, `resolve_text`, `lint_text`, ...),
  running `wfb` in-process (`run_cli`; use a real subprocess only to test
  `wfb.py` itself), and the session-cached examples (`example`,
  `resolved_example`, read-only). Reach for these before writing a new
  private copy.
- **The editor** (`wfb studio`): `ts/test/edit.test.ts` runs the patch engine over
  the example corpus; the editor's worker and server are tested in
  `ts/test/studio*.test.ts`. `test_studio_frontend.py` runs the page's pure
  modules in Node (skipped without `node`), and `test_studio_panels.py`
  renders the panels with preact over a minimal DOM (`studio_dom.mjs`) and
  clicks their controls, checking the edits they send; `test_studio_app.py`
  renders the whole page (`ts/app/app.js`) the same way against a stand-in
  worker answering from a real summary (`ts/tools/summary.ts`), and presses
  its keys. `test_studio_raster.py` holds
  the browser's rasteriser (`raster.js`) to Pillow byte for byte, and
  **fails** without Node, being that rasteriser's only guard. Nothing here
  drives a browser: the pages are checked by hand.
- **`tests/fixtures/slice/`** is the golden source and the real TTF every font
  test bakes (Open Sans). It is a fixture, not an example: a missing fixture
  fails rather than skips, because a skip once silently turned the goldens off.
- `ts/test/goldens/` holds the frozen output (`ts/test/goldens.test.ts`) and,
  in `monkeyc/`, generated Monkey C the user reviews. A golden diff is a real
  output change: explain it, do not just regenerate.
- **Drive every new diagnostic red** against violating input before trusting
  it, and cut the whole path so a second branch cannot quietly answer.
- **A test must be able to fail against a knowingly broken implementation.**
  If it cannot, it tests the wrong contrast. Example: `00:00`/`11:11` cannot
  catch broken monospacing, because Open Sans figures are already tabular;
  `Fri 11:11`/`Wed 00:00` can.
- An error for a rejected named block must be **one error, not N**: the
  rejected name stays bound in scope (`docs/lore/codegen.md`).
- The incidents behind these rules are in `docs/lore/working-agreement.md`.
