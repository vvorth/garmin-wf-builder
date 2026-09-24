# Plan 18: bug fixes from the 2026-09-24 code review

**Status: open, not started.** The user asked for this list. Nothing here is
fixed yet. Work top to bottom (§1). Delete this file once every item is
built or explicitly dropped (`docs/CLAUDE.md`).

**Where these came from.** A seven-part review/refactor pass (commits
`6aacfee`..`f2efa36`) changed no output. These are behaviour bugs it found
and deliberately did **not** fix, because each fix changes output or
diagnostics. Line numbers are as of `f2efa36`; re-grep before trusting them.
Architecture proposals from the same review are in plan 19.

## 0. How to work each item

- **Red first.** Write the failing test against the current code before
  touching the fix (root `CLAUDE.md` §7, "A guard nobody has watched fail
  is not a guard"). The test must fail for the reason described here.
- **Golden diffs are real output changes.** If `tests/golden/` moves, say
  which item moved it and why in the commit message. Never just regenerate.
- **One item per commit** (items 3 and 4 may share one). Commit message
  `fix(<area>): …`, citing `plan 18 item N`.
- **Same-commit docs rule:** update `docs/guide/`, `docs/limitations.md`,
  `docs/lore/*` and ADRs in the same commit when a fix makes them stale.
- Fast suite: `./.venv/bin/python -m pytest -m "not slow" -q`. The only known
  failure is `test_templates.py::test_example_is_clean_on_every_target[showcase]`.
  For items that change generated Monkey C, also run
  `bash -l -c './.venv/bin/python -m pytest -m slow -q'` (real `monkeyc`,
  must stay warning-free).

## 1. Fix order

| # | Item | Why at this position | Changes output? |
|---|---|---|---|
| 1 | `aod: {format}` with `%h` fails to compile | real build break, one-line fix | generated code, affected faces only |
| 2 | Weather readers lack `requires_module` | wrong ERROR on in-scope devices (fenix5/5x) | lint findings + guards on those devices |
| 3 | `round` host ≠ device, and folding bakes it in | wrong **generated code**, not just preview | generated code when folding `x.5` |
| 4 | `percent` / `clamp` / `%` host ≠ device | wrong preview/folding; same fix site as 3 | preview; folding of constant `percent` |
| 5 | Group-inherited `aod:` keys silently ignored | violates "friendly error, never a silent no-op" | new errors on designs that were silently wrong |
| 6 | Colour users miss `outline.color` / `aod: {color}` | un-suppressible, misleading `palette-dither`/`config-unsupported` | lint text/suppression only |
| 7 | `_backdrop` ignores layouts and modes | false/missed `contrast` warnings | lint findings |
| 8 | `wfb preview --fonts` only reaches drawing | preview draws with one font, measures with another | preview + lint under `--fonts` |
| 9 | Minor batch | cheap, low risk | messages mostly |

Items 3–4 are best done together with plan 19 step A1 (the host/device
parity test). If plan 19 is not approved, do them standalone as written.

## 2. Items

### 1. `aod: {format: ...}` using `%h` fails to compile

- **Symptom.** Awake `format: "{:%H:%M}"`, `aod: {format: "{:%h:%M}"}` on a
  time text, AMOLED target (reproduced on `fenix847mm`):
  `monkeyc: Undefined symbol ':settings'`.
- **Cause.** `wfb/emit/monkeyc/readplan.py:104-121`. The TIME branch calls
  `formatting.extra_paths(element.format, Type.TIME)` on the awake format
  only. The DATE branch just below already loops over
  `[element.format, element.aod.format]`.
- **Fix.** Make the TIME branch loop over the same two specs as the DATE
  branch. Better still, merge both branches into one loop over `specs` with
  the value's type.
- **Test.** A codegen test asserting `device.is_24_hour`'s reader is declared
  for the case above, plus a slow build of the same design.

### 2. Weather readers don't declare `requires_module="Weather"`

- **Symptom.** On `fenix5`/`fenix5x` (no `Toybox.Weather`), every
  `weather.*` binding gets `api-gated-unguardable` (an ERROR) instead of a
  guardable module gap (an `api-gated` warning plus a `has :Weather` guard).
  Visible in `showcase` and `dashboard` lint output for those devices.
- **Cause.** `wfb/catalog.py:~208-230`. `weather_current` / `weather_daily`
  (and any other `Toybox.Weather` reader) set `requires=(...)` but not
  `requires_module="Weather"`. `wfb/availability.py` checks
  `requires_module` before `requires`, so the whole-module gap is
  misreported as a missing function.
- **Fix.** Add `requires_module="Weather"` to every `Toybox.Weather` reader.
  Check the generated `has :Weather` guard compiles on `fenix5`.
- **Test.** An availability test: `fenix5` plus a weather reader gives a
  module gap, not a function gap. A lint test: warning, not error. The
  existing `fenix5` Weather positive-gap test in `test_availability.py` is
  the neighbour to extend.

### 3. `round` disagrees between host and device

- **Symptom.** The host uses Python `round` (half to even). The SDK says
  `Math.round` rounds ">= .5 up" (`$CIQ_SDK/doc/Toybox/Math.html`).
  `round(2.5)` **constant-folds to `2` in generated code**; the watch would
  compute `3`. The preview of `round(battery)` at 72.5 shows 72; the watch
  shows 73.
- **Cause.** `wfb/expr.py:197`, the `"round"` row's host lambda
  `int(round(a[0]))`.
- **Fix.** Use `math.floor(x + 0.5)`, and confirm negative behaviour first.
  **UNVERIFIED:** `Math.round(-2.5)` on device. Write a probe under
  `docs/research/probes/` (compile and run the result through `monkeyc` + a
  unit test, or at least compile-check), and record the answer in
  `docs/lore/monkeyc.md`.
- **Test.** Fold `round(2.5)` → `3`, and `evaluate` at 72.5 → 73.

### 4. `percent`, `clamp` and `%` disagree between host and device

- **`percent`.** Host `wfb/expr.py:189` `_percent` is `100*a/b`, unclamped,
  and `None` when `b == 0`. Device `runtime-lib/WfbMath.mc:37` returns
  `0.0` when goal ≤ 0 and clamps to 0..100. Steps 12000 / goal 10000: the
  preview shows 120, the watch 100. A goal of 0: the preview treats the
  value as absent (placeholder), the watch shows 0. Constant
  `percent(150, 100)` folds to `150.0`. **Fix:** port `WfbMath.percent`
  exactly.
- **`clamp`.** Host `max(lo, min(v, hi))` returns `lo` when `lo > hi`.
  `WfbMath.clamp` (`:22`) checks `< lo` first, then `> hi`. **Fix:** port that
  order exactly.
- **`%`.** Host `operator.mod` is floor modulo (`-7 % 3 == 2`). Monkey C
  probably truncates (`-1`). **UNVERIFIED**; probe alongside item 3. Also
  unverified: whether Monkey C accepts `%` on Float, which `expr.check`
  currently allows.
- **Test.** One case per divergence, host evaluation and constant folding
  both.

### 5. `aod:` keys inherited from a group skip the "not supported" errors

- **Symptom.** The builder refuses `aod: {font}` on a pattern's or
  complication slot's own `aod:`, `aod: {filled}` on a polygon, and
  `aod: {format}` on a literal text. But the same keys set on a **group**
  are inherited silently and then dropped by codegen. A group with
  `aod: {font: FONT_TINY, filled: false, format: "{:%H}"}` around a slot, a
  polygon, a literal text and a pattern validates "ok -- 1 note".
- **Cause.** The per-kind checks live in `Builder._build_aod_authored`
  (`wfb/ir/builder.py:2054`, table `_AOD_FONT_UNSUPPORTED` at `:2048`), which
  only sees the element's *own* block. Inheritance happens later, in
  `_resolve_aod` (`:2150`).
- **Fix.** Run the per-kind checks on each element's **resolved** override
  inside `_resolve_aod`, where a group's keys have already reached the
  element. Keep the parser-time check only if its message is better, and
  don't report twice (one error, not N). Report the error on the element,
  with a note pointing at the group that set the key.
- **Test.** The scratch design above → 4 errors. Also drive each error red
  individually.
- **Docs.** `docs/guide/always-on-display.md` and `docs/limitations.md` §2
  (the "friendly build errors" list already names these three).

### 6. Colour-user lookups miss `outline.color` and `aod: {color}`

- **Symptom.** `palette: {ring: "#123456"}` used only as
  `outline: {color: palette.ring}` on a text element gives a `palette-dither`
  warning saying no element uses it "exactly", and it cannot be suppressed
  on the element that does. The same gap affects `config-unsupported` for
  `config.colors.*`. Patterns don't have it, because `PatternElement.colors`
  includes part outlines.
- **Cause.** `wfb/lint.py:414` `_users_of` reads only
  `color`/`track_color`/`icon_color`, plus `.colors` for hands and patterns.
- **Fix now.** Include `Text.outline.color` and `element.aod.color` (and
  every other AOD colour key) in `_users_of`.
- **Fix properly.** Plan 19 step A2 (`Element.color_roles()`) makes this
  impossible to miss. If A2 is scheduled soon, fold this item into it.
- **Test.** The palette case above: the warning names the text element and
  its `lint: allow` suppresses it.

### 7. `_backdrop` ignores layouts and modes

- **Symptom.** `layouts:` `day` (white full-screen rectangle) and `night`
  (black one). Night-layout white text is contrast-checked against white:
  a false warning. Night-layout dark text passes when it shouldn't. A
  `modes: [low_power]` background has the same effect on active elements.
- **Cause.** `wfb/lint.py:1099` `_backdrop` takes the first full-screen solid
  shape for the whole face.
- **Fix.** Compute the backdrop per (mode, layout): the last full-screen
  solid shape drawn before the element, in draw order, that can be drawn
  together with it (`wfb.ir.never_together`, same mode). Shared content
  (layout `None`) is a candidate for every layout.
- **Test.** The day/night case, both directions (false positive and missed
  warning).
- **Related gap (optional, same item).** `check_contrast` never checks a
  progress `track_color` or a slot `icon_color`.

### 8. `wfb preview --fonts DIR` measures with one font, draws with another

- **Symptom.** `--fonts` reaches only `PreviewOptions.fonts_root`
  (`wfb/cli.py:525`). Layout and lint (`fallback.measure`, `line_height`,
  `ascent`), the complication-slot measurement in `preview._complication_slot`,
  and `Device.system_fonts`' `_locate_garmin_outline_font` all use the
  default root. So boxes are sized from the stand-in and drawn with Garmin's
  face, and fenix 9 devices still get no metrics even when `--fonts` points
  at the right files.
- **Fix.** Thread a `fonts_root` through `build.resolve_all` → `layout.resolve`
  → `fallback` → `devices`. The cleanest shape is a font-root context object
  owned by the `DeviceDatabase`, rather than one more parameter per call.
- **Test.** Point `--fonts` at a directory whose face has different advances
  than the stand-in, and assert layout uses them.

### 9. Minor batch

- `curve: radial` radius on a standalone `text` is resolved with `_len`
  (`wfb/layout.py:1162`), so a sub-pixel radius skips the
  `sub-pixel-length` lint. The pattern-part equivalent uses `_hand_extent`
  (`:1553`). Use `_extent(..., what="curve.radius")`.
- `validate._check_pattern_frame` reuses `_HAND_UNIT_REFUSALS`
  (`wfb/validate.py:329`), so pattern parts get "a hand frame has no parent
  box…". Give patterns their own wording.
- `series.unavailable_reason` (`wfb/series.py:279`) splits only on `.`, but
  its docstring promises `_` too (`sensor_pressure`). Split on both.
- `wfb new --template ../x` builds `TEMPLATE_DIR / f"{args.template}.yaml"`
  (`wfb/cli.py:762`) with no check. Restrict it to the known template names
  (argparse `choices=`).
- `complications.py:~142-154` types ALTITUDE, CURRENT_TEMPERATURE and others
  as `Float` on the assumption that every target is above API 5.1.0. Scope is
  136 devices now, and between 4.2.0 and 5.0/5.1 they are `Number`. Needs a
  per-device type, or `Numeric`. Check `<id>.api.debug.xml` before choosing.
- `availability.Guards.any` (`wfb/availability.py:339`) is used only by
  tests, ignores `amoled_target`/`burn_in_field_guarded`/`display_mode_guarded`,
  and its docstring is wrong. Fix it or delete it.
- `WfbTime.mc` is copied for about 9 examples whose code never calls
  `WfbTime`, and `examples/features/sun/bar.yaml` gets `WfbArc.mc` with no
  `WfbArc.` call. Harmless, since `monkeyc` strips it, but it shows
  `wfb/emit/project.py::_barrel_for` has drifted from codegen. The proper fix
  is plan 19 step A3; if A3 is not scheduled, tighten the `WfbTime` rule to
  the codes that actually call the helper.
