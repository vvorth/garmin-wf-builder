# tests/

Loaded automatically when working under `tests/`.

- **Fast suite:** `./.venv/bin/python -m pytest -m "not slow"`. Only tests
  marked `slow` invoke the real `monkeyc`.
- **The fast suite is green.** Every example lints clean on every target:
  intended rim contact and platform gaps are accepted per element with
  `lint: {allow: [...], reason: ...}`. `test_hands_*.py` assert against
  `examples/features/analog/`, which is the generated plan-04 design and is kept that
  way; the user's hand-tuned copy is `examples/analog-custom/`. A red test
  here is a real regression.
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
