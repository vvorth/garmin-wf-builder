# ts/test/

Loaded automatically when working under `ts/test/`.

- **Fast suite:** `npm test` in `ts/` (`node --test`), plus `npm run
  typecheck`. The slow suite, `npm run test:slow` (`ts/slow/`), is the only
  one that runs the real `monkeyc`: it builds every slow-test design, every
  example and every fixture.
- **Never pipe a test run through `tail`, `head` or `grep`.**
  - A cut-off log can hide the failures and the summary, and then the
    whole suite has to be rerun just to read it.
  - A pipe also reports the filter's exit code, not the run's.
  - Run it whole. When the output is long, send it to a file
    (`> log 2>&1; echo "exit=$?"`), then read that file in full.
- **The fast suite is green.** Every example lints clean on every target:
  intended rim contact and platform gaps are accepted per element with
  `lint: {allow: [...], reason: ...}`. A red test is a real regression.
- **Goldens** (`goldens/`, checked by `goldens.test.ts`): the diagnostics of
  a frozen corpus of 2,820 small designs (`corpus/designs.json.gz`, each
  written to hit one diagnostic), and each example's and fixture's
  diagnostics, project file hashes and preview pixel hashes. `monkeyc/`
  holds generated Monkey C the user reviews (`golden-monkeyc.test.ts`). A
  golden diff is a real output change: explain it, do not just regenerate
  (`WFB_UPDATE_GOLDENS=1 npm test`, or `node tools/goldens.ts`). Goldens
  never read the user's own Garmin fonts (`WFB_NO_GARMIN_FONTS=1`).
- **Shared helpers:** `designs.ts` loads, resolves, generates and draws a
  design written inline (`load`, `face`, `resolved`, `generated`, `view`,
  `drawn`, `MINIMAL`). Reach for these before writing a private copy.
- **The editor:** `edit.test.ts` runs the patch engine over the example
  corpus; `studio*.test.ts` the worker and server. `page-*.test.ts` run the
  page itself in Node (`page-harness.ts`): its pure modules, its panels
  rendered with preact over a minimal DOM (`studio_dom.mjs`) with their
  controls clicked, and the whole page against a stand-in worker answering
  from a real summary (`tools/summary.ts`). `garmin-raster.test.ts` holds the preview's shapes to the simulator captures.
  Nothing drives a browser: the pages are checked by hand.
- **`fixtures/slice/`** is the golden source and the real TTF every font
  test bakes (Open Sans). It is a fixture, not an example: a missing
  fixture fails rather than skips, because a skip once silently turned the
  goldens off.
- **Drive every new diagnostic red** against violating input before trusting
  it, and cut the whole path so a second branch cannot quietly answer.
- **A test must be able to fail against a knowingly broken implementation.**
  If it cannot, it tests the wrong contrast. Example: `00:00`/`11:11` cannot
  catch broken monospacing, because Open Sans figures are already tabular;
  `Fri 11:11`/`Wed 00:00` can.
- An error for a rejected named block must be **one error, not N**: the
  rejected name stays bound in scope (`docs/lore/codegen.md`).
- The incidents behind these rules are in `docs/lore/working-agreement.md`.
