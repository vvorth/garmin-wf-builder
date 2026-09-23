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
  - the shared manifest floor stays 3.2.0;
  - every complication touch and every missing field is `has`-guarded at
    runtime (`wfb/availability.py`);
  - an unavailable binding reads as absent, and lint `api-gated` warns.

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
  `monkeyc` build. Cannot see the 3-minute static-pixel rule (a property of
  a frame sequence, not the one rendered), any time/data combination but
  the two sampled, or Garmin's actual luminance formula.
- **`aod: {jitter: ...}` (plan 14 slice 5, §5.2):** a deterministic
  per-minute pixel offset, 1-4 px (Garmin's own cap), accepted at face
  level and on a `group`'s own `aod:` block -- schema-accepted, builder-
  rejected with an explanation everywhere else, since per-element jitter
  would break a design's own relationships (a hand's centre against its
  tick ring). Resolution is "nearest declaration wins", the same
  `min_1px:`/`antialias:` walk (`Builder._resolve_inherited_flag`), so a
  group's own `jitter:` replaces its ancestry's for its whole subtree and
  nested groups never accumulate an offset. The sequence is a constant
  stride (`stride = 2w+1`, coprime with `w²` since `w = 2n+1` is odd)
  through the flattened `(2n+1)x(2n+1)` grid, pure integer arithmetic, one
  Python implementation (`wfb/aod_jitter.py`) and one Monkey C twin
  (`runtime-lib/WfbJitter.mc`) kept bit-for-bit identical: it moves *both*
  axes every single minute, not just the offset pair as a whole -- a first,
  raster-scan cut (step one axis every minute, the other only every `w`
  minutes) passed every property test written against it (bounded,
  deterministic, full grid coverage, the pair never repeating) while still
  leaving a long 1px line's own interior lit for up to `w` minutes, caught
  in review before it shipped (`docs/lore/codegen.md`). Codegen appends
  `+ _aodDxN<n>`/`+ _aodDyN<n>`
  (one field pair per distinct magnitude actually used, computed once at
  the top of the AOD branch and reset to `0` in `onExitSleep`) to every
  coordinate a jittered element's shared draw method uses --
  unconditionally, cheaper than a ternary since the field is `0` except
  while that exact frame is drawing. Reaches every element kind: `shape`
  (including a rebuilt polygon vertex array, since `_POINTS` has no single
  X/Y to suffix), `text` (plain, vector, `outline:`, `curve:`), `progress`,
  `icon`, `graph`, `complication_slot`, `hands` (the rotation centre) and
  `pattern` (the per-copy origin) -- the last two, plus a `curve:`/
  `outline:` anchor, needed no per-call-site editing at all, since they
  already funnel every part's geometry through one shared local origin.
  `wfb preview --aod --minute N` renders any single minute's offset;
  `wfb preview --aod --heatmap` sums 1,440 renders into one normalised PNG
  plus a max-persistence figure, approximating (not replacing) the
  simulator's own Screen Heat Map. Measured: +338 B on `fenix847mm`
  (`examples/features/aod/face.yaml`, one magnitude reaching three
  elements, `docs/lore/codegen.md`).

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
    every other override key and a `text` element's baked-font override,
    and slice 5 built `jitter:`, above) -- all three are friendly build
    errors (`Builder._build_aod_authored`), never a silent no-op.
