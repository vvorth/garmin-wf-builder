# Roadmap: what exists, what was removed, what is missing

`docs/limitations.md` §2 is the **authoritative** list of what is missing.
This file is a turn-one summary; if the two disagree, `limitations.md` is
right and this file needs updating. `docs/guide/` documents everything
listed as shipped.

## Shipped

- **All nine element types:**
  - `group`, `text`, `icon`, `complication_slot`;
  - `shape` (`rectangle`, `rounded_rectangle`, `circle`, `line`, `arc`,
    `ellipse`, `polygon`);
  - `progress` (`arc`, `bar`);
  - `graph` (`line`, `area`, `bars`);
  - `hands` (analog hands, plan 04);
  - `pattern` (plan 05; its text parts come from plan 06).

  `hands` and `pattern` are the two exceptions to "the device does no layout
  arithmetic": the watch rotates or transforms the resolved geometry each
  frame (ADR 0004; `runtime-lib/WfbHands.mc`, `WfbGeom.mc`). Baked pattern
  copies measured about 30× the memory (`docs/research/probes/pattern-cost/`).
- **Placement and drawing:**
  - `align:`/`vertical_align:` on every element with a placement box (plans
    06–07);
  - `static:` (paint-once buffering), `antialias:`, `visible:`,
    `monospace:`, and `min_1px:` (opt-in 1 px floor for relative lengths,
    plan 08);
  - the mapping form of `elements:`.
- **Data:**
  - the full source catalogue, including all 42 `COMPLICATION_TYPE_*` values
    under `complication.*`;
  - the Nerd Fonts icon catalogue, downloaded by setup;
  - every source is a plain per-frame pull read. There are no refresh tiers.
- **Interactivity:**
  - `on_hold:` on every element, touch-and-hold only (constraint 6c);
  - `on_hold: auto`, which picks the launch target from the element's own
    bound value;
  - `Complications.exitTo`.
- **Configuration: all four native axes (ADR 0006):**
  - `accent_color` and `data_color`;
  - Styles, carrying `color_scheme:` and `layouts:` (form A: a container;
    plan 02);
  - the Data axis as `complication_slot`, with icons for all 42 types
    (plan 03).
- **Per-device API gating:**
  - the shared manifest floor stays 3.1.0 (plan 14 slice 6, lowered from
    3.2.0 once `fenix5`/`fenix5x` were installed);
  - a device below 3.1.0 is a friendly `target` build error, not a raw
    `monkeyc` failure (`wfb.build.select_devices`);
  - every complication touch, every `Toybox.Weather` touch (readers and
    forecast graphs; `fenix5`/`fenix5x` lack the module, plan 18 item 2)
    and every missing field is `has`-guarded at runtime
    (`wfb/availability.py`, `Guards.modules`/`fields`);
  - an unavailable binding reads as absent, and lint `api-gated` warns; a
    missing *function* symbol is a build error, `api-gated-unguardable`,
    since there is no runtime guard for an individual function (no
    installed device has one today).

  UNVERIFIED on a real pre-4.2.0 device: that a guarded reference to an
  absent module is harmless at load time. A reader *function* that a device
  lacks would still be a hard build error.
- **System fonts in preview and measurement** (plans 09–10):
  - Garmin's own font files first, then pinned free stand-ins, then
    Pillow's default;
  - `.cft` bitmap fonts decoded for the fenix 6/7 family, fr245 and fr255
    (`docs/research/10-system-fonts.md`).
- **Vector fonts and `curve:` on `text` and on a pattern's own `shape: text`
  part** (plan 11, both slices): a `fonts:` entry can name a device-resident
  scalable face (`face:`) instead of baking one, and a `text` element, or a
  pattern's own text part, can bend it along a line or around a circle
  (`Dc.drawAngledText`/`drawRadialText`) — the only way to rotate or curve
  text, since a baked font cannot. Reaches 44 of the 136 watch-face-capable
  devices; `if_unavailable: error` (default) fails the build per device,
  `hide` lets the element (or, on a pattern, that one part) disappear there
  instead — both are build-time-only guarantees, since the platform can
  still return a null font at runtime. A pattern part's `curve.angle` is
  authored once, in the template's own local frame; a radial pattern
  composes it with each copy's own rotation at codegen/preview time, the
  same way its own `arc` part's `start_angle:` already composes with
  `start:`/`step:` — rotated hour numerals around a dial, each tangent to
  its own radius, is one authored angle, not twelve (plan 11 §5 slice 2).

- **`outline:` on `text` and on a pattern's own `shape: text` part** (plan
  15, all three slices): the stamped-ring substitute for a filled-outline
  draw mode this platform does not have (research 13/14) -- a string drawn
  a handful of times at small pixel offsets in a ring colour, then once
  more, unshifted, in the element's own `color:`. Reaches every draw shape
  a `text` element or pattern text part can take (upright, `curve:
  {style: angled}`, `curve: {style: radial}`), composes with a radial
  pattern's own per-copy rotation the same way `curve:` alone already does,
  and is checked by a new suppressible lint, `text-outline-interior`
  (the interior pass paints over what's beneath it, it does not reveal
  it). Out of scope: `hands`/`icon` parts (plan 15 §13 D5) -- text and
  pattern `shape: text` parts only.

Nothing config-, hands- or pattern-related is verified on a watch or in the
simulator. What is verified is a warning-free real `monkeyc` build and
`wfb preview`.

- **`aod:` format, resolution and restyling (plan 14 slices 1-2):**
  per-element/group `hide`/`show`/an override block reusing that kind's own
  property names, key-by-key resolution (element > nearest ancestor group >
  face default), a group's explicit `hide` sticky and unconditional,
  `visible:` conjoined with the element's own. `_aod` (the sleep-frame gate)
  is emitted only when some build target is AMOLED (`Device.is_amoled`),
  selected at runtime per device via `requiresBurnInProtection` -- an
  all-MIP build stays byte-identical with or without `aod:` keys present.
  Every override key restyles the generated AOD frame for real (slice 2):
  an inline `_aod ? <aod> : <awake>` ternary at the draw call site, measured
  smaller than a second per-element method (`docs/lore/codegen.md`);
  `filled:` toggles the draw call itself; a resource font named only by an
  override is a second resource, loaded in `onEnterSleep` and released in
  `onExitSleep`; a `static:` element with an override skips its buffer and
  draws directly. `wfb preview --aod` renders the resolved set fully
  restyled, matching codegen's own scope (a `pattern`/`complication_slot`
  `font:` override and any vector-font override are not implemented yet).
  Two new suppressible lints, `aod-unreachable` and `aod-empty`.
  `modes: [always_on]` is removed outright (D3) -- see below.
- **`aod: {dim: ...}` (plan 14 slice 3):** scales the luminance of every
  colour the AOD frame draws, override colours excepted -- each channel
  times `dim`, rounded to the nearest integer (`wfb.palette.dim_channel`).
  A build-time-constant colour (a bare hex, or a `palette.<name>`
  reference) is pre-dimmed into a second literal at build time, no runtime
  cost; a `config.colors.<role>` field (or any colour not known until the
  device resolves it) is dimmed on-device instead, by a small generated
  helper doing plain integer arithmetic (`WfbColor.dim`,
  `runtime-lib/WfbColor.mc`) -- the exact same formula, so codegen and
  `wfb preview --aod` agree to the pixel. `dim: 1` and no `dim:` at all both
  normalise to "no dimming" and emit no ternary at all, so a `dim: 1` face's
  generated source is byte-identical to one with no `dim:`; `dim: 0` is a
  schema error (`exclusiveMinimum: 0`) rather than a silent all-black frame.
  The 64-colour palette lint never sees a dimmed colour, since it is a
  synthetic literal never entered into `palette:`/`config:`/
  `color_scheme:`. The alpha route (`Dc.setStroke`'s `0xAARRGGBB`) stays
  UNVERIFIED, per the plan (§4.5): the burn-in lint (slice 4, below) now
  exists and would measure whatever it drew, but the alpha route itself was
  never built to render anything through it.
- **The burn-in lint, `aod-burn-in` (plan 14 slice 4, research 11 §6 D, ADR
  0008 check 8):** measured, not estimated -- renders the resolved `aod:`
  set with `wfb.preview.render` (`wfb preview --aod`'s own function, no
  second renderer) at a sampled worst-case time (`10:08`/`20:08`, full
  battery, `wfb.preview.SAMPLE`'s other defaults unchanged) and scores two
  fractions over the round-masked display area: the share of non-black
  pixels (research 11 §1.1's own "any color other than black" definition)
  and the mean relative luminance (`wfb.palette.Color.relative_luminance`,
  the same Rec. 709/WCAG formula the contrast lint uses, as a fraction of
  full white -- Garmin's own formula is unpublished, research 11 §5). Both
  AMOLED generations' 10% rules are checked at once (lit-pixel share for
  the original Venu, luminance share for Venu 2+, research 11 §1.2), since
  the device files do not say which generation a target is. Reported per
  element: every AOD-shown element is re-rendered alone
  (`dataclasses.replace`'s `items=[placed]`, cheap -- geometry is already
  absolute) and ranked by its own lit-pixel count, and the diagnostic is
  anchored at the biggest contributor's own line. Over 10% (either
  fraction) is `error`, code `aod-burn-in` -- uniquely among this
  project's hard errors, it **is** suppressible, because exceeding it
  breaks nothing the compiler emits (unlike `partial-update`, the other
  AMOLED hard error): at worst the watch's own OS disables always-on for
  the app. Under 10% is a `note` stating both figures, the same
  "the author sees the number on every build" shape `graphics-pool`
  already uses. Never runs on a MIP target (D5). Cost: ~40-70 ms per
  AMOLED target on `examples/features/aod/face.yaml` (two full-frame
  renders plus one per AOD-shown element), negligible against a real
  `monkeyc` build. With the pixel mask on (the default, plan 16), it
  scores the masked frame at its worst of 4 phases and the 3-minute
  static-pixel rule holds by construction, so this check no longer needs
  to see it; `aod: {mask: false}` restores that old gap. It still cannot
  see any time/data combination but the two sampled, or Garmin's actual
  luminance formula.
- **`aod: {jitter: ...}` (plan 14 slice 5): built, then removed
  2026-09-23** to cut codegen complexity (an offset term threaded through
  every emitter, a runtime barrel file and a Python twin kept bit-for-bit
  identical). The key is now a schema error. The per-minute preview tools
  stayed because the replacement needed them: `wfb preview --minute N`
  renders one minute of the day, and `--heatmap` (implies `--aod`) sums
  1,440 renders into one normalised persistence PNG plus a max-persistence
  figure, approximating the simulator's Screen Heat Map.
- **`aod: {mask: ...}` (plan 16, the same day): the replacement, built.**
  A moving 2×2 pixel mask over the whole AOD frame -- one pixel per
  on-screen 2×2 tile stays lit, stepping to a 4-neighbour each minute, 25%
  duty -- on by default (`aod: {mask: false}` opts out). Plan `fd49cab`,
  slice 1 (format + codegen) `3c2b40d`, slice 2 (preview/heatmap/lint)
  `965518a`. The device route is two loops of 1 px `Dc.fillRectangle`
  strips (`runtime-lib/WfbAodMask.mc`, ~454 calls on a 454 px panel) --
  no bitmap, no alpha, no graphics-pool memory, universal symbols only.
  `examples/features/aod/face.yaml` on `fenix847mm` measures **2,726 B**
  with the mask (the default) against **2,447 B** with `mask: false`
  (+279 B), warning-free on all four targets. `wfb.aod_mask` is the
  host-side twin (`docs/lore/codegen.md` has the barrel-detection and
  phase-table lore). `docs/research/15-aod-pixel-masks.md` §7 records why
  this pattern shipped instead of the research's own recommended queen-5.
- **The `getDisplayMode` ladder (plan 14 slice 6, research 11 §6 F):** the
  AOD frame now checks `System.getDisplayMode() == System.DISPLAY_MODE_OFF`
  before drawing anything at all -- not even the frame's own black clear --
  on a device that has the symbol (`fenix847mm`/`fenix947mm` today;
  research 11 §2), since an unlit panel could not show either. Guarded per
  device the same way `requiresBurnInProtection` already is
  (`wfb.availability.Guards.display_mode_guarded`): a mixed AMOLED+MIP
  build wraps the call in `System has :getDisplayMode`, an AMOLED-only
  build where every target has the symbol emits the bare call, and a
  device with neither symbol keeps drawing the resolved `aod:` set on
  every asleep frame exactly as before this slice. `DISPLAY_MODE_LOW_POWER`
  needed no new branch -- it is exactly the frame already drawn while
  `_aod`. `Application.AppBase.onDisplayModeChanged` is deliberately not
  wired to request an update (ADR 0006's 2026-09-23 amendment): `onUpdate`
  already runs once a minute while asleep regardless of display mode, so
  the callback would only shave a worst-case one-minute latency off a
  transition away from `DISPLAY_MODE_OFF`. All-MIP output stays
  byte-identical. This closes plan 14 out; it is deleted (`docs/CLAUDE.md`).

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
2. Per-device `overrides`: writing one is a build error.
3. `segments`/`scale` progress styles.
4. Automatic unit conversion (ADR 0005 §4). Authors convert by hand.
5. **Phone-side settings**, the only route to any on-device config on fr955.
   The work is frozen and incomplete on `wip/phone-settings`, with a safety
   pointer at `backup/pre-integrate`. Treat none of it as working, and do not
   resume without asking the user.
6. Catalogue generation from the SDK (ADR 0005 §1).
7. `catalog.Source.requires` is read by nothing. ADR 0008's check 2 is only
   partly built.
8. **The GUI** (ADR 0002). Unit round-tripping and schema churn make it
   premature (`docs/research/06-authoring-ergonomics.md` §4). If it is ever
   built, build it as a thin client over `wfb/preview.py`, not a second
   renderer.
9. `mypy --strict` and CI. Neither exists.
10. `wfb install`, `package`, `migrate`.
11. A `pattern`'s or `complication_slot`'s own `aod: {font: ...}` override,
    any `font:` override naming a `face:` (vector) font, and
    `aod: {filled: ...}` on `shape: polygon` (plan 14 §4.3, slice 2 built
    every other override key and a `text` element's baked-font override)
    -- all three are friendly build errors, whether the element writes
    the key or inherits it from a group (`Builder._aod_refusal`), never a
    silent no-op.
