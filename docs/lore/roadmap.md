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

- **`aod:` format and resolution (plan 14 slice 1):** per-element/group
  `hide`/`show`/an override block reusing that kind's own property names,
  key-by-key resolution (element > nearest ancestor group > face default),
  a group's explicit `hide` sticky and unconditional, `visible:` conjoined
  with the element's own. `_aod` (the sleep-frame gate) is emitted only
  when some build target is AMOLED (`Device.is_amoled`), selected at
  runtime per device via `requiresBurnInProtection` -- an all-MIP build
  stays byte-identical with or without `aod:` keys present. `wfb preview
  --aod` renders the resolved set, unrestyled; two new suppressible lints,
  `aod-unreachable` and `aod-empty`. Restyling what the AOD frame actually
  draws (colour/font/thickness ternaries, a separate AOD font, a static
  element's own bypass) is slice 2; `dim:`/`jitter:` are slices 3/5.
  `modes: [always_on]` is removed outright (D3) -- see below.

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
11. `aod: dim:`/`jitter:` (plan 14 §4.5/§5.2, slices 3/5) -- accepted by the
    schema, rejected by the builder with a friendly error. An `aod:`
    override's `color:`/`font:`/`format:`/`thickness:`/etc. actually
    restyling the generated AOD frame, a separate AOD font, and a
    `static:` element's own `aod:` bypassing the buffer (plan 14 slice 2).
    The AMOLED burn-in pixel/luminance lint (plan 14 slice 4).
