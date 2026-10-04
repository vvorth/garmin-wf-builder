# docs/plans/

Proposals written but not yet built. Each file carries its status at the
top and records the user's decisions as they are made. **A plan is deleted
once every slice has shipped**: what was built is then described by the
guide, lore and `docs/limitations.md` in their own words, never by pointing
back here.

## Open

None.

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
