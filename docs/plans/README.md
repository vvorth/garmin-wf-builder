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
| 19 architecture refactor | `git show d325e77:docs/plans/19-architecture-refactor.md` (§1 "Done" lists A0–A6 and the small items with their commits and how each was proven output-identical; §2 P2 and §3 A7 are the one option not taken then; the user decided on 2026-10-01 to build A7, research 27 §8) |
| 22 format 2 | `git show 9480d08:docs/plans/22-format-2.md` (§1–§2 are the decisions F1–F7, Q1–Q5 and names N1–N18; §3.4 the full v1 → v2 table, also `docs/guide/format-2-migration.md`; §5 the reserved vocabulary, each still to be planned; §6 records every slice: plan `6cfb9b6`, slice 0 `1189e94` (the baseline snapshot), slice 1 `d0256b9` (`wfb migrate`), slice 2 `c97710d` (both formats compiled), slice 3 `4c657a7` (the switch-over), slice 4 `9480d08` (an absent gauge keeps its track), slice 5 the tidy commit that deleted it) |
| 25 gauges on a slot, `max: auto` | `git show b1e3a23:docs/plans/25-slot-gauges.md` (§1 is D1–D8; §3 the slices: slice 1 `71859a4` (counts read whole, "10.0K"), slice 2 `0acb5a2` (the scale table), slice 3 `38d2c1c` (`slot:` on a gauge), slice 4 `3c35b10` (the editor sees every element of a slot), slice 5 `b1e3a23` (`max: auto`), slice 6 the example/screenshot/doc-sweep commit that deleted it; **§6 is the deferred zone-colouring proposal**, to start a follow-up plan from; research 24 is the evidence) |
| 23 `outline:` everywhere | `git show 96462ed:docs/plans/23-outline-everything.md` (§1 is D1–D5, §3 the slices: slice 1 `badb527` (shapes, icons), slice 2 `fde32fa` (hands), slice 3 `88f79ae` (groups), slice 4 `96462ed` (patterns, gauges), slice 5 the example/screenshot/doc-sweep commit that deleted it; research 19 is the measurement record) |
| 20 screen shapes | `git show fb290f9:docs/plans/20-screen-shapes.md` (§2 is the slices: 1 rectangles exercised, 2 the skin mask, 3 two-colour panels, 5 `anchor: subscreen`; slice 4, `overrides:` with D1 as recommended, is the commit that deleted it; research 16 is the evidence) |
| 26 the single draw program | `git show 270c595:docs/plans/26-draw-program.md` (§1 is P1–P4; §3 records every slice with its proof: slice 0 `0a699f0` (the core), slice 1 `acf16ad`/`9770f65` (`shape`), slice 2 `27b3a3e` (`text`), slice 3 `dd1d280` (layers and the JSON form), slice 4 `a08431a` (`icon`), slice 5 `84a3e7c` (gauges), slice 6 `b311526` (`pattern`), slice 7 `8819a45` (`hands`), slice 8 `93cc476` (`graph`), slice 9 `d84987a` (`data`), slice 10 `270c595` (the guards, Q1's grown ring, the close-out), and the commit that deleted it; research 27 is the case, research 28 §7 Q1's answer) |
| 27 `wfb studio`, the editor | `git show cf4b310:docs/plans/27-studio.md` (§1 is D1–D3, E2/E4, G1–G6 and the user's re-scope S1–S7, which superseded G4's working copy and E2's geometry-only editor; §3 records every slice with its measurements: slice 0 `4cf31ce` (the patch engine), the re-scope `b29de9d`, slice 1 `86bf2d0` (server, bundles, viewer), slice 2 `f7503e4` (history), slice 3 `dcfc17d` (inspector, Face panel), slice 4 `7adc83c` (canvas drags), slice 5 `3934629` (structure), slice 6 `cf4b310` (YAML tab), slice 7 the close-out that deleted it) |
| 28 a browser renderer for `wfb studio` | `git show 2ab22c4:docs/plans/28-browser-renderer.md` (§1 is R1–R4 and B1–B5; §3 records every slice with its proof and measurements: slice 0 `fa3e649` (Pillow's primitives in JavaScript), slice 1 `f21db57` (glyph tiles and placed text), slice 2 `c23d117` (layers drawn in the browser), slice 3 `2ab22c4` (live handles, and why only 63 of 304), slice 4 the close-out that deleted it; research 29 is the case) |
| 30 the editor's gaps | `git show 07446be:docs/plans/30-editor-gaps.md` (§1 is the decisions K1–K5, C1–C2, H1–H2, L1–L3, S1–S3 and the rule R1; §2 the slices: slice 1 `a274f34` (the colour table, the picker, the colour axes), slice 2 `e99acdf` (colour schemes), slice 3 `8dd89c9` (hand sets), slice 4 `c9b1873` (slots), slice 5 `07446be` (faces per browser and the `Host` check), and the close-out that deleted it. Departures: Schemes stayed its own section; + Scheme on a face with layouts adds a style per layout without asking; + Role starts white; the slot card has no "+ data element" (+ Slot adds one, Layers otherwise); type labels are the SDK constants' words, the SDK naming none; research 30 is the case) |
| 29 live centred boxes and gauge arcs | `git show 0b280bf:docs/plans/29-live-centred-boxes-and-gauges.md` (§1: E, plain arc gauges, built; D for centred boxes, which keep the outline, with A–C and C1–C4 kept as the options considered for a later plan; built in one commit `0b280bf`: 107 of 304 handles live; research 29 is the case) |
