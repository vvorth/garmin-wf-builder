# docs/plans/

Proposals written but not yet built. Each file carries its status at the
top and records the user's decisions as they are made. **A plan is deleted
once every slice has shipped**: what was built is then described by the
guide, lore and `docs/limitations.md` in their own words, never by pointing
back here.

## Open

| Plan | Status |
|---|---|
| [34 a curved slot](34-curved-slot.md): `rotate:` and `slot:` on `type: icon`, `curve:` on `type: data`, a group's `on_hold:` following its slot | in progress; slices 1–5 done, slice 6 built and not yet verified on a watch, D1–D8 decided |

## Built and deleted

ADRs and research still cite these by number (`plan 02 §12.4`). To read one
as built, `git show` it from the commit before it was deleted; each plan
records its own slices and decisions. Its commits are
`git log --grep "plan NN"`.

| Plans | Read with |
|---|---|
| 01–03 | `git show a645d64:docs/plans/02-style-layouts.md` (`01-background-color.md` and `03-complication-slot-icons.md` likewise) |
| 04 analog hands | `git show 93ef6d7:docs/plans/04-analog-hands.md` (§13 is what shipped) |
| 05 patterns | `git show f9115ca:docs/plans/05-patterns.md` |
| 06 pattern text, group align | `git show f5155d7:docs/plans/06-pattern-text-and-group-align.md` |
| 07 align everywhere | `git show b534b8a:docs/plans/07-align-everywhere.md` |
| 09 system fonts, 10 `.cft` | `git show 7e8e11d:docs/plans/09-system-font-metrics.md`, `…/10-cft-bitmap-fonts.md` |
| 11 vector fonts, `curve:` | `git show 35217d1:docs/plans/11-vector-text.md` |
| 12 preview font fidelity | `git show 28638ca:docs/plans/12-preview-font-fidelity.md` (§1 is the measured diagnosis: read it before re-investigating "the preview's typeface is wrong") |
| 13 showcase `roman` layout | `git show 28638ca:docs/plans/13-showcase-roman-layout.md` (built with two departures, recorded in `examples/showcase/face.yaml`'s comments) |
| 14 `aod:`, always-on display | `git show 2892263:docs/plans/14-aod.md` |
| 15 `outline:`, the stamped ring | `git show e31117b:docs/plans/15-text-outline.md` |
| 16 AOD pixel mask | `git show 965518a:docs/plans/16-aod-pixel-mask.md` |
| 17 derived system-font metrics | `git show f03d413:docs/plans/17-derived-system-font-metrics.md` |
| 18 review bug fixes | `git show 45c40b7:docs/plans/18-review-bug-fixes.md` |
| 19 architecture refactor | `git show d325e77:docs/plans/19-architecture-refactor.md` |
| 20 screen shapes | `git show fb290f9:docs/plans/20-screen-shapes.md` |
| 21 `settings:` | `git show 0e741d9:docs/plans/21-phone-settings.md` (removed the same day in favour of the `config:` settings menu) |
| 22 format 2 | `git show 9480d08:docs/plans/22-format-2.md` (§5 is the reserved vocabulary, each still to be planned) |
| 23 `outline:` everywhere | `git show 96462ed:docs/plans/23-outline-everything.md` |
| 25 gauges on a slot, `max: auto` | `git show b1e3a23:docs/plans/25-slot-gauges.md` (**§6 is the deferred zone-colouring proposal**, to start a follow-up plan from) |
| 26 the single draw program | `git show 270c595:docs/plans/26-draw-program.md` |
| 27 `wfb studio`, the editor | `git show cf4b310:docs/plans/27-studio.md` |
| 28 a browser renderer for `wfb studio` | `git show 2ab22c4:docs/plans/28-browser-renderer.md` |
| 29 live centred boxes and gauge arcs | `git show 0b280bf:docs/plans/29-live-centred-boxes-and-gauges.md` (options A–C and C1–C4 for centred boxes are kept for a later plan) |
| 30 the editor's gaps | `git show 07446be:docs/plans/30-editor-gaps.md` |
| 31 TypeScript migration | `git show 7aea248:docs/plans/31-typescript-migration.md` (commits `git log --grep "port slice"`; slice 10's open shape rules are in `docs/research/probes/garmin-raster/README.md`) |
| 32 GUIv2 | `git show 19ae010:docs/plans/32-gui-v2.md` (commits `git log --grep "plan 32"`; built from `docs/research/33-gui-v2.md`) |
| 33 a full-featured editor | `git show 6ec6c61:docs/plans/33-full-editor.md` (commits `git log --grep "plan 33"` and the slice headings' hashes; built from `docs/research/34-full-editor.md`; ten format changes F1–F10, the editor rebuilt over its engine, the browser suite and the fixture device) |
| 35 astronomy sources | `git show 59c1508:docs/plans/35-astronomy-sources.md` (commits `git log --grep "plan 35"` and 8bf069f, 641aa3c, f081cee, 1672d94, 59c1508: `date.month_number`, `time.utc_offset`, the catalogue's `call:`, `position.*` and `astro.*` in `WfbAstro.mc` with a host twin, built from `docs/research/39-position-and-astronomy.md`; the Solaria face rebuilt on them) |
| 36 icon rules | `git show 8b0e778:docs/plans/36-icon-rules.md` (commits `git log --grep "plan 36"`: one `steps`/`table` rule per source in `icons.json` read by the compiler, the preview, the generated `IconGlyphs.<rule>Icon` choosers and the editor; `absent: hide | {icon:}` on `type: icon`; alarm, do-not-disturb, phone and moon-phase rules; `examples/features/status/`; the icon picker's "follows data" tab) |
| 37 phone-side settings | `git show d9a6b9e:docs/plans/37-phone-settings.md` (commits `git log --grep "plan 37"`: `settings.xml`/`properties.xml` per settings-menu device, derived from `config:`, shared strings, `onSettingsChanged`, the `wfb export` phone-settings line; the §5 phone checks are still the user's) |
| 38 element names unique among siblings | `git show 21144b7:docs/plans/38-scoped-element-ids.md` (commits `git log --grep "plan 38"`: an element's id is its key qualified by its groups (`top.label`), generated symbols derive from it, the editor is keyed on it and checks a name among its siblings only; `ts/src/element_ids.ts`) |
| 39 a fleet-wide Store export | `git show db039df:docs/plans/39-fleet-export.md` (commits `git log --grep "plan 39"`: `fallback:` on a `face:` font, baked per device where no listed face is published and drawn upright, with `font-fallback` and the `examples/features/font-fallback/` example; `wfb export --all-devices` dropping each device whose errors are all its own lack, through `Diagnostic.devices` and `dropUnsupported`, reported by `device-dropped`, the `dropped` line and `export-info.json`) |
| 40 `fallback: auto` | `git show 959b539:docs/plans/40-auto-fallback.md` (commits `git log --grep "plan 40"`: every device-resident scalable face mapped to a free, licensed stand-in in `ts/src/data/font-registry.json`, chosen by look where the face is proprietary and prefetched whole on setup, built from `docs/research/40-vector-face-stand-ins.md`; `fallback: auto` baking that stand-in, named with its match and licence in `font-fallback`) |
| 41 tabular digits | `git show 34536bb:docs/plans/41-tabular-digits.md` (commits `git log --grep "plan 41"` and `git log --grep "Plan 41"`: `tabular_digits:` on a baked font, on by default for a `fallback: auto` whose registry key has the flag (Bionic's Rajdhani stand-ins), and the same cell in the stand-in measuring and preview, which brought the fenix 8 `FONT_NUMBER_*` width probe from 296 px to 150 px of total error without Garmin's files) |
| 42 your own glyphs, `icons:` | `git show 1fcfcb8:docs/plans/42-icon-glyph-sets.md` (commits `git log --grep "plan 42"`: face-owned icon rules and a Float threshold chooser; `icons:` on `icon: {for:}` and on a slot choice, keyed by band start, `off`/`on`, or built-in glyph name as an overlay; `absent:` on a slot choice; the editor's state editor; `wfb sources` keys) |
