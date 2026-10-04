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

- **Format 2** — the only format the compiler reads, and the builder reads
  its keys as written; `wfb/lower.py` checks what the schema cannot.
  `docs/guide/design-file.md`.
- **Every element type** — `group`, `text`, `icon`, `data`, the six
  primitives (`rectangle`, `circle`, `ellipse`, `arc`, `polygon`, `line`),
  `gauge`, `graph`, `hands`, `pattern` (`radial`, `linear`, `grid`); nine
  internal kinds. `hands` and `pattern`
  are the two places the watch does layout arithmetic (`WfbHands.mc`,
  `WfbGeom.mc`); baked pattern copies measured ~30× the memory
  (`docs/research/probes/pattern-cost/`). `docs/guide/elements.md`,
  `shapes.md`, `analog-hands.md`, `patterns.md`.
- **Placement and drawing** — `align:` everywhere (nine anchor names and
  compass aliases), `static:` blocks, `antialias:`, `visible:`,
  `monospace:`, `min_1px:`. `docs/guide/placement.md`.
- **Data** — the full source catalogue including all 42
  `COMPLICATION_TYPE_*` values; every source is a plain per-frame pull.
  `text:` templates (`"{expr:spec}"`, several placeholders on a `text`
  element, `wfb.template.segments`, `Text.more`), `absent:`;
  `units: auto|metric|statute` on a `text` element (`Source.quantity`,
  `wfb/conversion.py`) and duration formats on a number of seconds
  (`wfb.formatting.DURATION_CODES`, `WfbTime.durationPart`).
  `docs/guide/data.md`.
- **Interactivity** — `on_hold:` (including `on_hold: auto`) on every
  element; `Complications.exitTo`. `docs/guide/modes-and-interaction.md`.
- **Configuration: all four native axes** — `accent_color`, `data_color`,
  Styles with `theme: schemes:` and `layouts:` (form A), the Data axis as
  `config: slots:` drawn by `type: data`; one `color.<name>` namespace for
  swatches and roles. `docs/guide/configuration.md`,
  `styles-and-layouts.md`.
- **A slot's reading per complication type** — times of day, durations,
  paces, rounded temperatures, hours, `K` counts and condition names,
  following the watch's units and clock; `unit:` adds each type's unit and
  `short:` keeps to seven characters; a weather slot's icon follows the
  condition (`wfb.complications.READING`, generated `SlotText.mc`,
  `runtime-lib/WfbReading.mc`). `docs/guide/configuration.md`.
- **The `config:` settings menu** — on a watch without the native editor
  but with `getSettingsView` (fr955), the `config:` axes as one list per
  axis (`wfb.emit.monkeyc.config_menu`), a data slot titled by its
  optional `label:`; stored as `Application.Properties`
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
- **`outline:` everywhere** (research 19) — a 1–3 px ring on
  shapes, icons, `hands` (each hand whole), `pattern` (each copy whole),
  `arc`/`bar`/`needle` gauges and `group` (the members' union): grown
  where one copy is exactly the dilation (filled circle, rectangle, a bar),
  stamped otherwise. `docs/guide/outlines.md`.
- **Gauge styles** — `arc`, `bar`, `needle` (a hand's `parts:` turned
  to `start_angle + fraction × sweep`; `Builder.build_hand_part`),
  `segments` and `scale` (`wfb.lint.check_progress_segments`); `absent:
  hide` keeps the track (`wfb.kinds.gauge.keeps_track`).
  `docs/guide/progress-and-graphs.md`.
- **Gauges on a slot, and `max: auto`** (research 24) — `slot:` on a gauge
  shows the wearer's pick against its own scale, and `max: auto` on a bare
  `complication.<type>` takes the same: `wfb.complications.SCALE` (0-100,
  the watch's goals, a day, the wearer's heart-rate zones and VO2 max row),
  generated into `SlotScale.mc` over `runtime-lib/WfbScale.mc` and
  `WfbProfileScale.mc`; a pick with no scale hides the gauge whole. The
  editor treats a slot as every element drawing it
  (`wfb.emit.monkeyc.common.editor_slots`). Zone colouring by a metric's
  own bands is not built. `docs/guide/progress-and-graphs.md`.
- **Always-on display** — `aod:` overrides resolved element > group >
  face default, restyled by inline ternaries; `dim:`; the pixel `mask:`
  (on by default, +279 B on `examples/features/aod/`); the
  `getDisplayMode` early exit; lints `aod-unreachable`, `aod-empty`,
  `aod-burn-in`; `wfb preview --aod/--minute/--heatmap`. An all-MIP build
  is byte-identical with or without `aod:`. The burn-in lint costs about
  40–70 ms per AMOLED target (two full-frame renders plus one per shown
  element). `jitter:` was built and removed on 2026-09-23 in favour of the
  mask. `docs/guide/always-on-display.md`, `docs/research/11`, `15`.
- **Per-device `overrides:`** (ADR 0004 §4) -- an element's `at:`,
  `size:`, `radius:` and `align:` patched per device id or `shape:<s>`,
  deep-merged (device over shape over the element), parsed in
  `ElementTree._build_overrides` into `Element.overrides` and applied per
  device by `Resolver.for_device`, so only `Layout.mc` changes; the
  selectors are checked by `lint.check_override_selectors` (an unknown
  device is an error, `override-unreachable` a warning).
  `docs/guide/placement.md`.
- **SDK version recorded** (ADR 0009 §4) -- the device reference records
  its SDK (`sdk-version.txt`); `wfb build` warns on a mismatch
  (`wfb.build.check_sdk`) and writes `build-info.json`; `wfb doctor`
  reports it. `docs/guide/getting-started.md`.
- **One draw program** — each element is lowered once into a program of
  drawing steps over `Layout` constants and readings (`wfb/draw/`), its
  guards included: the view prints it, the preview evaluates it with the
  barrel's arithmetic transcribed, and a frame is per-element layers with
  the program as JSON (`wfb.draw.layers`, `wfb.draw.jsonform`): text and
  icons as placed tiles, which the editor's browser draws itself
  (`wfb/studio/static/raster.js`, Pillow's primitives byte for byte). A grown outline ring is drawn grown in the preview
  as on the watch (research 28 §7). Garmin's circle and rounded-corner
  rasterisation is not matched (`docs/limitations.md`).
  `docs/development.md`, "Element kinds".
- **Preview in the watch** — `wfb preview --skin` sets the render into
  the simulator skin the device files ship, at its `display.location`
  (`wfb.preview.frame_in_skin`); a device without a skin renders the bare
  screen with one warning. `docs/guide/preview-and-cli.md`.
- **The editor** (`wfb studio`) — a local web app: new from a template,
  open and download a bundle (`.zip` with `face.yaml` and `assets/`, or a
  plain `.yaml`), the canvas's drags (move, resize, an arc's angles, a
  line's ends, snapping) written in the author's units to the key the
  viewed watch reads, every key in an inspector, targets, colours (a
  picker over the face's colours, the 64 named MIP colours and custom
  ones, each picked colour a named swatch, `wfb/edit/colors.py`), the
  accent and data colour settings as explicit lists, schemes (made,
  added, renamed and removed with their roles and styles as one patch
  each, `wfb/edit/schemes.py`), hand sets (from four presets, drawn
  alone, renamed with every `set:`, `wfb/edit/hands.py`; parts in the
  YAML), slots (one card in the Face tab and on the element drawing it,
  types labelled and grouped in `wfb.complications`, the face drawn
  showing any one choice, `PreviewOptions.picks`), styles and fonts,
  faces per browser (a cookie bound to a principal that owns documents,
  one-time claim links, `--single-user`, a `Host` allowlist;
  `wfb/studio/sessions.py`), structure (add any type, reorder, static and
  dynamic, groups), a YAML tab with the schema, a history with undo and
  snapshots that survives restarts, Build for one watch (`wfb build` as a
  subprocess, the `.prg` downloaded), a continuous zoom with real size
  from the device's ppi (calibrated in the browser), and the skin. Every edit but typed text is a
  patch of the text checked by the full load (`wfb/edit/`). The browser
  draws the frame's layers from their JSON (`raster.js`), hit-tests by
  their ink, redraws a move from them, and draws a resize or an angle
  live where the kind declares the result exact
  (`ElementKind.live_handle`); it decides nothing. `docs/guide/studio.md`.

## Removed outright (no shim; the old spelling is an ordinary error)

- `type: carousel`.
- `on_tap:`, now `on_hold:`. `WatchFaceDelegate.onTap` never fires on a live
  face.
- A font `size:` given as a bare number, and `scale:`. Lengths are always
  `%r`/`px`.
- A pasted raw character in `icon:`. Use a catalogue name or
  `icon: "U+XXXX"`.
- Refresh tiers (`WfbCache.mc`, `catalog.Tier`).
- `config: colors:`. Use `config: style:`.
- `vertical_align: baseline`, renamed `bottom`.
- `modes: [always_on]`. Use `aod:` -- the schema error names
  the replacement.
- **Format 1** and `wfb migrate` (removed 2026-10-04): `format: 1` is an
  error. Every format 1 key is gone with it, among
  them the list form of `elements:` (`- id:`), `targets:`/`fonts:`/
  `palette:`/`hands:` at the top level, `color_scheme:`, `palette.x`/
  `config.colors.x` references, `type: shape`/`progress`/
  `complication_slot`, `rounded_rectangle`, `value:`+`format:` on text,
  `when_absent:`/`placeholder:`/`fallback:`, `vertical_align:`,
  `if_unavailable:`, `modes:`, the `static: true` flag, `glyph:`/
  `icon_for:` and the `icon_*` keys; a format 1 key in a format 2 file is
  a schema error naming its replacement.

## Not implemented

See `docs/limitations.md` §2 for the full table and why each item is not
built.

1. `image` elements and the `raw` escape hatch (ADR 0007). Both give a
   friendly error.
2. `overrides:` beyond geometry (`color:`, `visible:`, a font, `touch:`/
   `api:` selectors), and `align:` on `text`/`icon`/`data`, whose
   justification is shared code: build errors.
3. Ticks drawn by a `style: scale` gauge itself (a radial `pattern`
   does them today).
4. `units:` on an expression or a `data` element.
5. **Phone-side settings and `wfb package`.** Phone editing needs a Store
   install, which needs `wfb package` (research 17 §2); wearer settings
   beyond `config:` were decided against, and there is no `.SET` writer
   (ADR 0006 tenth and eleventh amendments). Do not revisit it without
   asking the user.
6. Catalogue generation from the SDK (ADR 0005 §1).
7. `catalog.Source.requires` is set on no source. ADR 0008's check 2 is
   otherwise built (`api-gated`: modules, fields, complication types); the
   hook is read by `wfb.availability.source_unavailable` for a future
   source whose read needs an extra function.
8. Sideloading from the editor (`wfb studio`): it builds and downloads a
   watch's `.prg`; copying it to the watch is by hand (as `wfb install`,
   item 10, is unbuilt).
9. CI does not exist. `mypy --strict` is clean over `wfb/` and runs as
   its own test set (`pytest -m typecheck`, ADR 0001 amendment), by hand;
   its baseline (`tests/mypy-baseline.txt`) is empty.
10. `wfb install`, `package`.
11. A `pattern`'s or `data` element's own `aod: {font: ...}` override,
    any `font:` override naming a `face:` (vector) font, and
    `aod: {filled: ...}` on `type: polygon` (every other override key and
    a `text` element's baked-font override are built) -- all three are friendly build errors, whether the element writes
    the key or inherits it from a group (`Builder.aod_refusal`), never a
    silent no-op.
12. **Non-round screens** (research 16): rectangles resolve, lint,
    preview and build against real device files; every non-round
    shape's visible area is its simulator skin; 2-colour panels
    are black and white only, `palette-mono`; `anchor: subscreen`
    places an element in the Instinct window; `overrides:` patches an
    element's geometry per device id or shape.

13. **Reserved by format 2**, each a friendly "not
    implemented" error today: `components`/`use:`/`with:`, `effects:`, `outline:` on parts, the
    data widget's `parts:`/`arrange:`/`requires:`/`fallback:`, `when:`
    rule lists, and an advisory `static-candidate` lint.
    `docs/limitations.md` §2. `outline:` on the element (every kind but
    `data`, `graph` and a ticked gauge) and on a group is built;
    only the per-part form stays reserved.
