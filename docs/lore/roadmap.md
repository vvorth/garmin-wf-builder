# Roadmap: what exists, what was removed, what is missing

`docs/limitations.md` §2 is the **authoritative** list of what is missing.
This file is a turn-one index: one entry per shipped feature, pointing at
the guide chapter that documents it, plus the few facts recorded nowhere
else. If this file and `limitations.md` disagree, `limitations.md` is
right.

## Shipped

Verified means a warning-free real `monkeyc` build on the three
verification devices plus `wfb preview`. Nothing config-, hands-, pattern-
or AOD-related has been observed on a watch or in the simulator.

- **All nine element types** — `group`, `text`, `icon`,
  `complication_slot`, `shape` (seven shapes), `progress`, `graph`,
  `hands`, `pattern` (`radial`, `linear`, `grid`). `hands` and `pattern`
  are the two places the watch does layout arithmetic (`WfbHands.mc`,
  `WfbGeom.mc`); baked pattern copies measured ~30× the memory
  (`docs/research/probes/pattern-cost/`). `docs/guide/elements.md`,
  `shapes.md`, `analog-hands.md`, `patterns.md`.
- **Placement and drawing** — `align:`/`vertical_align:` everywhere,
  `static:`, `antialias:`, `visible:`, `monospace:`, `min_1px:`, the
  mapping form of `elements:`. `docs/guide/placement.md`.
- **Data** — the full source catalogue including all 42
  `COMPLICATION_TYPE_*` values; every source is a plain per-frame pull.
  `units: auto|metric|statute` on a `text` element (`Source.quantity`,
  `wfb/conversion.py`) and duration formats on a number of seconds
  (`wfb.formatting.DURATION_CODES`, `WfbTime.durationPart`).
  `docs/guide/data.md`.
- **Interactivity** — `on_hold:` (including `on_hold: auto`) on every
  element; `Complications.exitTo`. `docs/guide/modes-and-interaction.md`.
- **Configuration: all four native axes** — `accent_color`, `data_color`,
  Styles with `color_scheme:` and `layouts:` (form A), the Data axis as
  `complication_slot`. `docs/guide/configuration.md`,
  `styles-and-layouts.md`.
- **The `config:` settings menu** — on a watch without the native editor
  but with `getSettingsView` (fr955), the `config:` axes as one list per
  axis (`wfb.emit.monkeyc.config_menu`); stored as `Application.Properties`
  indices; `choices: any` offers the palette or every complication type
  the device has (per-device `Layout` arrays). `config-unsupported` fires
  only with neither (`fenix5`/`fenix5x`). The mechanism was seen working on
  `fr955`; the `config:` menu itself not yet. `docs/guide/configuration.md`.
- **Per-device API gating** — manifest floor 3.1.0, a device below it is a
  friendly error (`wfb.build.select_devices`); complication, weather and
  field touches are `has`-guarded (`wfb/availability.py`); lints
  `api-gated` and `api-gated-unguardable`. UNVERIFIED on a real pre-4.2.0
  device: that a guarded reference to an absent module is harmless at load
  time.
- **Fonts** — system fonts measured and previewed from the device's own
  files, `.cft` included (`docs/research/10-system-fonts.md`); vector fonts
  (`face:`) and `curve:` on `text` and pattern text parts, 44 of 136
  devices; `outline:` (the stamped ring) with lint
  `text-outline-interior`. `docs/guide/fonts.md`, `text.md`.
- **Progress styles** — `arc`, `bar`, `needle` (a hand's `parts:` turned
  to `start_angle + fraction × sweep`; `Builder.build_hand_part`),
  `segments` and `scale` (`wfb.lint.check_progress_segments`).
  `docs/guide/progress-and-graphs.md`.
- **Always-on display** — `aod:` overrides resolved element > group >
  face default, restyled by inline ternaries; `dim:`; the pixel `mask:`
  (on by default, +279 B on `examples/features/aod/`); the
  `getDisplayMode` early exit; lints `aod-unreachable`, `aod-empty`,
  `aod-burn-in`; `wfb preview --aod/--minute/--heatmap`. An all-MIP build
  is byte-identical with or without `aod:`. The burn-in lint costs about
  40–70 ms per AMOLED target (two full-frame renders plus one per shown
  element). `jitter:` was built and removed on 2026-09-23 in favour of the
  mask. `docs/guide/always-on-display.md`, `docs/research/11`, `15`.

## Removed outright (no shim; the old spelling is an ordinary error)

- `type: carousel`.
- `on_tap:`, now `on_hold:`. `WatchFaceDelegate.onTap` never fires on a live
  face.
- A font `size:` given as a bare number, and `scale:`. Lengths are always
  `%r`/`px`.
- A pasted raw character in `icon:`. Use a catalogue name or
  `glyph: "U+XXXX"`.
- Refresh tiers (`WfbCache.mc`, `catalog.Tier`).
- `config: colors:`. Use `config: style:`.
- `vertical_align: baseline`, renamed `bottom`.
- `modes: [always_on]`. Use `aod:` (plan 14 D3) -- the schema error names
  the replacement.

## Not implemented

See `docs/limitations.md` §2 for the full table and the ADR or plan that
specifies each item.

1. `image` elements and the `raw` escape hatch (ADR 0007). Both give a
   friendly error.
2. Per-device `overrides`: writing one is a build error. Plan 20 slice 4
   proposes the geometry-only subset, with `shape:` selectors.
3. Ticks drawn by a `style: scale` progress itself (a radial `pattern`
   does them today).
4. `units:` on an expression or a `complication_slot`.
5. **Phone-side settings and `wfb package`.** Phone editing needs a Store
   install, which needs `wfb package` (research 17 §2); wearer settings
   beyond `config:` were decided against, and there is no `.SET` writer
   (ADR 0006 tenth and eleventh amendments). The
   2026-09-11 WIP is pinned on `wip/phone-settings`. It is design reference
   only: it predates the builder, emitter and kinds refactors. Do not
   resume it without asking the user.
6. Catalogue generation from the SDK (ADR 0005 §1).
7. `catalog.Source.requires` is set on no source. ADR 0008's check 2 is
   otherwise built (`api-gated`: modules, fields, complication types); the
   hook is read by `wfb.availability.source_unavailable` for a future
   source whose read needs an extra function.
8. **The GUI** (ADR 0002). Unit round-tripping and schema churn make it
   premature (`docs/research/06-authoring-ergonomics.md` §4). If it is ever
   built, build it as a thin client over `wfb/preview.py`, not a second
   renderer.
9. CI does not exist. `mypy --strict` is clean over `wfb/` and runs as
   its own test set (`pytest -m typecheck`, ADR 0001 amendment), by hand;
   its baseline (`tests/mypy-baseline.txt`) is empty.
10. `wfb install`, `package`, `migrate`.
11. A `pattern`'s or `complication_slot`'s own `aod: {font: ...}` override,
    any `font:` override naming a `face:` (vector) font, and
    `aod: {filled: ...}` on `shape: polygon` (plan 14 §4.3, slice 2 built
    every other override key and a `text` element's baked-font override)
    -- all three are friendly build errors, whether the element writes
    the key or inherits it from a group (`Builder.aod_refusal`), never a
    silent no-op.
12. **Non-round screens** (plan 20, research 16): rectangles are designed
    for but never run against a real device; semi-octagon (Instinct) and
    semi-round are "not checked"; 2-colour panels have no palette rule.

## Architecture options not taken

- **A single draw program** (plan 19 A7): lower each element once into a
  small display list of drawing steps that the preview evaluates and the
  emitter prints as Monkey C, removing the rules preview and codegen still
  implement twice (plan 19 §2 P2 lists them). Not built, and not
  recommended unless many more drawing features are coming: it rewrites
  most of `wfb/preview.py` and `wfb/emit/monkeyc/`, while A1's shared
  definitions plus parity tests already cover most of that risk. The
  user has not decided; read the analysis with
  `git show d325e77:docs/plans/19-architecture-refactor.md`, and write a
  new plan before starting it.
