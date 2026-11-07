# Plan 41 — tabular digits: for a baked font, and for the stand-ins of a face that has them

**Status:** in progress (2026-11-07). Two slices built in parallel by two
agents, merged by the orchestrator. Decisions D1–D8 are made.

## 1. The problem

Garmin's Bionic faces are Rajdhani with the ten digits (and `+`) redrawn to
one tabular advance (research 40 §2.1). The registry stands Bionic in with
plain Rajdhani, whose digits are proportional, so:

- a `fallback: auto` sheet for a Bionic face draws `11:11` a quarter narrower
  than `00:00`, and a clock in it shifts as the digits change (the user's
  simulator captures of 2026-11-07, `fr255`, against the real face on
  `fenix8solar47mm`);
- a build without Garmin's font files measures Bionic text (the fenix 8
  `FONT_NUMBER_*` roles, and a `face: BionicSemiBold` text) with Rajdhani's
  proportional advances, which is where research 40 §2.1's 296 px total
  width error on the probe's 16 readings comes from;
- the preview without Garmin's files draws the same proportional digits.

A simulated tabular Rajdhani (digits widened to the widest digit's advance,
each outline centred, everything else untouched) reproduced the real face's
layout on the simulator: equal widths, a narrow colon. `monospace: true` does
not: it widens the colon too.

## 2. Decisions

- **D1. The bake option.** `tabular_digits: true` on a baked font (`source:`
  entries, inline fonts, and a `fallback:` mapping with `source:` a path or
  `auto`): the ten digits `0`–`9` share one advance, the widest digit's, with
  each digit's outline centred in it; every other glyph keeps its own advance.
  Default `false`. Beside `monospace: true` it is a build error (every glyph
  already shares one cell), in the style of `align:` without `monospace:`.
  Refused on a `face:` entry like the other baking keys. The schema
  (normative) carries the key with its promise; `docs/guide/fonts.md` gets a
  section beside `monospace:`.
- **D2. The registry flag.** `fonts[key].tabular_digits: true` marks a
  stand-in whose face has tabular digits: `rajdhani-semibold`,
  `rajdhani-bold`, `rajdhani-medium` (Bionic). Set in this plan's first
  commit, before either slice starts.
- **D3. `auto` applies it.** A `fallback: auto` (or `source: auto`) whose
  resolved key carries the flag bakes with tabular digits unless the author
  writes `tabular_digits: false` beside it. The `font-fallback` note says
  "digits tabular, as the face's are". A path fallback or a `source:` font
  takes only what the author writes.
- **D4. Measuring and previewing through a flagged key.** Wherever a system
  font or a vector face is measured or drawn from a registry stand-in
  (`SystemFace`, used by layout's width estimates and by `wfb preview` when
  Garmin's own file is not installed, and the `WFB_NO_GARMIN_FONTS=1`
  goldens), a key with the flag gives its digits the widest digit's advance
  and draws each centred in that cell. Garmin's own file, when installed,
  is used as is: it already has the real widths. This brings the fenix 8
  `FONT_NUMBER_*` width estimates back toward the measured ones; the goldens
  that draw Bionic move and the commit says by how much the probe's total
  error moved (research 40 §2.1's `probe-widths.ts`).
- **D5. One definition of the cell.** Both slices compute the tabular advance
  the same way, from the font's own `hmtx` at the em in use: the maximum
  over `0`–`9`, each digit offset by half the difference, rounded as the path
  already rounds. Slice T exports the helper from `ts/src/fonts/bake.ts`;
  slice M reads the same rule in `ts/src/fonts/fallback.ts` and the two tests
  assert the same `11:11`/`00:00` equality.
- **D6. Tests must contrast.** Open Sans (the fixture TTF) already has
  tabular figures, so it cannot show the option working. Tests use Rajdhani
  SemiBold from the installed registry (`ts/assets/system-fonts/`), whose
  `1` is 327 units against the `0`'s 528: `Fri 11:11` and `Wed 00:00` measure
  apart without the option and equal with it, the colon's advance unchanged.
- **D7. Sizing, already fixed.** A `face:` font's fallback is baked to the
  face's line height (commit e5fd1f1); this plan changes advances only.
- **D8. Example.** `examples/features/font-fallback/face.yaml`'s `auto` font
  switches to a Bionic face with a clock reading, so the tabular sheet is on
  a device of its own (`fr255`) and in the screenshots.

## 3. Slices

### Slice T — the bake option and `auto`

Files: `ts/src/fonts/bake.ts` (`BakeOptions.tabular_digits`, the shared
cell helper), `ts/src/fonts/bmfont.ts` if the sheet needs a field,
`ts/src/ir/model.ts` (`FontSpec.tabular_digits`), `ts/src/ir/builder/fonts.ts`,
`ts/src/emit/resources.ts` (`bakeFonts`, the registry flag through `standIn`),
`ts/src/fonts/files.ts` (`StandIn.tabular_digits`), `ts/src/lint.ts` (the
note), `schema/`, `ts/src/studio/inspect.ts` if the font form lists keys by
hand, tests (`ts/test/font-fallback.test.ts`, `bake.test.ts`), the example,
`docs/guide/fonts.md`, `docs/limitations.md`, `docs/lore/roadmap.md`.

### Slice M — measuring and previewing through a flagged key

Files: `ts/src/fonts/fallback.ts` (`SystemFace.advances`, the glyph offset),
`ts/src/preview.ts` (drawing each digit centred in its cell), tests
(`ts/test/layout.test.ts` or a new file; the research probe's widths),
goldens, `docs/research/40-vector-face-stand-ins.md` §2.1 (the measured
error after), `docs/lore/codegen.md` or `docs/limitations.md` where they
describe system-font width estimates, `docs/research/10-system-fonts.md`
if it states the Bionic substitute's width error.

### Close

Merge both, run the fast, slow, browser suites and CI's own step, re-render
the comparison on `fr255` against the real face, delete this file and add
its row to `docs/plans/README.md`, merge to `main`.
