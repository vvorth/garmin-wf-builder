# docs/plans/

Proposals written but not yet built. Each file carries its status at the
top and records the user's decisions as they are made. **A plan is deleted
once every slice has shipped**: what was built is then described by the
guide, lore and `docs/limitations.md` in their own words, never by pointing
back here.

## Open

| Plan | Status |
|---|---|
| [`20-screen-shapes.md`](20-screen-shapes.md) | rectangular and semi-octagon screens: all built but slice 4 (`overrides:`), which awaits decision D1 and is to be rebased onto format 2's key names (plan 22 F7) |
| [`25-slot-gauges.md`](25-slot-gauges.md) | gauges on a `config: slots:` slot, scaled per picked metric, and `max: auto` on a fixed complication (research 24); slices 1–2 done; zone colouring deferred (§6) |

## Built and deleted

ADRs and research still cite these by number (`plan 02 §12.4`). To read one
as built:

| Plans | Read with |
|---|---|
| 01–03 | `git show a645d64:docs/plans/02-style-layouts.md` (`01-background-color.md` and `03-complication-slot-icons.md` likewise) |
| 04 analog hands | `git show 93ef6d7:docs/plans/04-analog-hands.md` (§13 is what shipped) |
| 05 patterns | `git show f9115ca:docs/plans/05-patterns.md` |
| 06 pattern text, group align | `git show f5155d7:docs/plans/06-pattern-text-and-group-align.md` |
| 07 align everywhere | `git show b534b8a:docs/plans/07-align-everywhere.md` |
| 09 system fonts, 10 `.cft` | `git show 7e8e11d:docs/plans/09-system-font-metrics.md`, `…/10-cft-bitmap-fonts.md` |
| 11 vector fonts, `curve:` | `git show 35217d1:docs/plans/11-vector-text.md` (§5 "Slices" is what shipped; slice 1 is `e744913`, slice 2 `35217d1`, slice 3 the example/screenshots) |
| 12 preview font fidelity | `git show 28638ca:docs/plans/12-preview-font-fidelity.md` (§1 is the measured diagnosis — read it before re-investigating "the preview's typeface is wrong"; slice 1 R1/R3 is `28638ca`, slice 2 R2 the commit after it) |
| 13 showcase `roman` layout | `git show 28638ca:docs/plans/13-showcase-roman-layout.md` (as proposed; built with two deliberate departures recorded in `examples/showcase/face.yaml`'s own comments — `skip: [2, 10]` because the shared registers sit on those spokes, and both apertures on `FONT_XTINY` so each is wider than tall) |
| 15 `outline:`, the stamped ring | `git show e31117b:docs/plans/15-text-outline.md` (§14 "Slices" is what shipped; slice 1 is `0cebdf0` (amended by `65b8f2a`), slice 2 `e31117b`, slice 3 the example/screenshots/doc-sweep, commit `9a5371f`) |
| 14 `aod:`, always-on display | `git show 2892263:docs/plans/14-aod.md` (§6 "Slices" is what shipped; slice 0 `02c375d`, slice 1 `1af607e`, slice 2 `b786723`, slice 3 `616b646`, slice 4 `65bca8a`, slice 5 `2892263`, slice 6 `1f8358e`, which deleted it; §7's decisions D1-D5 and §8's open questions live on in ADR 0006's 2026-09-23 amendment and research 11 §5/`docs/limitations.md` §3) |
| 16 AOD pixel mask | `git show 965518a:docs/plans/16-aod-pixel-mask.md` (§5 "Slices" is what shipped; plan `fd49cab`, slice 1 `3c2b40d`, slice 2 `965518a`, slice 3 the docs closeout that deleted it) |
| 17 derived system-font metrics | `git show f03d413:docs/plans/17-derived-system-font-metrics.md` (built as written in one commit, the one that deleted it; §2 is the 45/45 evidence, also in research 10 §3.1) |
| 18 review bug fixes | `git show 45c40b7:docs/plans/18-review-bug-fixes.md` (§1 lists items 1–9 with their commits; §2.1, Float complications converted with `.toFloat()`, is `45c40b7`; §2.2, `contrast` for a slot's `icon_color` but not a progress `track_color`, is the commit that deleted it) |
| 21 `settings:` | `git show 0e741d9:docs/plans/21-phone-settings.md` (§1 is D1–D3, §4 the slices; slices 1-4 are `3137c80`, `88eb824`, `0e741d9`, `b6aad60`. All of `settings:` was removed the same day in favour of the `config:` settings menu, ADR 0006's eleventh amendment; only the menu machinery lives on) |
| 19 architecture refactor | `git show d325e77:docs/plans/19-architecture-refactor.md` (§1 "Done" lists A0–A6 and the small items with their commits and how each was proven output-identical; §2 P2 and §3 A7 are the one option not taken, see `docs/lore/roadmap.md`) |
| 22 format 2 | `git show 9480d08:docs/plans/22-format-2.md` (§1–§2 are the decisions F1–F7, Q1–Q5 and names N1–N18; §3.4 the full v1 → v2 table, also `docs/guide/format-2-migration.md`; §5 the reserved vocabulary, each still to be planned; §6 records every slice: plan `6cfb9b6`, slice 0 `1189e94` (the baseline snapshot), slice 1 `d0256b9` (`wfb migrate`), slice 2 `c97710d` (both formats compiled), slice 3 `4c657a7` (the switch-over), slice 4 `9480d08` (an absent gauge keeps its track), slice 5 the tidy commit that deleted it) |
| 23 `outline:` everywhere | `git show 96462ed:docs/plans/23-outline-everything.md` (§1 is D1–D5, §3 the slices: slice 1 `badb527` (shapes, icons), slice 2 `fde32fa` (hands), slice 3 `88f79ae` (groups), slice 4 `96462ed` (patterns, gauges), slice 5 the example/screenshot/doc-sweep commit that deleted it; research 19 is the measurement record) |
